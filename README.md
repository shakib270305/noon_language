# Noon Assistant — Language Detector

Telegram group bot that:
- ignores English messages
- detects non-English messages with Gemini
- replies in the same language: "Please send messages in English."
- ignores commands and bot messages
- ignores group admins/owner
- works through Telegram webhook
- is designed for Render Free Web Service

## Render settings

Build Command:
pip install -r requirements.txt

Start Command:
gunicorn app:app

Environment variables:
BOT_TOKEN=your Telegram BotFather token
GEMINI_API_KEY=your Google AI Studio API key
WEBHOOK_SECRET=make-a-random-secret

After deployment, your URL will look like:
https://YOUR-SERVICE-NAME.onrender.com

Set Telegram webhook:
https://api.telegram.org/botYOUR_BOT_TOKEN/setWebhook?url=https://YOUR-SERVICE-NAME.onrender.com/webhook&secret_token=YOUR_WEBHOOK_SECRET

Do NOT publish BOT_TOKEN or GEMINI_API_KEY in GitHub.
