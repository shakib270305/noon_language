import os
import re
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

WEBHOOK_SECRET = os.environ.get(
    "WEBHOOK_SECRET",
    ""
)

SUPPORT_GROUP_ID = int(
    os.environ["SUPPORT_GROUP_ID"]
)

LANGUAGE_GROUP_ID = os.environ.get(
    "LANGUAGE_GROUP_ID",
    ""
).strip()

DATABASE_URL = os.environ["DATABASE_URL"]

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"


# ============================================================
# DATABASE
# ============================================================

def db_connect():
    return psycopg2.connect(
        DATABASE_URL
    )


def init_database():

    conn = db_connect()

    try:

        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS customer_topics (
                customer_id BIGINT PRIMARY KEY,
                topic_id BIGINT UNIQUE NOT NULL,
                display_number INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE SEQUENCE IF NOT EXISTS
                customer_display_seq START 1
        """)

        cur.execute("""
            ALTER TABLE customer_topics
            ADD COLUMN IF NOT EXISTS display_number INTEGER
        """)

        conn.commit()

        cur.close()

    finally:

        conn.close()


def get_or_create_display_number(customer_id):
    """
    Returns a small, anonymous, sequential number to represent this
    customer everywhere agents can see it (topic names, headers) —
    never their real name, username, or Telegram user id.
    """

    conn = db_connect()

    try:

        cur = conn.cursor()

        cur.execute(
            """
            SELECT display_number
            FROM customer_topics
            WHERE customer_id = %s
            """,
            (customer_id,)
        )

        row = cur.fetchone()

        if row and row[0] is not None:

            cur.close()

            return int(row[0])

        cur.execute(
            "SELECT nextval('customer_display_seq')"
        )

        display_number = int(
            cur.fetchone()[0]
        )

        cur.close()

        return display_number

    finally:

        conn.close()


def get_customer_id_by_display_number(display_number):

    conn = db_connect()

    try:

        cur = conn.cursor()

        cur.execute(
            """
            SELECT customer_id
            FROM customer_topics
            WHERE display_number = %s
            """,
            (display_number,)
        )

        row = cur.fetchone()

        cur.close()

        if row:

            return int(row[0])

        return None

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


def save_customer_topic(
    customer_id,
    topic_id,
    display_number
):

    conn = db_connect()

    try:

        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO customer_topics
                (customer_id, topic_id, display_number)
            VALUES
                (%s, %s, %s)
            ON CONFLICT (customer_id)
            DO UPDATE SET
                topic_id = EXCLUDED.topic_id,
                display_number = COALESCE(
                    customer_topics.display_number,
                    EXCLUDED.display_number
                )
            """,
            (
                customer_id,
                topic_id,
                display_number
            )
        )

        conn.commit()

        cur.close()

    finally:

        conn.close()


# Initialize database when app starts
init_database()


# ============================================================
# TELEGRAM API
# ============================================================

def tg(
    method,
    payload=None
):

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

    language = detect_language(
        text
    )

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

    customer_id = int(
        user["id"]
    )

    # --------------------------------------------------------
    # First check PostgreSQL
    # --------------------------------------------------------

    existing_topic = get_customer_topic(
        customer_id
    )

    if existing_topic:

        print(
            f"Existing topic {existing_topic} "
            f"found for customer {customer_id}"
        )

        display_number = get_or_create_display_number(
            customer_id
        )

        return existing_topic, display_number

    # --------------------------------------------------------
    # Create new topic — deliberately anonymous. Agents in the
    # support group must not be able to identify the customer,
    # so the topic name/header only ever shows a sequential
    # number, never their name, username, or Telegram user id.
    # --------------------------------------------------------

    display_number = get_or_create_display_number(
        customer_id
    )

    topic_name = f"👤 Customer #{display_number}"

    topic_name = topic_name[:128]

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
    # Save permanent mapping
    # --------------------------------------------------------

    save_customer_topic(
        customer_id,
        topic_id,
        display_number
    )

    print(
        f"Created topic {topic_id} "
        f"for customer #{display_number}"
    )

    print(
        f"Saved mapping: "
        f"customer #{display_number} -> topic {topic_id}"
    )

    return topic_id, display_number


