import os
import sqlite3
import threading
import requests
from flask import Flask, request, jsonify
from langdetect import detect, DetectorFactory, LangDetectException

# Make langdetect deterministic.
DetectorFactory.seed = 0

app = Flask(__name__)

# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================
BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
SUPPORT_GROUP_ID = os.environ.get("SUPPORT_GROUP_ID", "").strip()

# Two (or more) admin Telegram numeric user IDs, comma-separated.
ADMIN_CHAT_IDS = {
    x.strip()
    for x in os.environ.get("ADMIN_CHAT_IDS", "").split(",")
    if x.strip()
}

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# SQLite stores customer -> forum topic mapping.
DB_PATH = os.environ.get("DB_PATH", "customer_topics.db")
db_lock = threading.Lock()


# ============================================================
# DATABASE
# ============================================================
def db_connect():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS customer_topics (
            user_id INTEGER PRIMARY KEY,
            topic_id INTEGER NOT NULL UNIQUE,
            first_name TEXT DEFAULT '',
            username TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    return conn


with db_connect() as conn:
    pass


def get_topic(user_id):
    with db_lock:
        conn = db_connect()
        row = conn.execute(
            "SELECT topic_id FROM customer_topics WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        conn.close()
    return row[0] if row else None


def get_user_by_topic(topic_id):
    with db_lock:
        conn = db_connect()
        row = conn.execute(
            "SELECT user_id FROM customer_topics WHERE topic_id = ?",
            (topic_id,)
        ).fetchone()
        conn.close()
    return row[0] if row else None


def save_topic(user_id, topic_id, first_name="", username=""):
    with db_lock:
        conn = db_connect()
        conn.execute(
            """
            INSERT INTO customer_topics
                (user_id, topic_id, first_name, username)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                topic_id = excluded.topic_id,
                first_name = excluded.first_name,
                username = excluded.username
            """,
            (user_id, topic_id, first_name or "", username or "")
        )
        conn.commit()
        conn.close()


# ============================================================
# TELEGRAM API
# ============================================================
def tg(method, payload=None):
    response = requests.post(
        f"{TELEGRAM_API}/{method}",
        json=payload or {},
        timeout=30
    )

    try:
        data = response.json()
    except Exception:
        response.raise_for_status()
        raise

    if not data.get("ok"):
        raise RuntimeError(
            f"Telegram {method} failed: "
            f"{data.get('description', data)}"
        )

    return data


# ============================================================
# LANGUAGE DETECTOR
# ============================================================
# Warning shown in the support group when a non-English message
# is sent by a non-admin.
WARNINGS = {
    "ar": "يرجى إرسال الرسائل باللغة الإنجليزية.",
    "bg": "Моля, изпращайте съобщения на английски.",
    "bn": "দয়া করে ইংরেজিতে মেসেজ পাঠান।",
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
    try:
        return detect(text)
    except LangDetectException:
        # Fail safe: don't warn when detection is uncertain.
        return "en"


def send_group_language_warning(chat_id, message_id, text):
    letters = "".join(ch for ch in text if ch.isalpha())

    # langdetect is unreliable for extremely short messages.
    if len(letters) < 3:
        return

    lang_code = detect_language(text)
    warning = WARNINGS.get(lang_code)

    if warning:
        tg(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": warning,
                "reply_to_message_id": message_id,
                "allow_sending_without_reply": True
            }
        )


# ============================================================
# CUSTOMER / TOPIC HELPERS
# ============================================================
def safe_name(user):
    first = (user.get("first_name") or "").strip()
    last = (user.get("last_name") or "").strip()
    full = " ".join(x for x in (first, last) if x)
    return full or "Unknown User"


def create_customer_topic(user):
    if not SUPPORT_GROUP_ID:
        raise RuntimeError("SUPPORT_GROUP_ID is not configured.")

    user_id = user["id"]

    # Telegram forum topic names have a limited practical length.
    title = f"{safe_name(user)[:35]} | {user_id}"

    result = tg(
        "createForumTopic",
        {
            "chat_id": SUPPORT_GROUP_ID,
            "name": title
        }
    )

    topic_id = result["result"]["message_thread_id"]

    save_topic(
        user_id=user_id,
        topic_id=topic_id,
        first_name=user.get("first_name", ""),
        username=user.get("username", "")
    )

    username = (
        f"@{user['username']}"
        if user.get("username")
        else "(no username)"
    )

    info = (
        "👤 CUSTOMER CHAT\n\n"
        f"Name: {safe_name(user)}\n"
        f"Username: {username}\n"
        f"User ID: {user_id}\n\n"
        "💬 Reply to the customer's message in this topic "
        "to send your reply to the customer."
    )

    try:
        tg(
            "sendMessage",
            {
                "chat_id": SUPPORT_GROUP_ID,
                "message_thread_id": topic_id,
                "text": info
            }
        )
    except Exception as e:
        print("Could not send topic info:", repr(e))

    return topic_id


def get_or_create_topic(user):
    topic_id = get_topic(user["id"])

    if topic_id is not None:
        return topic_id

    return create_customer_topic(user)


# ============================================================
# CUSTOMER -> TOPIC
# ============================================================
def forward_customer_message(message, user):
    topic_id = get_or_create_topic(user)

    text = (message.get("text") or "").strip()

    username = (
        f"@{user['username']}"
        if user.get("username")
        else "(no username)"
    )

    header = (
        f"👤 {safe_name(user)} {username}\n"
        f"🆔 {user['id']}\n\n"
    )

    if text:
        tg(
            "sendMessage",
            {
                "chat_id": SUPPORT_GROUP_ID,
                "message_thread_id": topic_id,
                "text": header + text
            }
        )
        return

    # Copy photos, videos, documents, voice notes, stickers, etc.
    # when Telegram permits copying them.
    try:
        tg(
            "copyMessage",
            {
                "chat_id": SUPPORT_GROUP_ID,
                "from_chat_id": message["chat"]["id"],
                "message_id": message["message_id"],
                "message_thread_id": topic_id
            }
        )

        tg(
            "sendMessage",
            {
                "chat_id": SUPPORT_GROUP_ID,
                "message_thread_id": topic_id,
                "text": header + "📎 Customer sent a non-text message."
            }
        )

    except Exception as e:
        print("Customer non-text copy failed:", repr(e))

        tg(
            "sendMessage",
            {
                "chat_id": SUPPORT_GROUP_ID,
                "message_thread_id": topic_id,
                "text": header +
                        "📎 Customer sent a message that could not be copied."
            }
        )


# ============================================================
# ADMIN -> CUSTOMER
# ============================================================
def relay_admin_reply(message):
    chat_id = str(message.get("chat", {}).get("id", ""))
    admin_id = str(message.get("from", {}).get("id", ""))

    if chat_id != SUPPORT_GROUP_ID:
        return False

    if admin_id not in ADMIN_CHAT_IDS:
        return False

    topic_id = message.get("message_thread_id")

    if not topic_id:
        return False

    target_user_id = get_user_by_topic(topic_id)

    # This is not one of our customer topics.
    if target_user_id is None:
        return False

    text = (message.get("text") or "").strip()

    if text:
        tg(
            "sendMessage",
            {
                "chat_id": target_user_id,
                "text": text
            }
        )
        return True

    # Relay admin media/files too.
    try:
        tg(
            "copyMessage",
            {
                "chat_id": target_user_id,
                "from_chat_id": message["chat"]["id"],
                "message_id": message["message_id"]
            }
        )
        return True

    except Exception as e:
        print("Admin non-text relay failed:", repr(e))
        return False


# ============================================================
# WEBHOOK
# ============================================================
@app.get("/")
def home():
    return "Noon Customer Support Bot is running."


@app.get("/health")
def health():
    return jsonify({
        "ok": True,
        "support_group_configured": bool(SUPPORT_GROUP_ID),
        "admins_configured": len(ADMIN_CHAT_IDS)
    })


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

        chat = message.get("chat", {})
        user = message.get("from", {})

        chat_id = chat.get("id")
        user_id = user.get("id")

        if not chat_id or not user_id:
            return jsonify({"ok": True})

        # Never process messages sent by bots.
        if user.get("is_bot"):
            return jsonify({"ok": True})

        # --------------------------------------------------------
        # PRIVATE CHAT:
        # Customer -> Bot -> Customer's Forum Topic
        # --------------------------------------------------------
        if chat.get("type") == "private":
            if not SUPPORT_GROUP_ID:
                print("ERROR: SUPPORT_GROUP_ID is not configured.")
                return jsonify({"ok": True})

            # Admins can use the bot privately without becoming
            # customer records.
            if str(user_id) in ADMIN_CHAT_IDS:
                return jsonify({"ok": True})

            forward_customer_message(message, user)
            return jsonify({"ok": True})

        # --------------------------------------------------------
        # SUPPORT FORUM GROUP:
        # A) Admin reply -> customer
        # B) Non-admin group message in a customer topic -> language warning
        # --------------------------------------------------------
        if str(chat_id) == SUPPORT_GROUP_ID:

            # Admin's topic reply is sent to the mapped customer.
            if relay_admin_reply(message):
                return jsonify({"ok": True})

            # Only normal text messages need language detection.
            text = (message.get("text") or "").strip()

            if not text:
                return jsonify({"ok": True})

            # Ignore commands such as /start, /help, etc.
            if text.startswith("/"):
                return jsonify({"ok": True})

            # Ignore admins/owner for language warning.
            if str(user_id) in ADMIN_CHAT_IDS:
                return jsonify({"ok": True})

            # Also check actual Telegram admin status, so other group
            # administrators aren't warned.
            try:
                member = tg(
                    "getChatMember",
                    {
                        "chat_id": chat_id,
                        "user_id": user_id
                    }
                )
                status = member.get("result", {}).get("status")

                if status in {"creator", "administrator"}:
                    return jsonify({"ok": True})

            except Exception as e:
                print("Admin status check failed:", repr(e))

            # Preserve the old language-warning functionality.
            send_group_language_warning(
                chat_id,
                message["message_id"],
                text
            )

            return jsonify({"ok": True})

        # Ignore messages from unrelated chats/groups.
        return jsonify({"ok": True})

    except Exception as e:
        # Return 200 so Telegram does not endlessly retry an update.
        print("Processing error:", repr(e))

    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
