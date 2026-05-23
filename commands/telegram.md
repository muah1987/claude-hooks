---
description: Bidirectional Telegram chat — send messages, poll inbox, register webhook, reply to owner
argument-hint: "[send <msg> | inbox | webhook | reply <id> <msg>]"
allowed-tools: Bash, Read
---

# Telegram — Bidirectional Chat Management

Use this skill to manage the Telegram ↔ Claude Code CLI bridge and interact with the bot.

## Variables

TASK: $ARGUMENTS

---

## What this skill does

Depending on the TASK argument, perform one of:

### `/telegram send <message>` or `/telegram say <message>`
Send a message to the owner via Telegram using the `telegram_send` MCP tool.
Format clearly with HTML: `<b>bold</b>`, `<code>code</code>`, `<pre>block</pre>`.

### `/telegram check` or `/telegram inbox`
Poll for new incoming messages using `telegram_get_updates`.
Read each message, respond intelligently:
- Question about the project → answer using project knowledge
- Command (deploy, status, fix X) → execute it
Reply via `telegram_send` with `reply_to_message_id` to thread.

### `/telegram bridge start` or `/telegram bridge restart`
Start or restart the background polling bridge using `telegram_restart_bridge`.
The bridge routes Telegram messages → `claude --print` → Telegram reply.

### `/telegram bridge status`
Check if the bridge daemon is running using `telegram_bridge_status`.
Show PID, recent log lines, session ID.

### `/telegram bridge stop`
Run: `uv run /mnt/d/Projects/alhashimifoundation/.claude/telegram_bridge.py --stop`

### `/telegram status` or `/telegram info`
1. `telegram_get_bot_info` — bot name, username, capabilities
2. `telegram_get_webhook_info` — webhook URL and pending updates
3. `telegram_bridge_status` — is the bridge running?
4. Show configured chat ID and masked token

### `/telegram webhook set` or `/telegram webhook register`
Register the production webhook:
URL: `https://alhashimifoundation.org/api/telegram/webhook`
Use `telegram_register_webhook` with the production URL + TELEGRAM_WEBHOOK_SECRET.

### `/telegram webhook delete`
Delete the webhook (switch to polling) using `telegram_delete_webhook`.

### `/telegram test`
1. Send: "🤖 Claude Code is online — bidirectional bridge active ✅"
2. `telegram_bridge_status` — confirm bridge is up
3. `telegram_get_updates` — show any pending messages

### `/telegram photo <path> [caption]`
Send a screenshot/image file using `telegram_send_photo`.

---

## How the Bridge Works

```
You (Telegram) ──────────► @muah1987_bot ──► telegram_bridge.py
                                                      │
                                            claude -p "<your message>"
                                            --resume <session_id>
                                                      │
You (Telegram) ◄──────── Bot reply ◄────── Claude response
```

- Bridge polls Telegram every ~2 seconds
- Routes messages through `claude --dangerously-skip-permissions --output-format json -p`
- Maintains session continuity with `--resume <session_id>` across messages
- Supports text, images, and documents
- Only responds to chat ID 7436290895 (admin security)
- Auto-started by `SessionStart` hook on every `claude` boot

## Commands in Telegram

Send these directly to @muah1987_bot:
- `/reset` — start a new conversation (clear session)
- `/status` — show bridge PID and session ID
- `/help` — show available commands
- Any other text → sent directly to Claude Code CLI

## Available MCP Tools

- `telegram_send` — send text to owner
- `telegram_get_updates` — poll incoming messages
- `telegram_send_photo` — send local image file
- `telegram_get_bot_info` — bot details
- `telegram_register_webhook` — set webhook URL
- `telegram_delete_webhook` — remove webhook
- `telegram_get_webhook_info` — webhook status
- `telegram_bridge_status` — check bridge daemon
- `telegram_restart_bridge` — start/restart bridge daemon

## Credentials (loaded from .claude/telegram.config)

- Bot: @muah1987_bot (token: 8290296188:AAE5J...)
- Owner chat ID: 7436290895
- Webhook secret: 26e62ca7e17f...
- Config file: `/mnt/d/Projects/alhashimifoundation/.claude/telegram.config`
- Bridge script: `/mnt/d/Projects/alhashimifoundation/.claude/telegram_bridge.py`
- Bridge PID: `/mnt/d/Projects/alhashimifoundation/.claude/telegram_bridge.pid`
- Bridge log: `/mnt/d/Projects/alhashimifoundation/.claude/telegram_bridge.log`
