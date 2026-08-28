import os
import json
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.5-flash-lite:generateContent"
)

def tg(method, payload=None):
    r = requests.post(f"{TELEGRAM_API}/{method}", json=payload or {}, timeout=20)
    r.raise_for_status()
    return r.json()

def is_admin(chat_id, user_id):
    try:
        data = tg("getChatMember", {"chat_id": chat_id, "user_id": user_id})
        status = data.get("result", {}).get("status")
        return status in {"creator", "administrator"}
    except Exception:
        return False

def analyze_language(text):
    prompt = f"""
You are a language detector for a Telegram group moderation bot.

Task:
1. Detect whether the message is primarily English.
2. If it is NOT primarily English, identify the language in English.
3. Create a very short warning IN THE SAME LANGUAGE as the user's message telling them:
   "Please send messages in English."
4. If the message is primarily English, do not create a warning.

Return ONLY valid JSON with exactly these keys:
{{
  "is_english": true or false,
  "language": "English or language name",
  "reply": "warning in the same language, or empty string"
}}

Important:
- Do not reply to a message that is clearly English.
- For mixed messages, decide based on the dominant natural-language content.
- Do not treat emojis, URLs, usernames, numbers, or product codes as a non-English language.
- Keep the warning concise and polite.

Message:
{text}
""".strip()

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
        },
    }

    r = requests.post(
        GEMINI_URL,
        params={"key": GEMINI_API_KEY},
        json=payload,
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()

    candidate = data["candidates"][0]["content"]["parts"][0]["text"]
    result = json.loads(candidate)

    return {
        "is_english": bool(result.get("is_english", True)),
        "language": str(result.get("language", "")),
        "reply": str(result.get("reply", "")).strip(),
    }

def send_reply(chat_id, reply_to_message_id, text, user_id=None):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "reply_to_message_id": reply_to_message_id,
        "allow_sending_without_reply": True,
    }
    # This mentions the user by replying to their message, rather than
    # relying on a username. It works even when the user has no username.
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
        supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if supplied != WEBHOOK_SECRET:
            return "forbidden", 403

    update = request.get_json(silent=True) or {}

    try:
        message = update.get("message") or update.get("edited_message")
        if not message:
            return jsonify({"ok": True})

        # Ignore channel posts, service messages, and messages without text.
        text = (message.get("text") or "").strip()
        if not text:
            return jsonify({"ok": True})

        chat = message.get("chat", {})
        user = message.get("from", {})
        chat_id = chat.get("id")
        user_id = user.get("id")

        if not chat_id or not user_id:
            return jsonify({"ok": True})

        # Ignore messages from bots and Telegram commands.
        if user.get("is_bot") or text.startswith("/"):
            return jsonify({"ok": True})

        # Ignore admins/owner so the bot does not police staff.
        if is_admin(chat_id, user_id):
            return jsonify({"ok": True})

        # Very short messages made only of punctuation/numbers/emoji are not useful
        # for language detection.
        if len("".join(ch for ch in text if ch.isalpha())) < 3:
            return jsonify({"ok": True})

        result = analyze_language(text)

        if not result["is_english"] and result["reply"]:
            send_reply(
                chat_id,
                message["message_id"],
                result["reply"],
            )

    except Exception as e:
        # Do not return Telegram-retry-triggering 5xx for ordinary processing errors.
        print("Processing error:", repr(e))

    return jsonify({"ok": True})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