# ============================================================
# MEDIA / CONTENT HELPERS
# ============================================================

MEDIA_FIELDS = (
    "photo", "video", "voice", "video_note",
    "audio", "document", "sticker", "animation"
)


def message_has_content(message):
    """True if the message has text OR any supported media type
    (photo, video, voice, video note, audio, document, sticker, GIF)."""

    if (message.get("text") or "").strip():
        return True

    return any(message.get(field) for field in MEDIA_FIELDS)


# ============================================================
# CUSTOMER → SUPPORT GROUP
# ============================================================

def send_customer_message_to_support(
    user,
    message
):

    customer_id = int(
        user["id"]
    )

    topic_id, display_number = create_customer_topic(
        user
    )

    # A short, ANONYMOUS header is posted first — just the sequential
    # display number, never the customer's real name, username, or
    # Telegram user id. This keeps the "Customer #<number>" fallback-
    # recovery pattern usable in extract_customer_id_from_message even
    # if the database mapping is ever lost, without exposing identity
    # to agents. The actual message — text, photo, sticker, video,
    # voice, GIF, whatever it is — is then copied in as-is right after
    # it using copyMessage, which handles every content type without
    # needing separate code per media type, and never carries Telegram's
    # "forwarded from" tag either.

    header = f"🆔 Customer #{display_number}"

    tg(
        "sendMessage",
        {
            "chat_id": SUPPORT_GROUP_ID,
            "message_thread_id": topic_id,
            "text": header
        }
    )

    result = tg(
        "copyMessage",
        {
            "chat_id": SUPPORT_GROUP_ID,
            "message_thread_id": topic_id,
            "from_chat_id": message["chat"]["id"],
            "message_id": message["message_id"]
        }
    )

    support_message_id = result[
        "result"
    ]["message_id"]

    print(
        f"Customer {customer_id} "
        f"message copied to topic {topic_id}"
    )

    print(
        f"Support message ID: "
        f"{support_message_id}"
    )



# ============================================================
# EXTRACT CUSTOMER ID FROM SUPPORT MESSAGE
# ============================================================

def extract_customer_id_from_message(
    message
):

    if not message:

        return None

    text = (
        message.get("text")
        or message.get("caption")
        or ""
    ).strip()

    if not text:

        return None

    # Matches the anonymous "🆔 Customer #<number>" header — never a
    # raw Telegram user id, so agents can't read one out of the chat.
    match = re.search(
        r"Customer\s*#\s*(\d+)",
        text
    )

    if match:

        try:

            display_number = int(
                match.group(1)
            )

        except Exception:

            return None

        return get_customer_id_by_display_number(
            display_number
        )

    return None


# ============================================================
# ADMIN MESSAGE → CUSTOMER
# ============================================================

