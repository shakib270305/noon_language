# Noon Customer Support Bot

This version combines both features:

1. **Customer support inbox**
   - Customer sends a private message to the bot.
   - The bot creates one Forum Topic for that customer.
   - Later messages from that customer go to the same topic.
   - Two configured admins can reply from the topic.
   - Admin replies are sent to the customer's private chat.

2. **English-only warning in the support group**
   - Non-admin users who send supported non-English text in the group receive a warning in their detected language.
   - English messages receive no warning.
   - Admins/owner are ignored.

Gemini is NOT used by this version.

## Render environment variables

Required:

- `BOT_TOKEN` — Telegram BotFather token.
- `ADMIN_CHAT_IDS` — numeric Telegram user IDs of your admins, comma-separated.
- `SUPPORT_GROUP_ID` — numeric ID of your Forum Group, normally starting with `-100`.
- `WEBHOOK_SECRET` — any random secret string. Use the exact same value when configuring Telegram's webhook `secret_token`.

Optional:

- `DB_PATH` — defaults to `customer_topics.db`.

`GEMINI_API_KEY` is not required.

## Telegram setup

1. Use/create a Telegram group.
2. Turn on Topics/Forum.
3. Add your bot to the group.
4. Make the bot an administrator.
5. Give the bot permission to manage topics and send messages.
6. Add both admins to the group.
7. Set `SUPPORT_GROUP_ID` to the numeric group ID.

`@RawDataBot` is not required for the bot logic. It may be used as a helper to inspect Telegram update data if you need to discover an ID.

## How support works

Example:

Customer `Rahim` sends:

    Hello, I need help.

The bot creates:

    Rahim | 123456789

and puts the customer message in that topic.

If Rahim sends another message later, it goes to the same topic.

Admin replies in that topic:

    Sure, how can I help you?

The bot sends that reply to Rahim's private chat.

## Important

The bot should be configured with the Forum Group's numeric chat ID, not its @username.

The SQLite database stores the mapping between customer user IDs and topic IDs. Render's local filesystem should not be treated as permanent storage across every restart/redeploy. For production durability, use a persistent disk or managed database.

## Webhook

After deployment, use:

    https://YOUR-SERVICE.onrender.com/webhook

If `WEBHOOK_SECRET` is configured, Telegram's webhook should be configured with the same value as `secret_token`.
