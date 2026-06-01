import os
import sys
import json
import time
import asyncio
import logging
from datetime import datetime
from pathlib import Path
from functools import wraps

try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from dotenv import load_dotenv
from telethon import TelegramClient, functions, errors, utils
from telethon.tl.types import Chat, Channel
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    Defaults,
    filters,
)
from aiohttp import web

load_dotenv()

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
SESSION_NAME = os.getenv("SESSION_NAME", "userbot")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=getattr(logging, LOG_LEVEL, logging.INFO),
)
logger = logging.getLogger("userbot")

for v, name in [(API_ID, "API_ID"), (API_HASH, "API_HASH"), (BOT_TOKEN, "BOT_TOKEN")]:
    if not v:
        logger.error(f"❌ {name} ضروري. حطه بملف .env")
        sys.exit(1)

if OWNER_ID == 0:
    logger.warning("⚠️ OWNER_ID مو محدد - البوت مفتوح لاي شخص!")

START_TIME = datetime.now()
user_client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

AUTOPUBLISH_FILE = Path("autopublish.json")
AUTOPUBLISH_DEFAULT = {"text": "", "interval": 300, "groups": [], "enabled": False}

user_states = {}
_auto_groups_cache = []
_auto_groups_page = 0


def load_autopublish() -> dict:
    if AUTOPUBLISH_FILE.exists():
        try:
            return json.loads(AUTOPUBLISH_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return dict(AUTOPUBLISH_DEFAULT)


def save_autopublish(cfg: dict):
    AUTOPUBLISH_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


auto_config = load_autopublish()


def fmt_duration(seconds: int) -> str:
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}ي")
    if hours:
        parts.append(f"{hours}س")
    if minutes:
        parts.append(f"{minutes}د")
    parts.append(f"{secs}ث")
    return " ".join(parts)


def btn(text, data):
    return InlineKeyboardButton(text, callback_data=data)


def main_menu_markup():
    return InlineKeyboardMarkup([
        [btn("🧑 معلوماتي", "me"), btn("👥 كروباتي", "groups")],
        [btn("📨 ارسال رسالة", "msg"), btn("🔄 نشر تلقائي", "autopublish")],
        [btn("📝 تعديل بروفايل", "profile"), btn("⚡ سرعة", "ping")],
        [btn("⚙️ أدوات", "tools"), btn("❓ تعليمات", "help")],
    ])


def back_btn():
    return InlineKeyboardMarkup([[btn("🔙 رجوع", "menu_main")]])


def tools_markup():
    return InlineKeyboardMarkup([
        [btn("🔒 بلوك", "block"), btn("🔓 فك بلوك", "unblock")],
        [btn("🗑 حذف رسالة", "del"), btn("🧹 مسح رسائلي", "purge")],
        [btn("ℹ️ آيدي", "id"), btn("👤 معلومات مستخدم", "uinfo")],
        [btn("🚪 مغادرة", "leave"), btn("📋 سجل", "log")],
        [btn("🔙 رجوع", "menu_main")],
    ])


def profile_markup():
    return InlineKeyboardMarkup([
        [btn("📝 تغيير الاسم", "setname")],
        [btn("📝 تغيير البايو", "setbio")],
        [btn("🔙 رجوع", "menu_main")],
    ])


def auto_markup():
    s = "⏹ ايقاف" if auto_config["enabled"] else "▶️ تشغيل"
    start_stop = "auto_stop" if auto_config["enabled"] else "auto_start"
    return InlineKeyboardMarkup([
        [btn("📝 تغيير النص", "auto_settext"), btn("⏱ تغيير المدة", "auto_setinterval")],
        [btn("👥 اختيار الكروبات", "auto_groups"), btn("📊 الحالة", "auto_status")],
        [btn(start_stop, start_stop)],
        [btn("🔙 رجوع", "menu_main")],
    ])