def send_admin_message_to_customer(
    message
):

    if not message_has_content(message):

        print(
            "Support message has no "
            "text or media"
        )

        return False

    # --------------------------------------------------------
    # Get forum topic ID
    # --------------------------------------------------------

    topic_id = message.get(
        "message_thread_id"
    )

    if not topic_id:

        print(
            "No message_thread_id "
            "in support message"
        )

        return False

    try:

        topic_id = int(
            topic_id
        )

    except Exception:

        print(
            "Invalid topic ID:",
            topic_id
        )

        return False

    print(
        f"Admin message received "
        f"in topic {topic_id}"
    )

    # --------------------------------------------------------
    # METHOD 1:
    # PostgreSQL topic → customer
    # --------------------------------------------------------

    customer_id = get_customer_by_topic(
        topic_id
    )

    if customer_id:

        print(
            f"Customer {customer_id} "
            f"found from database "
            f"for topic {topic_id}"
        )

    # --------------------------------------------------------
    # METHOD 2:
    # If database mapping is missing,
    # check the message being replied to.
    # --------------------------------------------------------

    if not customer_id:

        reply_to = message.get(
            "reply_to_message"
        )

        if reply_to:

            customer_id = (
                extract_customer_id_from_message(
                    reply_to
                )
            )

            if customer_id:

                print(
                    f"Customer {customer_id} "
                    f"found from replied message"
                )

                # Restore mapping
                try:

                    save_customer_topic(
                        customer_id,
                        topic_id,
                        get_or_create_display_number(
                            customer_id
                        )
                    )

                    print(
                        f"Restored mapping: "
                        f"{customer_id} -> {topic_id}"
                    )

                except Exception as e:

                    print(
                        "Could not save "
                        "restored mapping:",
                        repr(e)
                    )

    # --------------------------------------------------------
    # METHOD 3:
    # Check reply_to_message recursively
    # for another customer message.
    # --------------------------------------------------------

    if not customer_id:

        reply_to = message.get(
            "reply_to_message"
        )

        if reply_to:

            nested_reply = reply_to.get(
                "reply_to_message"
            )

            if nested_reply:

                customer_id = (
                    extract_customer_id_from_message(
                        nested_reply
                    )
                )

                if customer_id:

                    print(
                        f"Customer {customer_id} "
                        f"found from nested "
                        f"replied message"
                    )

                    try:

                        save_customer_topic(
                            customer_id,
                            topic_id,
                            get_or_create_display_number(
                                customer_id
                            )
                        )

                    except Exception as e:

                        print(
                            "Could not save "
                            "nested mapping:",
                            repr(e)
                        )

    # --------------------------------------------------------
    # Customer still not found
    # --------------------------------------------------------

    if not customer_id:

        print(
            f"Could not find customer "
            f"for topic {topic_id}"
        )

        print(
            "Admin message ID:",
            message.get("message_id")
        )

        print(
            "Admin user ID:",
            message.get("from", {}).get("id")
        )

        print(
            "Admin username:",
            message.get("from", {}).get("username")
        )

        print(
            "Reply to message:",
            message.get(
                "reply_to_message",
                {}
            ).get("message_id")
        )

        return False

    # --------------------------------------------------------
    # Send message to customer (copyMessage handles text, photos,
    # videos, voice notes, GIFs, stickers, documents — anything —
    # without needing separate code per media type)
    # --------------------------------------------------------

    try:

        tg(
            "copyMessage",
            {
                "chat_id": customer_id,
                "from_chat_id": SUPPORT_GROUP_ID,
                "message_id": message["message_id"]
            }
        )

        print(
            f"Admin message sent to customer "
            f"{customer_id} "
            f"from topic {topic_id}"
        )

        return True

    except Exception as e:

        print(
            "Failed to send admin message:",
            repr(e)
        )

        return False


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

            print(
                "Wrong webhook secret"
            )

            return "forbidden", 403

    update = request.get_json(
        silent=True
    ) or {}

    try:

        # ----------------------------------------------------
        # Get Telegram message
        # ----------------------------------------------------

        message = update.get(
            "message"
        )

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

        chat_id = chat.get(
            "id"
        )

        text = (
            message.get("text")
            or ""
        ).strip()

        # ----------------------------------------------------
        # Ignore real bots, but NOT Telegram's special
        # "GroupAnonymousBot" account — that's what Telegram
        # uses as the sender when an admin posts anonymously
        # ("Remain Anonymous" enabled). Its user id is fixed
        # across every group/channel: 1087968824. Without this
        # exception, anonymous-admin replies get silently
        # dropped before they ever reach the customer-routing
        # logic below.
        # ----------------------------------------------------

        ANONYMOUS_ADMIN_ID = 1087968824

        if user.get("is_bot") and user.get("id") != ANONYMOUS_ADMIN_ID:

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

            if not message_has_content(message):

                return jsonify({
                    "ok": True
                })

            send_customer_message_to_support(
                user,
                message
            )

            return jsonify({
                "ok": True
            })

        # ====================================================
        # SUPPORT GROUP
        # ====================================================

        if int(chat_id) == SUPPORT_GROUP_ID:

            # Ignore commands
            if text.startswith("/"):

                return jsonify({
                    "ok": True
                })

            # Any human admin/staff message
            # in a customer topic
            # goes to that customer.

            handled = (
                send_admin_message_to_customer(
                    message
                )
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
        # OTHER CHATS / GROUPS
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
