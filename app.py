import os
import requests
import psycopg2
from flask import Flask, request, jsonify
from langdetect import detect, DetectorFactory, LangDetectException

# ============================================================
# BASIC SETTINGS
# ============================================================

DetectorFactory.seed = 0

app = Flask(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

SUPPORT_GROUP_ID = int(os.environ["SUPPORT_GROUP_ID"])

LANGUAGE_GROUP_ID = os.environ.get(
    "LANGUAGE_GROUP_ID", ""
).strip()

DATABASE_URL = os.environ["DATABASE_URL"]

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"


# ============================================================
# DATABASE
# ============================================================

def db_connect():
    return psycopg2.connect(DATABASE_URL)


def init_database():
    conn = db_connect()

    try:
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS customer_topics (
                customer_id BIGINT PRIMARY KEY,
                topic_id BIGINT UNIQUE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()
        cur.close()

    finally:
        conn.close()


def get_customer_topic(customer_id):
    conn = db_connect()

    try:
        cur = conn.cursor()

        cur.execute(
            """
            SELECT topic_id
            FROM customer_topics
            WHERE customer_id = %s
            """,
            (customer_id,)
        )

        row = cur.fetchone()

        cur.close()

        if row:
            return int(row[0])

        return None

    finally:
        conn.close()


def get_customer_by_topic(topic_id):
    conn = db_connect()

    try:
        cur = conn.cursor()

        cur.execute(
            """
            SELECT customer_id
            FROM customer_topics
            WHERE topic_id = %s
            """,
            (topic_id,)
        )

        row = cur.fetchone()

        cur.close()

        if row:
            return int(row[0])

        return None

    finally:
        conn.close()


def save_customer_topic(customer_id, topic_id):
    conn = db_connect()

    try:
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO customer_topics
                (customer_id, topic_id)
            VALUES
                (%s, %s)
            ON CONFLICT (customer_id)
            DO UPDATE SET topic_id = EXCLUDED.topic_id
            """,
            (customer_id, topic_id)
        )

        conn.commit()
        cur.close()

    finally:
        conn.close()


init_database()


# ============================================================
# TELEGRAM API
# ============================================================

def tg(method, payload=None):

    response = requests.post(
        f"{TELEGRAM_API}/{method}",
        json=payload or {},
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    if not data.get("ok"):
        raise Exception(
            f"Telegram API error in {method}: {data}"
        )

    return data


# ============================================================
# LANGUAGE WARNINGS
# ============================================================

WARNINGS = {

    "ar":
        "يرجى إرسال الرسائل باللغة الإنجليزية.",

    "bn":
        "দয়া করে ইংরেজিতে মেসেজ পাঠান।",

    "ur":
        "براہ کرم پیغامات انگریزی میں بھیجیں۔",

    "hi":
        "कृपया संदेश अंग्रेज़ी में भेजें।",

    "fa":
        "لطفاً پیام‌ها را به انگلیسی ارسال کنید.",

    "ru":
        "Пожалуйста, отправляйте сообщения на английском.",

    "uk":
        "Будь ласка, надсилайте повідомлення англійською.",

    "fr":
        "Veuillez envoyer les messages en anglais.",

    "de":
        "Bitte senden Sie Nachrichten auf Englisch.",

    "es":
        "Por favor, envíe los mensajes en inglés.",

    "it":
        "Per favore, invia i messaggi in inglese.",

    "pt":
        "Por favor, envie as mensagens em inglês.",

    "tr":
        "Lütfen mesajları İngilizce gönderin.",

    "id":
        "Silakan kirim pesan dalam bahasa Inggris.",

    "ms":
        "Sila hantar mesej dalam bahasa Inggeris.",

    "ta":
        "தயவுசெய்து செய்திகளை ஆங்கிலத்தில் அனுப்பவும்.",

    "te":
        "దయచేసి సందేశాలను ఆంగ్లంలో పంపండి.",

    "ml":
        "ദയവായി സന്ദേശങ്ങളെ ഇംഗ്ലീഷിൽ അയയ്ക്കുക.",

    "kn":
        "ದಯವಿಟ್ಟು ಸಂದೇಶಗಳನ್ನು ಇಂಗ್ಲಿಷ್‌ನಲ್ಲಿ ಕಳುಹಿಸಿ.",

    "gu":
        "કૃપા કરીને સંદેશા અંગ્રેજીમાં મોકલો.",

    "pa":
        "ਕਿਰਪਾ ਕਰਕੇ ਸੁਨੇਹੇ ਅੰਗਰੇਜ਼ੀ ਵਿੱਚ ਭੇਜੋ.",

    "mr":
        "कृपया संदेश इंग्रजीत पाठवा.",

    "ne":
        "कृपया सन्देशहरू अङ्ग्रेजीमा पठाउनुहोस्।",

    "ja":
        "英語でメッセージを送ってください。",

    "ko":
        "영어로 메시지를 보내주세요.",

    "th":
        "กรุณาส่งข้อความเป็นภาษาอังกฤษ",

    "zh-cn":
        "请用英语发送消息。",

    "zh-tw":
        "請用英文發送訊息。"
}


def detect_language(text):

    try:
        return detect(text)

    except LangDetectException:
        return "en"

    except Exception:
        return "en"


def send_language_warning(message):

    text = (
        message.get("text")
        or ""
    ).strip()

    if not text:
        return

    letters = "".join(
        character
        for character in text
        if character.isalpha()
    )

    if len(letters) < 3:
        return

    language = detect_language(text)

    if language == "en":
        return

    warning = WARNINGS.get(
        language,
        "Please send messages in English."
    )

    tg(
        "sendMessage",
        {
            "chat_id": message["chat"]["id"],
            "text": warning,
            "reply_to_message_id": message["message_id"],
            "allow_sending_without_reply": True
        }
    )


# ============================================================
# CREATE / GET CUSTOMER TOPIC
# ============================================================

def create_customer_topic(user):

    customer_id = int(user["id"])

    # --------------------------------------------------------
    # Check database first
    # --------------------------------------------------------

    existing_topic = get_customer_topic(customer_id)

    if existing_topic:
        return existing_topic

    first_name = (
        user.get("first_name")
        or "Customer"
    )

    username = user.get("username")

    if username:

        topic_name = (
            f"👤 {first_name} "
            f"(@{username}) - {customer_id}"
        )

    else:

        topic_name = (
            f"👤 {first_name} - {customer_id}"
        )

    topic_name = topic_name[:128]

    # --------------------------------------------------------
    # Create Telegram forum topic
    # --------------------------------------------------------

    result = tg(
        "createForumTopic",
        {
            "chat_id": SUPPORT_GROUP_ID,
            "name": topic_name
        }
    )

    topic_id = result[
        "result"
    ]["message_thread_id"]

    # --------------------------------------------------------
    # IMPORTANT:
    # Save mapping permanently in PostgreSQL
    # --------------------------------------------------------

    save_customer_topic(
        customer_id,
        topic_id
    )

    print(
        f"Created topic {topic_id} "
        f"for customer {customer_id}"
    )

    return topic_id


# ============================================================
# CUSTOMER PRIVATE MESSAGE → SUPPORT GROUP
# ============================================================

def send_customer_message_to_support(
    user,
    text
):

    customer_id = int(user["id"])

    topic_id = create_customer_topic(user)

    first_name = (
        user.get("first_name")
        or "Customer"
    )

    username = user.get("username")

    if username:

        customer_name = (
            f"{first_name} (@{username})"
        )

    else:

        customer_name = first_name

    support_message = (
        f"👤 Customer: {customer_name}\n"
        f"🆔 User ID: {customer_id}\n\n"
        f"{text}"
    )

    tg(
        "sendMessage",
        {
            "chat_id": SUPPORT_GROUP_ID,
            "message_thread_id": topic_id,
            "text": support_message
        }
    )

    print(
        f"Customer {customer_id} -> "
        f"Topic {topic_id}"
    )


# ============================================================
# ADMIN MESSAGE → CUSTOMER
# ============================================================

def send_admin_message_to_customer(message):

    text = (
        message.get("text")
        or ""
    ).strip()

    if not text:
        print("Support message has no text")
        return False

    # --------------------------------------------------------
    # IMPORTANT:
    # Telegram sends message_thread_id for forum topics.
    # --------------------------------------------------------

    topic_id = message.get(
        "message_thread_id"
    )

    if not topic_id:

        print(
            "No message_thread_id in support message"
        )

        return False

    try:
        topic_id = int(topic_id)

    except Exception:

        print(
            "Invalid topic ID:",
            topic_id
        )

        return False

    # --------------------------------------------------------
    # Find customer from permanent DB mapping
    # --------------------------------------------------------

    customer_id = get_customer_by_topic(
        topic_id
    )

    if not customer_id:

        print(
            "Could not find customer for "
            f"topic {topic_id}"
        )

        return False

    # --------------------------------------------------------
    # Send admin message to customer
    # --------------------------------------------------------

    tg(
        "sendMessage",
        {
            "chat_id": customer_id,
            "text": text
        }
    )

    print(
        f"Admin message sent to customer "
        f"{customer_id} "
        f"from topic {topic_id}"
    )

    return True


# ============================================================
# WEBHOOK
# ============================================================

@app.post("/webhook")
def webhook():

    # --------------------------------------------------------
    # WEBHOOK SECRET
    # --------------------------------------------------------

    if WEBHOOK_SECRET:

        supplied_secret = request.headers.get(
            "X-Telegram-Bot-Api-Secret-Token",
            ""
        )

        if supplied_secret != WEBHOOK_SECRET:

            print("Wrong webhook secret")

            return "forbidden", 403

    update = request.get_json(
        silent=True
    ) or {}

    try:

        # ----------------------------------------------------
        # Only normal message updates
        # ----------------------------------------------------

        message = update.get("message")

        if not message:

            return jsonify({
                "ok": True
            })

        user = message.get(
            "from",
            {}
        )

        chat = message.get(
            "chat",
            {}
        )

        chat_id = chat.get("id")

        text = (
            message.get("text")
            or ""
        ).strip()

        # ----------------------------------------------------
        # Ignore messages sent by bots
        # ----------------------------------------------------

        if user.get("is_bot"):

            return jsonify({
                "ok": True
            })

        if not chat_id:

            return jsonify({
                "ok": True
            })

        # ====================================================
        # CUSTOMER PRIVATE CHAT
        # ====================================================

        if chat.get("type") == "private":

            if not text:

                return jsonify({
                    "ok": True
                })

            send_customer_message_to_support(
                user,
                text
            )

            return jsonify({
                "ok": True
            })

        # ====================================================
        # SECRET SUPPORT GROUP
        # ====================================================

        if int(chat_id) == SUPPORT_GROUP_ID:

            # Ignore bot commands
            if text.startswith("/"):

                return jsonify({
                    "ok": True
                })

            # ------------------------------------------------
            # ANY HUMAN ADMIN / STAFF MESSAGE
            # IN A CUSTOMER TOPIC WILL BE SENT TO CUSTOMER
            # ------------------------------------------------

            handled = send_admin_message_to_customer(
                message
            )

            if not handled:

                print(
                    "Support message was not "
                    "linked to a customer."
                )

            return jsonify({
                "ok": True
            })

        # ====================================================
        # FIRST LANGUAGE GROUP
        # ====================================================

        if (
            LANGUAGE_GROUP_ID
            and str(chat_id)
            == LANGUAGE_GROUP_ID
        ):

            if text.startswith("/"):

                return jsonify({
                    "ok": True
                })

            send_language_warning(
                message
            )

            return jsonify({
                "ok": True
            })

        # ====================================================
        # OTHER GROUPS
        # ====================================================

        return jsonify({
            "ok": True
        })

    except Exception as e:

        print(
            "PROCESSING ERROR:",
            repr(e)
        )

        return jsonify({
            "ok": True
        })


# ============================================================
# HOME
# ============================================================

@app.get("/")
def home():

    return "Noon Support Bot is running."


@app.get("/health")
def health():

    return jsonify({
        "ok": True
    })


# ============================================================
# START SERVER
# ============================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            "10000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
