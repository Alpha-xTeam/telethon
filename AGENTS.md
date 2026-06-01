# Bot Development Guide

## Project Structure
- `/telethon-bot/` — Telegram userbot with Supabase (Telethon)
- `/youtube-bot/` — Media downloader bot (python-telegram-bot)
- New bots go in their own subfolder at this level

## Identity
- Developer: @hsabadi
- Channel: @xtraforbots
- All bots must display this info in the welcome/start message

## Platform
- Bots deploy on Hugging Face Spaces (Docker SDK)
- HF Spaces BLOCKS `api.telegram.org` (HTTPS) — bots using PTB (HTTP) will NOT work
- Workaround: use Telethon (MTProto, connects to 149.154.167.51) instead of python-telegram-bot
- If you don't use HF Spaces, either library is fine

## Python Version
- Python 3.11+ (use 3.11-slim in Docker for consistency)

## Database
- Supabase project `azhrxvngrovywstizads` (ap-northeast-1) — **خاص بـ `telethon-bot/` فقط**
- بقية البوتات تخزن بالطريقة اللي تناسبها (ملفات، قاعدة بيانات أخرى، أو بدون تخزين)
- جداول `telethon-bot` في Supabase: `sessions`, `bot_config`, `user_prefs`
- Service role key في environment variables

## Naming Convention
- Each bot in its own subfolder: `{bot-name}/`
- `bot.py` is the main entry point
- `.env` for secrets (gitignored)
- `requirements.txt` for dependencies
- `Dockerfile` for HF Spaces deployment (ffmpeg included if needed)
- `README.md` with HF Space metadata (YAML frontmatter)

## Code Style
- No comments in code
- Arabic strings for user-facing messages
- Async/await throughout
- Inline keyboards with `Button.inline()` (Telethon) or `InlineKeyboardButton` (PTB)
- Persistent data in Supabase OR files — depending on the bot's needs
- `.gitignore` must exclude `.env`, session files (`*.session`), and any credentials

## Deployment
- HF Space name format: `hsoneabadi/{bot-name}`
- Secrets depend on the bot (BOT_TOKEN always needed, API_ID/API_HASH if Telethon, etc.)
- Environment variables via `.env` locally, HF Secrets in production
