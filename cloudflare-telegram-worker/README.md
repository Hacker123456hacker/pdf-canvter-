# Telegram Webhook Controller (Cloudflare Worker)

This replaces the GitHub Actions 5-minute polling loop with Telegram webhooks. Telegram delivers each update directly to the Worker; command replies should normally arrive within seconds. Video generation still runs in GitHub Actions.

## 1. Deploy the Worker

Create a Cloudflare Worker named `bhakti-telegram-control` and deploy `worker.js` as its entry point. Enable Workers Logs.

## 2. Add Worker secrets

In Worker → Settings → Variables and Secrets, add these as **Secrets**, not plain variables:

- `TELEGRAM_BOT_TOKEN`: same bot token currently stored in GitHub Actions.
- `TELEGRAM_CHAT_ID`: same allowed Telegram chat ID.
- `GITHUB_TOKEN`: a fine-grained GitHub Personal Access Token restricted to this repository, with **Actions: Read and write** permission. It is needed for workflow status/dispatch/enable/disable.
- `WEBHOOK_SECRET`: a newly generated random string, 32–64 characters, using only A–Z, a–z, 0–9, underscore or hyphen.

Never commit these values or paste them into chat.

## 3. Register Telegram webhook

After deploying, copy the Worker URL, for example `https://bhakti-telegram-control.<your-subdomain>.workers.dev`.

Run this locally in a private terminal after replacing the placeholders (do not share the command or its output because it contains the bot token):

```bash
curl -sS -X POST "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook" \
  -d "url=https://bhakti-telegram-control.<your-subdomain>.workers.dev" \
  -d "secret_token=<WEBHOOK_SECRET>" \
  -d 'allowed_updates=["message"]'
```

Telegram's `secret_token` must exactly match the Worker secret `WEBHOOK_SECRET`.

Verify without exposing the bot token: call `getWebhookInfo` from your private terminal and confirm the URL is the Worker URL and `last_error_message` is empty.

## 4. Retire polling only after webhook test

First test `/help`, `/status`, `/lastvideo`, and `/run` (only if you intend to start a video). Once webhook commands work, disable the old `Telegram Bot Controller` scheduled workflow or remove its schedule to prevent competing `getUpdates` polling. Keep the video workflow schedule unchanged.

## Security notes

- The Worker rejects Telegram updates unless the Telegram webhook secret header matches.
- It accepts commands only from the configured chat ID.
- GitHub token is scoped to this repository and Actions permissions only.
- Do not expose the Worker secrets or webhook URL registration command.
