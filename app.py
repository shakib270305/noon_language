import os
import re
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# ---------------------------------------------------------------------------
# Language detection by Unicode script — no external API call, so this is
# instant and can never 404/503/rate-limit. Covers the languages your group
# actually needs (based on the rules message: Arabic, Bangla, Urdu, Hindi,
# English). Any other script falls back to a generic English-only warning.
# ---------------------------------------------------------------------------

SCRIPT_RANGES = {
    "bn": re.compile(r"[\u0980-\u09FF]"),          # Bengali
    "ar_ur": re.compile(r"[\u0600-\u06FF]"),        # Arabic + Urdu (shared script)
    "hi": re.compile(r"[\u0900-\u097F]"),          # Devanagari (Hindi)
    "latin": re.compile(r"[A-Za-z]"),
}

# Characters that only appear in Urdu, not in standard Arabic.
# If any of these show up in an Arabic-script message, treat it as Urdu.
URDU_ONLY_CHARS = re.compile(
    r"[\u0679\u0688\u0691\u06A9\u06AF\u06BA\u06BE\u06C1\u06C3\u06D2]"
)

WARNINGS = {
    "bn": "দয়া করে ইংরেজিতে মেসেজ পাঠান।",
    "ar": "يرجى إرسال الرسائل باللغة الإنجليزية.",
    "ur": "براہ کرم پیغامات انگریزی میں بھیجیں۔",
    "hi": "कृपया संदेश अंग्रेज़ी में भेजें।",
    # fallback for any other non-English script we don't have a translation for
    "default": "Please send messages in English.",
}


def detect_language(text):
    """
    Returns a language code: 'en', 'bn', 'ar', 'ur', 'hi', or 'other'.
    Decision is based on which script has the most characters in the text.
    """

    counts = {
        "bn": len(SCRIPT_RANGES["bn"].findall(text)),
        "ar_ur": len(SCRIPT_RANGES["ar_ur"].findall(text)),
        "hi": len(SCRIPT_RANGES["hi"].findall(text)),
        "latin": len(SCRIPT_RANGES["latin"].findall(text)),
    }

    # Nothing but latin letters (or no letters at all, e.g. only emoji/numbers)
    # -> treat as English, matches "don't warn on emojis/numbers" requirement.
    if counts["bn"] == 0 and counts["ar_ur"] == 0 and counts["hi"] == 0:
        return "en"

    top_script = max(counts, key=counts.get)

    if top_script == "bn":
        return "bn"

    if top_script == "hi":
        return "hi"

    if top_script == "ar_ur":
        return "ur" if URDU_ONLY_CHARS.search(text) else "ar"

    return "en"


def get_warning(lang_code):
    return WARNINGS.get(lang_code, WARNINGS["default"])


def tg(method, payload=None):
    r = requests.post(
        f"{TELEGRAM_API}/{method}",
        json=payload or {},
        timeout=20
    )
    r.raise_for_status()
    return r.json()


def is_admin(chat_id, user_id):
    try:
        data = tg(
            "getChatMember",
            {
                "chat_id": chat_id,
                "user_id": user_id
            }
        )

        status = data.get("result", {}).get("status")

        return status in {"creator", "administrator"}

    except Exception:
        return False


def send_reply(chat_id, reply_to_message_id, text):

    payload = {
        "chat_id": chat_id,
        "text": text,
        "reply_to_message_id": reply_to_message_id,
        "allow_sending_without_reply": True
    }

    tg("sendMessage", payload)


@app.get("/")
def home():
    return "Noon Assistant is running."


@app.get("/health")
def health():
    return jsonify({"ok": True})


@app.post("/webhook")
def webhook():

    if WEBHOOK_SECRET:

        supplied = request.headers.get(
            "X-Telegram-Bot-Api-Secret-Token",
            ""
        )

        if supplied != WEBHOOK_SECRET:
            return "forbidden", 403

    update = request.get_json(silent=True) or {}

    try:

        message = (
            update.get("message")
            or update.get("edited_message")
        )

        if not message:
            return jsonify({"ok": True})

        text = (message.get("text") or "").strip()

        if not text:
            return jsonify({"ok": True})

        chat = message.get("chat", {})
        user = message.get("from", {})

        chat_id = chat.get("id")
        user_id = user.get("id")

        if not chat_id or not user_id:
            return jsonify({"ok": True})

        # Ignore bots and commands
        if user.get("is_bot") or text.startswith("/"):
            return jsonify({"ok": True})

        # Ignore group admins
        if is_admin(chat_id, user_id):
            return jsonify({"ok": True})

        # Ignore very short messages
        if len("".join(ch for ch in text if ch.isalpha())) < 3:
            return jsonify({"ok": True})

        lang_code = detect_language(text)

        if lang_code != "en":

            send_reply(
                chat_id,
                message["message_id"],
                get_warning(lang_code)
            )

    except Exception as e:

        print("Processing error:", repr(e))

    return jsonify({"ok": True})


if __name__ == "__main__":

    port = int(os.environ.get("PORT", "10000"))

    app.run(
        host="0.0.0.0",
        port=port
    )
