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
- All bots deploy on Hugging Face Spaces (Docker SDK)
- HF Spaces BLOCKS `api.telegram.org` (HTTPS) — bots using MTProto (Telethon) work, bots using HTTP (PTB) do NOT
- For bots that need to bypass: use Telethon (MTProto, connects to 149.154.167.51)

## Python Version
- Python 3.11+ (use 3.11-slim in Docker for consistency)

## Database
- Supabase project `azhrxvngrovywstizads` (ap-northeast-1) is available
- Tables: `sessions` (user auth), `bot_config` (global settings), `user_prefs` (per-user prefs)
- Service role key is in environment

## Naming Convention
- Each bot in a numbered subfolder: `NN-name/`
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
- All persistent data in Supabase, NOT in files

## Deployment
- HF Space name format: `hsoneabadi/{bot-name}`
- Secrets: BOT_TOKEN, API_ID, API_HASH, SUPABASE_URL, SUPABASE_SERVICE_KEY
- Environment variables via `.env` locally, HF Secrets in production
