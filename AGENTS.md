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

## Developer Control Panel Guidelines
- The Developer Control Panel for all current and future bots must include:
  1. Complete bot statistics.
  2. A JSON file (`stats.json`) to store user info, bot info, and force subscription channels.
  3. Force subscription channels management (adding/deleting individually).
  4. Enable or disable the bot.
  5. Enable or disable bot notifications.
  6. Enable or disable forwarding user messages to the developer.
  7. Bot uptime/running time tracker.
  8. Changing the `/start` welcome message.
  9. Promoting a secondary admin for the bot.
- Any persistent configuration must be saved in `stats.json`.

## AI Development Rules & Safeguards (قواعد التطوير الذكي والحماية)

يجب على الذكاء الاصطناعي الالتزام بالضوابط والتدابير البرمجية التالية في كافة البوتات الحالية والجديدة:

### 1. التحقق الشامل من الاشتراك الإجباري (Force Subscription Safeguards)
- لا تكتفِ بالتحقق من الاشتراك الإجباري عند أمر `/start` فقط.
- **إلزامي**: يجب التحقق من الاشتراك عند بدء أي لعبة أو خدمة في المجموعات (مثل كتابة كلمة `روليت` أو `/xo`).
- **إلزامي**: يجب التحقق من الاشتراك عند ضغط أي عضو على أزرار التفاعل والإنلاين (مثل أزرار الانضمام `join_game` أو `xo_join`)، وعرض تنبيه Alert منبثق في حال عدم الاشتراك يبلغه باسم القناة.

### 2. البرمجة الدفاعية وتفادي تجميد الأزرار (Defensive Coded Callbacks)
- تجنب تماماً استدعاء الفهرس المباشر للمصفوفات القابلة للتفريغ (مثل `channels[0]`) دون فحص طول المصفوفة أولاً.
- استدعاء فهرس مصفوفة فارغة يتسبب في خطأ صامت (`IndexError`) يؤدي لتجميد الأزرار وظهور عقرب التحميل الدائري للأبد.
- استخدم دائماً قيم استرداد افتراضية آمنة (مثال: `ch = channels[0] if channels else "@xtraforbots"`).

### 3. الحماية من حلقات التكرار والتحويل اللانهائي (Loop Prevention)
- عند تفعيل ميزة تحويل رسائل المستخدمين للمطور (Forward Messages)، يجب قصر الاستماع على الرسائل الواردة فقط (`incoming=True`).
- يجب دائماً تجاهل الرسائل الصادرة من البوت نفسه أو أي بوت آخر (`if sender and sender.bot: return`) لمنع حدوث حلقة تكرار برمجية لانهائية تستهلك موارد الخادم.

### 4. التنسيق الفخم والمعلمة الذكية `/start about` (Deep-Linking Bypass)
- يجب دعم المعلمة `/start about` في جميع البوتات لتعرض تفاصيل البوت تلقائياً ومباشرة.
- يجب أن تتخطى هذه المعلمة `/start about` أي قيود مثل الحظر، الصيانة، أو الاشتراك الإجباري لتوفر وصولاً سلساً للمستخدم الجديد.
- يجب استخدام التنسيق الكلاسيكي الفخم الخالي من الإيموجيات الملونة والاعتماد على الرموز الراقية فقط (`✦`, `▪`, `•`, `«`, `»`).