def auto_groups_markup(page=0):
    page_size = 15
    start = page * page_size
    groups_page = _auto_groups_cache[start:start + page_size]
    total_pages = max((len(_auto_groups_cache) + page_size - 1) // page_size, 1)

    keyboard = []
    for gid, gname in groups_page:
        mark = "✅" if gid in auto_config["groups"] else "⬜"
        name = gname[:25]
        keyboard.append([btn(f"{mark} {name}", f"ag_t|{gid}")])

    nav = []
    if page > 0:
        nav.append(btn("⬅️", f"ag_p|{page - 1}"))
    nav.append(btn(f"{page + 1}/{total_pages}", "noop"))
    if page < total_pages - 1:
        nav.append(btn("➡️", f"ag_p|{page + 1}"))
    if nav:
        keyboard.append(nav)

    keyboard.append([btn("✅ تم", "ag_done"), btn("🔙 رجوع", "autopublish")])
    return InlineKeyboardMarkup(keyboard)


async def edit_or_send(update, text, markup=None, edit=True):
    if update.callback_query and edit:
        try:
            if markup:
                return await update.callback_query.edit_message_text(text, reply_markup=markup)
            return await update.callback_query.edit_message_text(text)
        except Exception:
            pass
    if markup:
        return await update.effective_message.reply_text(text, reply_markup=markup)
    return await update.effective_message.reply_text(text)


async def show_main(update):
    await edit_or_send(update,
        "── ─ ── ─ ──\n\n"
        "**🤖 القائمة الرئيسية**\n"
        "اختر من الأزرار أدناه 👇",
        main_menu_markup())


async def auto_sender(application):
    last_send = 0.0
    while True:
        await asyncio.sleep(1)
        try:
            if not (auto_config["enabled"] and auto_config["text"] and auto_config["groups"]):
                continue
            elapsed = time.time() - last_send
            if elapsed < max(auto_config["interval"], 10):
                continue
            for chat_id in auto_config["groups"]:
                try:
                    await user_client.send_message(chat_id, auto_config["text"])
                    await asyncio.sleep(2)
                except Exception:
                    pass
            last_send = time.time()
        except Exception:
            pass


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if OWNER_ID and update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ ما عندك صلاحية")
        return
    await show_main(update)


async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "menu_main":
        await show_main(update)

    elif data == "me":
        try:
            me = await user_client.get_me()
            full = await user_client(functions.users.GetFullUserRequest(me.id))
            bio = full.full_user.about or "بدون بايو"
            await edit_or_send(update,
                f"**{utils.get_display_name(me)}**\n"
                f"@{me.username or '—'}\n\n"
                f"الآيدي : {me.id}\n"
                f"الرقم : {me.phone or '—'}\n"
                f"البايو : {bio}\n"
                f"موثوق : {'✅' if me.verified else '❌'}",
                back_btn())
        except Exception as e:
            await edit_or_send(update, f"خطأ : {e}", back_btn())

    elif data == "groups":
        try:
            await q.edit_message_text("⏳ جاري التحميل ...")
            lines = []
            async for d in user_client.iter_dialogs(limit=200):
                if not d.is_group:
                    continue
                lines.append(f"`{d.name}`\n`{d.id}`")
            text = "── ─ ── ─ ──\n\n**👥 كروباتك**\n\n" + "\n\n".join(lines) if lines else "ماعندك مجموعات"
            await q.edit_message_text(text[:4000], reply_markup=back_btn())
        except Exception as e:
            await q.edit_message_text(f"خطأ : {e}", reply_markup=back_btn())

    elif data == "ping":
        start = datetime.now()
        m = await q.edit_message_text("🏓 جاري الفحص ...")
        ms = (datetime.now() - start).microseconds // 1000
        await m.edit_text(f"🏓 **{ms} ms**", reply_markup=back_btn())

    elif data == "help":
        await edit_or_send(update,
            "── ─ ── ─ ──\n\n"
            "**🤖 الأوامر المتاحة**\n\n"
            "**من القائمة:**\n"
            "🧑 معلوماتي - معلومات حسابك\n"
            "👥 كروباتي - قائمة كروباتك\n"
            "📨 ارسال - ارسال رسالة\n"
            "🔄 نشر تلقائي - نشر دوري\n"
            "📝 بروفايل - تعديل الاسم والبايو\n"
            "⚡ سرعة - فحص الاستجابة\n"
            "⚙️ أدوات - ادوات اضافية\n\n"
            "**كتابة مباشرة (اختياري):**\n"
            "/me, /groups, /msg, /block, /purge ...",
            main_menu_markup())

    elif data == "tools":
        await edit_or_send(update, "── ─ ── ─ ──\n\n**⚙️ أدوات**", tools_markup())

    elif data == "profile":
        await edit_or_send(update, "── ─ ── ─ ──\n\n**📝 تعديل البروفايل**", profile_markup())

    # Profile
    elif data == "setname":
        user_states[update.effective_user.id] = {"action": "setname"}
        await edit_or_send(update, "ارسـل الاسم الجديد 👇", back_btn())

    elif data == "setbio":
        user_states[update.effective_user.id] = {"action": "setbio"}
        await edit_or_send(update, "ارسـل البايو الجديد 👇", back_btn())

    # Msg
    elif data == "msg":
        user_states[update.effective_user.id] = {"action": "msg_target"}
        await edit_or_send(update,
            "ارسـل اليوزر او الآيدي 👇\n"
            "مثال : @username او 123456789",
            back_btn())

    # Tools
    elif data == "block":
        user_states[update.effective_user.id] = {"action": "block"}
        await edit_or_send(update, "ارسـل آيدي او يوزر الشخص 👇", back_btn())

    elif data == "unblock":
        user_states[update.effective_user.id] = {"action": "unblock"}
        await edit_or_send(update, "ارسـل آيدي او يوزر الشخص 👇", back_btn())

    elif data == "del":
        user_states[update.effective_user.id] = {"action": "del_chat"}
        await edit_or_send(update,
            "ارسـل آيدي المحادثة 👇\n"
            "وراح احذف اخر رسالة الك فيها",
            back_btn())

    elif data == "purge":
        user_states[update.effective_user.id] = {"action": "purge_chat"}
        await edit_or_send(update,
            "ارسـل آيدي المحادثة 👇\n"
            "وراح امسح كل رسائلك فيها",
            back_btn())

    elif data == "id":
        user_states[update.effective_user.id] = {"action": "id"}
        await edit_or_send(update, "ارسـل يوزر او آيدي 👇", back_btn())

    elif data == "uinfo":
        user_states[update.effective_user.id] = {"action": "uinfo"}
        await edit_or_send(update, "ارسـل يوزر او آيدي المستخدم 👇", back_btn())

    elif data == "leave":
        user_states[update.effective_user.id] = {"action": "leave"}
        await edit_or_send(update, "ارسـل آيدي المحادثة الي تريد تغادرها 👇", back_btn())

    elif data == "log":
        user_states[update.effective_user.id] = {"action": "log"}
        await edit_or_send(update, "ارسـل آيدي المحادثة 👇", back_btn())

    # Autopublish
    elif data == "autopublish":
        await auto_show_menu(update)

    elif data == "auto_status":
        status = "🟢 شغال" if auto_config["enabled"] else "🔴 موقف"
        text = auto_config["text"][:50] + "..." if auto_config["text"] else "ماكو"
        interval = auto_config["interval"]
        groups = len(auto_config["groups"])
        await edit_or_send(update,
            f"── ─ ── ─ ──\n\n"
            f"**🔄 النشر التلقائي**\n\n"
            f"الحالة : {status}\n"
            f"الرسالة : {text}\n"
            f"المدة : كل {interval} ثانية\n"
            f"الكروبات : {groups}",
            auto_markup())

    elif data == "auto_settext":
        user_states[update.effective_user.id] = {"action": "auto_text"}
        await edit_or_send(update, "ارسـل النص الجديد للنشر التلقائي 👇", auto_markup())

    elif data == "auto_setinterval":
        user_states[update.effective_user.id] = {"action": "auto_interval"}
        await edit_or_send(update, "ارسـل المدة بالثواني 👇 (اقل شي 10)", auto_markup())

    elif data == "auto_groups":
        _auto_groups_cache.clear()
        await do_auto_show_groups(update)

    elif data == "ag_done":
        await auto_show_menu(update)

    elif data.startswith("ag_t|"):
        try:
            gid = int(data.split("|", 1)[1])
            if gid in auto_config["groups"]:
                auto_config["groups"] = [g for g in auto_config["groups"] if g != gid]
            else:
                auto_config["groups"].append(gid)
            save_autopublish(auto_config)
            total = len(_auto_groups_cache)
            selected = len(auto_config["groups"])
            await q.edit_message_text(
                f"── ─ ── ─ ──\n\n**اختيار الكروبات**\n\nالمختار : {selected} / {total}\nاضغط على الكروب لاختياره",
                reply_markup=auto_groups_markup(_auto_groups_page))
        except Exception as e:
            await q.edit_message_text(f"خطأ : {e}", reply_markup=back_btn())

    elif data.startswith("ag_p|"):
        try:
            page = int(data.split("|", 1)[1])
            await do_auto_show_groups(update, page)
        except Exception as e:
            await q.edit_message_text(f"خطأ : {e}", reply_markup=back_btn())

    elif data == "noop":
        pass

    elif data == "auto_start":
        if not auto_config["text"] or not auto_config["groups"]:
            await edit_or_send(update, "تأكد من وجود رسالة وكروبات مختارة", auto_markup())
            return
        auto_config["enabled"] = True
        save_autopublish(auto_config)
        await edit_or_send(update, "✅ تم تشغيل النشر التلقائي", auto_markup())

    elif data == "auto_stop":
        auto_config["enabled"] = False
        save_autopublish(auto_config)
        await edit_or_send(update, "✅ تم ايقاف النشر التلقائي", auto_markup())


async def auto_show_menu(update):
    status = "🟢 شغال" if auto_config["enabled"] else "🔴 موقف"
    text = auto_config["text"][:50] + "..." if auto_config["text"] else "ماكو"
    interval = auto_config["interval"]
    groups = len(auto_config["groups"])
    await edit_or_send(update,
        f"── ─ ── ─ ──\n\n"
        f"**🔄 النشر التلقائي**\n\n"
        f"الحالة : {status}\n"
        f"الرسالة : {text}\n"
        f"المدة : كل {interval} ثانية\n"
        f"الكروبات : {groups}",
        auto_markup())


async def do_auto_show_groups(update, page=0):
    global _auto_groups_cache, _auto_groups_page
    try:
        if page == 0 or not _auto_groups_cache:
            _auto_groups_cache = []
            async for d in user_client.iter_dialogs(limit=200):
                if d.is_group:
                    _auto_groups_cache.append((d.id, d.name or "بدون اسم"))
        _auto_groups_page = page
        total = len(_auto_groups_cache)
        if total == 0:
            await edit_or_send(update, "ماعندك مجموعات", auto_markup())
            return
        selected = len(auto_config["groups"])
        text = f"── ─ ── ─ ──\n\n**اختيار الكروبات**\n\nالمختار : {selected} / {total}\nاضغط على الكروب لاختياره"
        if update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=auto_groups_markup(page))
        else:
            await update.effective_message.reply_text(text, reply_markup=auto_groups_markup(page))
    except Exception as e:
        await edit_or_send(update, f"خطأ : {e}", auto_markup())


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in user_states:
        return
    if OWNER_ID and uid != OWNER_ID:
        return

    action = user_states[uid].get("action", "")
    text = update.message.text.strip()

    if action == "setname":
        try:
            await user_client(functions.account.UpdateProfileRequest(first_name=text, last_name=""))
            await update.message.reply_text("✅ تم تغيير الاسم")
        except Exception as e:
            await update.message.reply_text(f"خطأ : {e}")

    elif action == "setbio":
        try:
            await user_client(functions.account.UpdateProfileRequest(about=text))
            await update.message.reply_text("✅ تم تغيير البايو")
        except Exception as e:
            await update.message.reply_text(f"خطأ : {e}")

    elif action == "msg_target":
        user_states[uid] = {"action": "msg_text", "target": text}
        await update.message.reply_text("ارسـل النص 👇")

    elif action == "msg_text":
        target = user_states[uid].get("target", "")
        try:
            await user_client.send_message(target, text)
            await update.message.reply_text("✅ تم الارسال")
        except Exception as e:
            await update.message.reply_text(f"خطأ : {e}")

    elif action == "block":
        try:
            await user_client(functions.contacts.BlockRequest(text))
            await update.message.reply_text("✅ تم البلوك")
        except Exception as e:
            await update.message.reply_text(f"خطأ : {e}")

    elif action == "unblock":
        try:
            await user_client(functions.contacts.UnblockRequest(text))
            await update.message.reply_text("✅ تم رفع البلوك")
        except Exception as e:
            await update.message.reply_text(f"خطأ : {e}")

    elif action == "del_chat":
        user_states[uid] = {"action": "del_msg", "chat": text}
        await update.message.reply_text("ارسـل رقم الرسالة 👇\n(Message ID)")

    elif action == "del_msg":
        chat = user_states[uid].get("chat", "")
        try:
            msg_id = int(text)
            entity = await user_client.get_entity(chat)
            await user_client.delete_messages(entity, [msg_id])
            await update.message.reply_text("✅ تم الحذف")
        except Exception as e:
            await update.message.reply_text(f"خطأ : {e}")

    elif action == "purge_chat":
        try:
            entity = await user_client.get_entity(text)
            ids = [m.id async for m in user_client.iter_messages(entity, from_user="me")]
            if ids:
                await user_client.delete_messages(entity, ids)
                await update.message.reply_text(f"✅ تم مسح {len(ids)} رسالة")
            else:
                await update.message.reply_text("ماكو رسائل تمسحها")
        except Exception as e:
            await update.message.reply_text(f"خطأ : {e}")

    elif action == "id":
        try:
            entity = await user_client.get_entity(text)
            await update.message.reply_text(f"`{text}`\nالآيدي : `{entity.id}`")
        except Exception as e:
            await update.message.reply_text(f"خطأ : {e}")

    elif action == "uinfo":
        try:
            user = await user_client.get_entity(text)
            full = await user_client(functions.users.GetFullUserRequest(user.id))
            await update.message.reply_text(
                f"**{utils.get_display_name(user)}**\n"
                f"@{user.username or '—'}\n\n"
                f"الآيدي : {user.id}\n"
                f"البايو : {full.full_user.about or 'بدون بايو'}\n"
                f"بوت : {'✅' if user.bot else '❌'}")
        except Exception as e:
            await update.message.reply_text(f"خطأ : {e}")

    elif action == "leave":
        try:
            await user_client(functions.channels.LeaveChannelRequest(int(text) if text.isdigit() else text))
            await update.message.reply_text("✅ تم المغادرة")
        except Exception as e:
            await update.message.reply_text(f"خطأ : {e}")

    elif action == "log":
        try:
            entity = await user_client.get_entity(text)
            msgs = []
            async for m in user_client.iter_messages(entity, limit=10, from_user="me"):
                txt = (m.raw_text or "[ميديا]")[:50]
                msgs.append(f"`{m.date.strftime('%H:%M')}` {txt}")
            reply = "── ─ ── ─ ──\n\nآخر 10 رسائلك\n\n" + "\n".join(reversed(msgs)) if msgs else "ماكو رسائل"
            await update.message.reply_text(reply[:4000])
        except Exception as e:
            await update.message.reply_text(f"خطأ : {e}")

    elif action == "auto_text":
        auto_config["text"] = text
        save_autopublish(auto_config)
        await update.message.reply_text("✅ تم حفظ النص")

    elif action == "auto_interval":
        try:
            interval = max(int(text), 10)
            auto_config["interval"] = interval
            save_autopublish(auto_config)
            await update.message.reply_text(f"✅ تم ضبط المدة : كل {interval} ثانية")
        except ValueError:
            await update.message.reply_text("لازم رقم صحيح")

    user_states.pop(uid, None)


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in user_states:
        user_states.pop(uid)
        await update.message.reply_text("✅ تم الالغاء")
    else:
        await update.message.reply_text("ماكو عملية لتلغيها")


async def post_init(application):
    logger.info("🚀 جاري الاتصال بحساب تيليكرام...")
    await user_client.start()
    me = await user_client.get_me()
    logger.info(f"✅ تم تسجيل الدخول: {utils.get_display_name(me)} (@{me.username or '—'})")
    bot_info = await application.bot.get_me()
    logger.info(f"🤖 البوت يعمل: @{bot_info.username}")

    asyncio.create_task(auto_sender(application))
    logger.info("🔄 تم تشغيل مهمة النشر التلقائي")

    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 7860)
    await site.start()
    logger.info("🌐 Health server on :7860")


async def health(request):
    return web.Response(text="OK")


def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .defaults(Defaults(parse_mode=ParseMode.MARKDOWN))
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CallbackQueryHandler(menu_handler))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("📡 بدء استقبال الأوامر...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
