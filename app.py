import os
import json
import requests

from flask import Flask, request, jsonify
from langdetect import detect, DetectorFactory, LangDetectException


# ============================================================
# BASIC SETTINGS
# ============================================================

DetectorFactory.seed = 0

app = Flask(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

# SECRET SUPPORT GROUP
SUPPORT_GROUP_ID = int(
    os.environ["SUPPORT_GROUP_ID"]
)

# FIRST GROUP
LANGUAGE_GROUP_ID = os.environ.get(
    "LANGUAGE_GROUP_ID", ""
).strip()

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"


# ============================================================
# DATABASE
# ============================================================

DATA_FILE = "customer_topics.json"

customer_topics = {}
support_messages = {}


def load_database():

    global customer_topics
    global support_messages

    try:

        with open(
            DATA_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

            # New format
            if isinstance(data, dict) and (
                "customer_topics" in data
                or "support_messages" in data
            ):

                customer_topics = data.get(
                    "customer_topics",
                    {}
                )

                support_messages = data.get(
                    "support_messages",
                    {}
                )

            # Old format
            else:

                customer_topics = data
                support_messages = {}

    except Exception:

        customer_topics = {}
        support_messages = {}


load_database()


def save_database():

    try:

        with open(
            DATA_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                {
                    "customer_topics": customer_topics,
                    "support_messages": support_messages
                },
                f,
                ensure_ascii=False,
                indent=2
            )

    except Exception as e:

        print(
            "DATABASE SAVE ERROR:",
            repr(e)
        )


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
# LANGUAGE WARNING
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
        "ദയവായി സന്ദേശങ്ങൾ ഇംഗ്ലീഷിൽ അയയ്ക്കുക.",

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
# CREATE CUSTOMER TOPIC
# ============================================================

def create_customer_topic(user):

    user_id = str(user["id"])

    # Existing topic
    if user_id in customer_topics:

        return int(
            customer_topics[user_id]
        )

    first_name = (
        user.get("first_name")
        or "Customer"
    )

    username = user.get("username")

    if username:

        topic_name = (
            f"👤 {first_name} "
            f"(@{username}) - {user_id}"
        )

    else:

        topic_name = (
            f"👤 {first_name} - {user_id}"
        )

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

    customer_topics[user_id] = topic_id

    save_database()

    print(
        f"Created topic {topic_id} "
        f"for customer {user_id}"
    )

    return topic_id


# ============================================================
# SEND CUSTOMER MESSAGE TO SUPPORT
# ============================================================

def send_customer_message_to_support(
    user,
    text
):

    user_id = str(user["id"])

    topic_id = create_customer_topic(
        user
    )

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
        f"🆔 User ID: {user['id']}\n\n"
        f"{text}"
    )

    result = tg(
        "sendMessage",
        {
            "chat_id": SUPPORT_GROUP_ID,
            "message_thread_id": topic_id,
            "text": support_message
        }
    )

    support_message_id = result[
        "result"
    ]["message_id"]

    # --------------------------------------------------------
    # VERY IMPORTANT
    # Save support message ID -> customer ID
    # --------------------------------------------------------

    support_messages[
        str(support_message_id)
    ] = user_id

    save_database()

    print(
        f"Customer {user_id} -> "
        f"topic {topic_id} -> "
        f"support message {support_message_id}"
    )


# ============================================================
# FIND CUSTOMER BY TOPIC
# ============================================================

def find_customer_by_topic(topic_id):

    if not topic_id:
        return None

    try:

        topic_id = int(topic_id)

    except Exception:

        return None

    for user_id, saved_topic_id in customer_topics.items():

        try:

            if int(saved_topic_id) == topic_id:

                return int(user_id)

        except Exception:

            continue

    return None


# ============================================================
# FIND CUSTOMER BY SUPPORT MESSAGE
# ============================================================

def find_customer_by_support_message(
    message_id
):

    if not message_id:
        return None

    user_id = support_messages.get(
        str(message_id)
    )

    if not user_id:
        return None

    try:

        return int(user_id)

    except Exception:

        return None


# ============================================================
# FIND CUSTOMER FROM ADMIN MESSAGE
# ============================================================

def find_customer_from_admin_message(
    message
):

    # --------------------------------------------------------
    # METHOD 1
    # Topic ID
    # --------------------------------------------------------

    topic_id = message.get(
        "message_thread_id"
    )

    customer_id = find_customer_by_topic(
        topic_id
    )

    if customer_id:

        return customer_id


    # --------------------------------------------------------
    # METHOD 2
    # Reply-to message
    # --------------------------------------------------------

    replied_message = message.get(
        "reply_to_message"
    )

    if replied_message:

        replied_message_id = replied_message.get(
            "message_id"
        )

        customer_id = (
            find_customer_by_support_message(
                replied_message_id
            )
        )

        if customer_id:

            return customer_id


        # ----------------------------------------------------
        # Sometimes Telegram puts thread ID
        # inside replied message
        # ----------------------------------------------------

        replied_thread_id = (
            replied_message.get(
                "message_thread_id"
            )
        )

        customer_id = find_customer_by_topic(
            replied_thread_id
        )

        if customer_id:

            return customer_id


    return None


# ============================================================
# SEND ADMIN REPLY TO CUSTOMER
# ============================================================

def send_admin_reply_to_customer(
    message
):

    text = (
        message.get("text")
        or ""
    ).strip()

    if not text:

        print(
            "Admin message has no text"
        )

        return False


    customer_id = (
        find_customer_from_admin_message(
            message
        )
    )


    if not customer_id:

        print(
            "Could not find customer for "
            f"support message "
            f"{message.get('message_id')}"
        )

        print(
            "message_thread_id =",
            message.get(
                "message_thread_id"
            )
        )

        replied = message.get(
            "reply_to_message"
        )

        if replied:

            print(
                "reply_to_message_id =",
                replied.get(
                    "message_id"
                )
            )

        return False


    # --------------------------------------------------------
    # SEND TO CUSTOMER
    # --------------------------------------------------------

    result = tg(
        "sendMessage",
        {
            "chat_id": customer_id,
            "text": text
        }
    )


    print(
        f"Admin reply sent to customer "
        f"{customer_id}"
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

            print(
                "Wrong webhook secret"
            )

            return "forbidden", 403


    update = request.get_json(
        silent=True
    ) or {}


    try:

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
        # IGNORE BOT MESSAGES
        # ----------------------------------------------------

        if user.get("is_bot"):

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

            # Ignore commands
            if text.startswith("/"):

                return jsonify({
                    "ok": True
                })


            # Try to send admin message
            # to the correct customer

            handled = (
                send_admin_reply_to_customer(
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
