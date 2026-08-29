import os
import requests
from flask import Flask, request, jsonify
from langdetect import detect, DetectorFactory, LangDetectException

# Make detection results consistent across runs (langdetect is otherwise
# non-deterministic for ambiguous/short text).
DetectorFactory.seed = 0

app = Flask(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

# Your own Telegram numeric user ID(s), comma-separated (get each from
# @userinfobot). Any private message someone sends directly to the bot
# gets forwarded to every ID listed here, since Telegram has no built-in
# inbox/dashboard for bot owners.
ADMIN_CHAT_IDS = [
    cid.strip()
    for cid in os.environ.get("ADMIN_CHAT_IDS", "").split(",")
    if cid.strip()
]

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# ---------------------------------------------------------------------------
# Language detection via langdetect — fully offline (no external API call),
# so it can never 404/503/rate-limit like Gemini did. It covers 55 languages,
# which is effectively every major world language. Text is compared purely
# by statistical n-gram profiles, so it works for any script.
# ---------------------------------------------------------------------------

# "Please send messages in English." pre-translated for every language code
# that langdetect can return. Keys match langdetect's ISO codes exactly.
WARNINGS = {
    "ar": "يرجى إرسال الرسائل باللغة الإنجليزية.",
    "bg": "Моля, изпращайте съобщения на английски.",
    "bn": "দয়া করে ইংরেজিতে মেসেজ পাঠান।",
    "el": "Παρακαλώ στείλτε μηνύματα στα αγγλικά.",
    "fa": "لطفاً پیام‌ها را به انگلیسی ارسال کنید.",
    "gu": "કૃપા કરીને સંદેશા અંગ્રેજીમાં મોકલો.",
    "he": "אנא שלח הודעות באנגלית.",
    "hi": "कृपया संदेश अंग्रेज़ी में भेजें।",
    "ja": "英語でメッセージを送ってください。",
    "kn": "ದಯವಿಟ್ಟು ಸಂದೇಶಗಳನ್ನು ಇಂಗ್ಲಿಷ್‌ನಲ್ಲಿ ಕಳುಹಿಸಿ.",
    "ko": "영어로 메시지를 보내주세요.",
    "mk": "Ве молиме испраќајте пораки на англиски.",
    "ml": "ദയവായി സന്ദേശങ്ങൾ ഇംഗ്ലീഷിൽ അയയ്ക്കുക.",
    "mr": "कृपया संदेश इंग्रजीत पाठवा.",
    "ne": "कृपया सन्देशहरू अङ्ग्रेजीमा पठाउनुहोस्।",
    "pa": "ਕਿਰਪਾ ਕਰਕੇ ਸੁਨੇਹੇ ਅੰਗਰੇਜ਼ੀ ਵਿੱਚ ਭੇਜੋ।",
    "ru": "Пожалуйста, отправляйте сообщения на английском.",
    "ta": "தயவுசெய்து செய்திகளை ஆங்கிலத்தில் அனுப்பவும்.",
    "te": "దయచేసి సందేశాలను ఆంగ్లంలో పంపండి.",
    "th": "กรุณาส่งข้อความเป็นภาษาอังกฤษ",
    "uk": "Будь ласка, надсилайте повідомлення англійською.",
    "ur": "براہ کرم پیغامات انگریزی میں بھیجیں۔",
    "zh-cn": "请用英语发送消息。",
    "zh-tw": "請用英文發送訊息。",
}


def detect_language(text):
    """
    Returns a langdetect ISO code (e.g. 'en', 'bn', 'fr', 'zh-cn'),
    or 'en' if detection fails/is ambiguous (fail-safe: never warn
    on something we're not sure about).
    """
    try:
        return detect(text)
    except LangDetectException:
        return "en"


def get_warning(lang_code):
    return WARNINGS.get(lang_code)  # None if lang_code == "en" or unmapped


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


def forward_to_admin(user, text):

    if not ADMIN_CHAT_IDS:
        return

    name = (user.get("first_name") or "").strip()
    username = user.get("username")
    tag = f"@{username}" if username else "(no username)"
    user_id = user.get("id")

    notice = (
        f"📩 New private message to the bot\n"
        f"From: {name} {tag}\n"
        f"User ID: {user_id}\n\n"
        f"{text}"
    )

    for chat_id in ADMIN_CHAT_IDS:
        try:
            tg("sendMessage", {"chat_id": chat_id, "text": notice})
        except Exception as e:
            print(f"Failed to forward to admin {chat_id}:", repr(e))


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

        # Ignore other bots (but not commands here — /start in a private
        # chat still needs to reach the forwarding block below)
        if user.get("is_bot"):
            return jsonify({"ok": True})

        # Someone DM'd the bot directly (private chat, not the group).
        # Forward it to the owner so it's actually visible somewhere,
        # since Telegram gives bot owners no inbox of their own.
        if chat.get("type") == "private":
            forward_to_admin(user, text)
            return jsonify({"ok": True})

        # Ignore commands (group only, from here on)
        if text.startswith("/"):
            return jsonify({"ok": True})

        # Ignore group admins
        if is_admin(chat_id, user_id):
            return jsonify({"ok": True})

        # Ignore very short messages (langdetect is unreliable below ~3 letters)
        if len("".join(ch for ch in text if ch.isalpha())) < 3:
            return jsonify({"ok": True})

        lang_code = detect_language(text)
        warning = get_warning(lang_code)

        if lang_code != "en" and warning:

            send_reply(
                chat_id,
                message["message_id"],
                warning
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
