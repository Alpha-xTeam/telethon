import os, sys, json, time, asyncio, logging, math, random
from datetime import datetime
from pathlib import Path

try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from dotenv import load_dotenv
from telethon import TelegramClient, events, functions, errors, utils, Button
from telethon.sessions import StringSession
from aiohttp import web, ClientSession

load_dotenv()

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
SESSION_STRING = os.getenv("SESSION_STRING", "")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=getattr(logging, LOG_LEVEL, logging.INFO))
logger = logging.getLogger("userbot")

for v, name in [(API_ID, "API_ID"), (API_HASH, "API_HASH"), (BOT_TOKEN, "BOT_TOKEN"), (SUPABASE_URL, "SUPABASE_URL"), (SUPABASE_KEY, "SUPABASE_KEY")]:
    if not v:
        logger.error(f"❌ {name} ضروري")
        sys.exit(1)

START_TIME = datetime.now()
bot_client = TelegramClient(StringSession(), API_ID, API_HASH)

SUPA_HEADERS = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json", "Prefer": "return=representation"}

_owner_client = None
user_states = {}
user_clients = {}
_supa_session = None
_auto_groups_data = {}
_auto_last_send = {}


async def supa_req(method, path, data=None, params=None):
    global _supa_session
    if not _supa_session:
        _supa_session = ClientSession()
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    async with _supa_session.request(method, url, json=data, params=params, headers=SUPA_HEADERS) as r:
        if r.status < 300:
            if r.content_type == "application/json":
                return await r.json()
            return True
        t = await r.text()
        logger.error(f"Supabase {method} {path}: {r.status} {t}")
        return None


async def supa_select(table, match=None):
    params = None
    if match:
        k, v = list(match.items())[0]
        params = {f"{k}": f"eq.{v}"}
    return await supa_req("GET", table, params=params)


async def supa_upsert(table, data):
    return await supa_req("POST", table, data=data)


async def supa_update(table, data, match):
    k, v = list(match.items())[0]
    path = f"{table}?{k}=eq.{v}"
    return await supa_req("PATCH", path, data=data)


async def supa_delete(table, match):
    k, v = list(match.items())[0]
    path = f"{table}?{k}=eq.{v}"
    return await supa_req("DELETE", path)


AUTO_DEFAULT = {"text": "", "interval": 300, "groups": [], "enabled": False}


async def get_auto_config(user_id):
    rows = await supa_select("user_prefs", {"user_id": user_id})
    if rows:
        prefs = rows[0].get("prefs", {})
        ac = prefs.get("autopublish", {})
        return {**AUTO_DEFAULT, **ac}
    return dict(AUTO_DEFAULT)


async def save_auto_config(user_id, config):
    rows = await supa_select("user_prefs", {"user_id": user_id})
    if rows:
        prefs = rows[0].get("prefs", {})
        prefs["autopublish"] = config
        await supa_update("user_prefs", {"prefs": prefs}, {"user_id": user_id})
    else:
        await supa_upsert("user_prefs", {"user_id": user_id, "prefs": {"autopublish": config}})


def setup_dot_handlers(client):
    @client.on(events.NewMessage(outgoing=True, pattern=r"^\."))
    async def user_dot_handler(event):
        await process_dot_command(event, event.client)


async def handle_dot(event):
    text = event.raw_text.strip()
    if not text.startswith("."):
        return
    c = await get_client(event)
    if not c:
        return
    await process_dot_command(event, c)


async def get_or_create_client(user_id):
    global _owner_client
    rows = await supa_select("sessions", {"user_id": user_id})
    if not rows:
        return None, "no_session"
    row = rows[0]
    if not row.get("is_active"):
        return None, "inactive"
    ss = row["session_string"]
    if not ss:
        return None, "no_session"
    aid = row.get("api_id") or API_ID
    ah = row.get("api_hash") or API_HASH
    if user_id == OWNER_ID and _owner_client and _owner_client.is_connected():
        return _owner_client, "ok"
    if user_id in user_clients and user_clients[user_id] and user_clients[user_id].is_connected():
        return user_clients[user_id], "ok"
    try:
        client = TelegramClient(StringSession(ss), aid, ah)
        await client.start()
        setup_dot_handlers(client)
        if user_id == OWNER_ID:
            _owner_client = client
        user_clients[user_id] = client
        return client, "ok"
    except Exception as e:
        logger.error(f"Client start failed for {user_id}: {e}")
        return None, "error"


async def save_session(user_id, client, api_id=None, api_hash=None):
    ss = client.session.save()
    data = {"user_id": user_id, "session_string": ss, "is_active": True}
    if api_id: data["api_id"] = api_id
    if api_hash: data["api_hash"] = api_hash
    existing = await supa_select("sessions", {"user_id": user_id})
    if existing:
        await supa_update("sessions", data, {"user_id": user_id})
    else:
        await supa_upsert("sessions", data)


async def get_user_client(user_id):
    c, status = await get_or_create_client(user_id)
    if status == "no_session" and user_id == OWNER_ID and SESSION_STRING:
        try:
            c = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
            await c.start()
            setup_dot_handlers(c)
            await save_session(user_id, c)
            global _owner_client
            _owner_client = c
            user_clients[user_id] = c
            return c
        except Exception as e:
            logger.error(f"SESSION_STRING failed: {e}")
    return c


def fmt_duration(seconds: int) -> str:
    d, r = divmod(seconds, 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    parts = []
    if d: parts.append(f"{d}ي")
    if h: parts.append(f"{h}س")
    if m: parts.append(f"{m}د")
    parts.append(f"{s}ث")
    return " ".join(parts)


def btn(text, data):
    return Button.inline(text, data.encode() if isinstance(data, str) else data)


def main_menu_markup(is_owner=False):
    rows = [
        [btn("🧑 معلوماتي", "me"), btn("👥 كروباتي", "groups")],
        [btn("📨 ارسال", "msg"), btn("📝 بروفايل", "profile")],
        [btn("⚡ سرعة", "ping"), btn("⚙️ أدوات", "tools")],
    ]
    rows.append([btn("🔄 نشر تلقائي", "autopublish")])
    if is_owner:
        rows.append([btn("👑 ادارة", "admin"), btn("⏱ وقت التشغيل", "uptime")])
    return rows


def back_btn():
    return [[btn("🔙 رجوع", "menu_main")]]


def tools_markup():
    return [
        [btn("🔒 بلوك", "block"), btn("🔓 فك بلوك", "unblock")],
        [btn("🗑 حذف", "del"), btn("🧹 مسح", "purge")],
        [btn("ℹ️ آيدي", "id"), btn("👤 معلومات", "uinfo")],
        [btn("📞 رقم", "phone"), btn("🚪 مغادرة", "leave")],
        [btn("📋 سجل", "log"), btn("🔙 رجوع", "menu_main")],
    ]


def profile_markup():
    return [
        [btn("📝 تغيير الاسم", "setname")],
        [btn("📝 تغيير البايو", "setbio")],
        [btn("🔙 رجوع", "menu_main")],
    ]


def admin_markup():
    return [
        [btn("➕ اضافة مشترك", "admin_add"), btn("🔑 تعيين API", "admin_setapi")],
        [btn("🚫 حظر مشترك", "admin_block"), btn("✅ الغاء حظر", "admin_unblock")],
        [btn("❌ حذف مشترك", "admin_remove"), btn("📢 اذاعة للكل", "admin_broadcast")],
        [btn("📋 قائمة المشتركين", "admin_list")],
        [btn("🔙 رجوع", "menu_main")],
    ]


def auto_markup(config):
    s = "⏹" if config["enabled"] else "▶️"
    ss = "auto_stop" if config["enabled"] else "auto_start"
    return [
        [btn("📝 نص", "auto_settext"), btn("⏱ مدة", "auto_setinterval")],
        [btn("👥 كروبات", "auto_groups"), btn("📊 حالة", "auto_status")],
        [btn(s, ss)],
        [btn("🔙 رجوع", "menu_main")],
    ]


def auto_groups_markup(app_data, page=0):
    uid = app_data["uid"]
    cache = _auto_groups_data.get(uid, {}).get("cache", [])
    selected = app_data.get("groups", [])
    ps = 15
    start = page * ps
    gp = cache[start:start + ps]
    tp = max((len(cache) + ps - 1) // ps, 1)
    kb = []
    for gid, gname in gp:
        m = "✅" if gid in selected else "⬜"
        kb.append([btn(f"{m} {gname[:25]}", f"ag_t|{uid}|{gid}")])
    nav = []
    if page > 0: nav.append(btn("⬅️", f"ag_p|{uid}|{page-1}"))
    nav.append(btn(f"{page+1}/{tp}", "noop"))
    if page < tp - 1: nav.append(btn("➡️", f"ag_p|{uid}|{page+1}"))
    if nav: kb.append(nav)
    kb.append([btn("✅ تم", f"ag_done|{uid}"), btn("🔙", "autopublish")])
    return kb


async def owner_check(event):
    return event.sender_id == OWNER_ID


async def subscriber_check(event):
    rows = await supa_select("sessions", {"user_id": event.sender_id})
    return bool(rows and rows[0].get("is_active"))


async def get_client(event):
    uid = event.sender_id
    c = await get_user_client(uid)
    if c:
        return c
    if uid == OWNER_ID:
        user_states[uid] = {"action": "auth_phone", "api_id": API_ID, "api_hash": API_HASH}
        await event.respond("📱 أرسل رقم هاتفك (مع مفتاح الدولة)\nمثال: `+9647xxxxxxxx`\nبعدها راح يطلب منك الكود أرسله بـ **مسافة** بين الأرقام")
        return None
    rows = await supa_select("sessions", {"user_id": uid})
    if not rows:
        await event.respond("❌ أنت غير مشترك")
        return None
    row = rows[0]
    if not row.get("is_active"):
        await event.respond("❌ حسابك موقف")
        return None
    if row.get("session_string"):
        await event.respond("❌ فشل الاتصال. حاول مرة ثانية")
        return None
    aid = row.get("api_id")
    ah = row.get("api_hash")
    if not aid or not ah:
        await event.respond("❌ ما عندك API_ID/HASH. تواصل مع المالك")
        return None
    user_states[uid] = {"action": "auth_phone", "api_id": aid, "api_hash": ah}
    await event.respond("📱 أرسل رقم هاتفك (مع مفتاح الدولة)\nمثال: `+9647xxxxxxxx`")
    return None


WELCOME_TEXT = "── ─ ── ─ ──\n\n**🤖 XTRA SOURCE**\n\nتم التطوير بواسطة: @hsabadi\nقناة البوتات: @xtraforbots"


@bot_client.on(events.NewMessage(pattern="/start"))
async def start_handler(event):
    text = event.raw_text.strip()
    if text.startswith("/start about") or text == "/start about":
        me = await event.client.get_me()
        bot_username = me.username or "i4asBbot"
        about_text = (
            "✦ بـوت XTRA SOURCE ✦\n"
            "« البوت الأقوى لحماية وإدارة حساباتك وتجربة استخدام تليجرام بمميزات خارقة »\n\n"
            "▪ **وظيفة البوت:** تشغيل وإدارة سورس تيليجرام (سورس إكس ترا) بشكل متكامل وآمن لتفعيل ميزات وخدمات حسابات تيليجرام التلقائية والذكية.\n\n"
            "▪ **مميزات البوت:**\n"
            "• تشغيل سريع وحماية كاملة للخصوصية والبيانات المشفرة.\n"
            "• إدارة وتفعيل مميزات التحكم التلقائي، ردود الأفعال الذكية، وحماية الحسابات.\n"
            "• لوحة تحكم برمجية احترافية وسهلة الاستخدام للمطورين والمشتركين.\n\n"
            "▪ **تجربة البوت الفورية:**\n"
            f"« @{bot_username} »\n\n"
            "▪ **للتواصل وشراء نسختك الخاصة:**\n"
            "« @hsabadi »"
        )
        await event.respond(about_text)
        return

    uid = event.sender_id
    if uid == OWNER_ID:
        await event.reply(f"{WELCOME_TEXT}\n\n**👑 القائمة الرئيسية**", buttons=main_menu_markup(True))
        return
    rows = await supa_select("sessions", {"user_id": uid})
    if rows and rows[0].get("is_active") and rows[0].get("session_string"):
        await event.reply(f"{WELCOME_TEXT}\n\n**🤖 القائمة**", buttons=main_menu_markup(False))
    elif rows and rows[0].get("is_active") and rows[0].get("api_id") and rows[0].get("api_hash"):
        await event.reply(f"{WELCOME_TEXT}\n\n📱 سجل دخولك للبدء", buttons=[[btn("📱 تسجيل الدخول", "register")]])
    else:
        welcome_unsub = (
            f"── ─ ── ─ ──\n\n"
            f"**🤖 أهلاً بك في XTRA SOURCE**\n\n"
            f"هذا البوت مخصص للتحكم وإدارة حسابات تيليجرام بشكل احترافي وتلقائي.\n\n"
            f"⚠️ **تنبيه:** حسابك غير مفعل حالياً في الخدمة.\n\n"
            f"👑 المطور: @hsabadi\n"
            f"📢 قناة البوتات: @xtraforbots\n\n"
            f"للاشتراك وتفعيل حسابك، اضغط على الزر أدناه للتواصل."
        )
        buttons = [[Button.url("💬 تواصل للاشتراك", "https://t.me/hsabadi")]]
        await event.reply(welcome_unsub, buttons=buttons)



@bot_client.on(events.NewMessage(pattern="/cancel"))
async def cancel_handler(event):
    if event.sender_id in user_states:
        user_states.pop(event.sender_id)
        await event.reply("✅ تم الالغاء")
    else:
        await event.reply("ماكو عملية")


@bot_client.on(events.CallbackQuery)
async def cb_handler(event):
    await event.answer()
    data = event.data.decode()
    uid = event.sender_id
    is_owner = uid == OWNER_ID

    skip_client = data in ("menu_main", "noop", "admin", "admin_add", "admin_setapi", "admin_remove", "admin_list", "register", "admin_block", "admin_unblock", "admin_broadcast")
    c = None if skip_client else await get_client(event)
    if not c and not skip_client:
        if is_owner:
            return await event.edit("❌ فشل الاتصال بحسابك")
        return await event.edit("❌ غير مشترك")

    if data == "register":
        rows = await supa_select("sessions", {"user_id": uid})
        if not rows:
            return await event.edit("❌ أنت غير مشترك")
        row = rows[0]
        aid, ah = row.get("api_id"), row.get("api_hash")
        if not aid or not ah:
            return await event.edit("❌ ما عندك API_ID/HASH. تواصل مع المالك")
        user_states[uid] = {"action": "auth_phone", "api_id": aid, "api_hash": ah}
        await event.edit("📱 أرسل رقم هاتفك (مع مفتاح الدولة)\nمثال: `+9647xxxxxxxx`")
        return

    if data == "menu_main":
        mk = main_menu_markup(is_owner)
        t = f"{WELCOME_TEXT}\n\n**القائمة الرئيسية**" if is_owner else f"{WELCOME_TEXT}\n\n**القائمة**"
        await event.edit(t, buttons=mk)
        return

    if data == "uptime":
        diff = datetime.now() - START_TIME
        d = diff.days
        h, rem = divmod(diff.seconds, 3600)
        m, s = divmod(rem, 60)
        pts = []
        if d: pts.append(f"{d} يوم")
        if h: pts.append(f"{h} ساعة")
        if m: pts.append(f"{m} دقيقة")
        if s: pts.append(f"{s} ثانية")
        await event.edit(f"⏱ **وقت التشغيل**\n{' و '.join(pts)}", buttons=back_btn())
        return

    if not is_owner and not await subscriber_check(event):
        return await event.edit("❌ غير مشترك")

    try:
        if data == "me":
            me = await c.get_me()
            full = await c(functions.users.GetFullUserRequest(me.id))
            b = full.full_user.about or "—"
            await event.edit(f"**{utils.get_display_name(me)}**\n@{me.username or '—'}\n\nالآيدي : {me.id}\nالرقم : {me.phone or '—'}\nالبايو : {b}", buttons=back_btn())

        elif data == "groups":
            await event.edit("⏳ جاري ...")
            ls = [f"`{d.name}`\n`{d.id}`" async for d in c.iter_dialogs(limit=200) if d.is_group]
            t = "── ─ ── ─ ──\n\n**👥 كروباتك**\n\n" + "\n\n".join(ls) if ls else "ماكو"
            await event.edit(t[:4000], buttons=back_btn())

        elif data == "ping":
            s = datetime.now()
            m = await event.edit("🏓 ...")
            ms = (datetime.now() - s).microseconds // 1000
            await m.edit(f"🏓 **{ms} ms**", buttons=back_btn())

        elif data == "tools":
            await event.edit("── ─ ── ─ ──\n\n**⚙️ أدوات**", buttons=tools_markup())

        elif data == "profile":
            await event.edit("── ─ ── ─ ──\n\n**📝 بروفايل**", buttons=profile_markup())

        elif data == "admin":
            if not is_owner: return
            await event.edit("── ─ ── ─ ──\n\n**👑 ادارة المشتركين**", buttons=admin_markup())

        elif data == "admin_add":
            if not is_owner: return
            user_states[uid] = {"action": "admin_add_id"}
            await event.edit("ارسـل آيدي التيليكرام حق المشترك الجديد", buttons=back_btn())

        elif data == "admin_setapi":
            if not is_owner: return
            user_states[uid] = {"action": "admin_setapi_id"}
            await event.edit("ارسـل آيدي المشترك", buttons=back_btn())

        elif data == "admin_remove":
            if not is_owner: return
            user_states[uid] = {"action": "admin_remove_id"}
            await event.edit("ارسـل آيدي المشترك", buttons=back_btn())

        elif data == "admin_block":
            if not is_owner: return
            user_states[uid] = {"action": "admin_block_id"}
            await event.edit("ارسـل آيدي المشترك لحظره", buttons=back_btn())

        elif data == "admin_unblock":
            if not is_owner: return
            user_states[uid] = {"action": "admin_unblock_id"}
            await event.edit("ارسـل آيدي المشترك لإلغاء الحظر", buttons=back_btn())

        elif data == "admin_broadcast":
            if not is_owner: return
            user_states[uid] = {"action": "admin_broadcast_msg"}
            await event.edit("ارسـل رسالة الاذاعة (نص، صورة، الخ)", buttons=back_btn())

        elif data == "admin_list":
            if not is_owner: return
            rows = await supa_select("sessions")
            active = [r for r in rows if r.get("is_active")] if rows else []
            if not active:
                await event.edit("ماكو مشتركين", buttons=admin_markup())
                return
            ls = [f"• `{r['user_id']}` {'✅' if r.get('is_active') else '❌'}" for r in active]
            await event.edit("── ─ ── ─ ──\n\n**المشتركين**\n\n" + "\n".join(ls)[:4000], buttons=back_btn())

        elif data == "setname":
            user_states[uid] = {"action": "setname"}
            await event.edit("ارسـل الاسم الجديد", buttons=back_btn())

        elif data == "setbio":
            user_states[uid] = {"action": "setbio"}
            await event.edit("ارسـل البايو الجديد", buttons=back_btn())

        elif data == "msg":
            user_states[uid] = {"action": "msg_target"}
            await event.edit("ارسـل اليوزر او الآيدي", buttons=back_btn())

        elif data == "block":
            user_states[uid] = {"action": "block"}
            await event.edit("ارسـل يوزر او آيدي", buttons=back_btn())

        elif data == "unblock":
            user_states[uid] = {"action": "unblock"}
            await event.edit("ارسـل يوزر او آيدي", buttons=back_btn())

        elif data == "del":
            user_states[uid] = {"action": "del_chat"}
            await event.edit("ارسـل آيدي المحادثة", buttons=back_btn())

        elif data == "purge":
            user_states[uid] = {"action": "purge_chat"}
            await event.edit("ارسـل آيدي المحادثة", buttons=back_btn())

        elif data == "id":
            user_states[uid] = {"action": "id"}
            await event.edit("ارسـل يوزر او آيدي", buttons=back_btn())

        elif data == "uinfo":
            user_states[uid] = {"action": "uinfo"}
            await event.edit("ارسـل يوزر او آيدي المستخدم", buttons=back_btn())

        elif data == "phone":
            user_states[uid] = {"action": "phone"}
            await event.edit("ارسـل يوزر او آيدي", buttons=back_btn())

        elif data == "leave":
            user_states[uid] = {"action": "leave"}
            await event.edit("ارسـل آيدي المحادثة", buttons=back_btn())

        elif data == "log":
            user_states[uid] = {"action": "log"}
            await event.edit("ارسـل آيدي المحادثة", buttons=back_btn())

        elif data == "autopublish":
            ac = await get_auto_config(uid)
            _auto_groups_data[uid] = {"config": ac}
            st = "🟢" if ac["enabled"] else "🔴"
            import re
            clean_t = re.sub('<[^<]+?>', '', ac["text"]) if ac.get("text") else ""
            t = clean_t[:40] + ".." if clean_t else "—"
            await event.edit(f"── ─ ── ─ ──\n\n**🔄 نشر**\n{st} {t}\n⏱ {ac['interval']}ث\n👥 {len(ac['groups'])}", buttons=auto_markup(ac))

        elif data == "auto_status":
            ac = await get_auto_config(uid)
            _auto_groups_data[uid] = {"config": ac}
            st = "🟢 شغال" if ac["enabled"] else "🔴 موقف"
            import re
            clean_t = re.sub('<[^<]+?>', '', ac["text"]) if ac.get("text") else ""
            t = clean_t[:50] + ".." if clean_t else "—"
            await event.edit(f"── ─ ── ─ ──\n\nالحالة : {st}\nالنص : {t}\nالمدة : {ac['interval']}ث\nالكروبات : {len(ac['groups'])}", buttons=auto_markup(ac))

        elif data == "auto_settext":
            user_states[uid] = {"action": "auto_text"}
            ac = await get_auto_config(uid)
            await event.edit("ارسـل النص", buttons=auto_markup(ac))

        elif data == "auto_setinterval":
            user_states[uid] = {"action": "auto_interval"}
            ac = await get_auto_config(uid)
            await event.edit("ارسـل المدة (ثواني)", buttons=auto_markup(ac))

        elif data == "auto_groups":
            _auto_groups_data.pop(uid, None)
            await show_auto_groups(event, uid)

        elif data.startswith("ag_done|"):
            parts = data.split("|", 1)
            tuid = int(parts[1])
            if tuid != uid: return
            ac = _auto_groups_data.get(tuid, {}).get("config") or await get_auto_config(tuid)
            st = "🟢" if ac["enabled"] else "🔴"
            import re
            clean_t = re.sub('<[^<]+?>', '', ac["text"]) if ac.get("text") else ""
            t = clean_t[:40] + ".." if clean_t else "—"
            await event.edit(f"── ─ ── ─ ──\n\n**🔄 نشر**\n{st} {t}\n⏱ {ac['interval']}ث\n👥 {len(ac['groups'])}", buttons=auto_markup(ac))

        elif data.startswith("ag_t|"):
            parts = data.split("|")
            tuid, gid = int(parts[1]), int(parts[2])
            if tuid != uid: return
            ac = _auto_groups_data.get(tuid, {}).get("config") or await get_auto_config(tuid)
            if gid in ac["groups"]:
                ac["groups"] = [g for g in ac["groups"] if g != gid]
            else:
                ac["groups"].append(gid)
            await save_auto_config(tuid, ac)
            _auto_groups_data[tuid] = {**_auto_groups_data.get(tuid, {}), "config": ac}
            s = len(ac["groups"])
            cache = _auto_groups_data.get(tuid, {}).get("cache", [])
            await event.edit(f"── ─ ── ─ ──\n\n**اختيار الكروبات**\n\nالمختار : {s} / {len(cache)}", buttons=auto_groups_markup({"uid": tuid, "groups": ac["groups"]}, _auto_groups_data.get(tuid, {}).get("page", 0)))

        elif data.startswith("ag_p|"):
            parts = data.split("|")
            tuid, pg = int(parts[1]), int(parts[2])
            if tuid != uid: return
            _auto_groups_data[tuid] = {**_auto_groups_data.get(tuid, {}), "page": pg}
            await show_auto_groups(event, uid, pg)

        elif data == "auto_start":
            ac = await get_auto_config(uid)
            if not ac["text"] or not ac["groups"]:
                await event.edit("تأكد من النص والكروبات", buttons=auto_markup(ac)); return
            ac["enabled"] = True
            await save_auto_config(uid, ac)
            await event.edit("✅ شغال", buttons=auto_markup(ac))

        elif data == "auto_stop":
            ac = await get_auto_config(uid)
            ac["enabled"] = False
            await save_auto_config(uid, ac)
            await event.edit("✅ موقف", buttons=auto_markup(ac))

        elif data == "noop":
            pass

    except errors.MessageNotModifiedError:
        pass
    except Exception as e:
        await event.edit(f"خطأ : {e}", buttons=back_btn())


async def show_auto_groups(event, uid, page=0):
    try:
        gd = _auto_groups_data.get(uid, {})
        if page == 0 or not gd.get("cache"):
            oc = await get_user_client(uid)
            if not oc:
                return await event.edit("❌ فشل الاتصال", buttons=back_btn())
            cache = [(d.id, d.name or "—") async for d in oc.iter_dialogs(limit=200) if d.is_group]
            _auto_groups_data[uid] = {"cache": cache, "page": page, "config": gd.get("config") or (await get_auto_config(uid))}
        gd = _auto_groups_data.get(uid, {})
        if not gd.get("cache"):
            return await event.edit("ماكو", buttons=back_btn())
        ac = gd.get("config", await get_auto_config(uid))
        s = len(ac["groups"])
        await event.edit(f"── ─ ── ─ ──\n\n**اختيار الكروبات**\n\nالمختار : {s} / {len(gd['cache'])}", buttons=auto_groups_markup({"uid": uid, "groups": ac["groups"]}, page))
    except Exception as e:
        ac = await get_auto_config(uid)
        await event.edit(f"خطأ : {e}", buttons=auto_markup(ac))


DOT_HELP = """**اوامر النقطة (.)**

`.id` - ايدي الحساب او المحادثة
`.me` - معلومات حسابك
`.ping` - سرعة الاستجابة
`.info <username>` - معلومات مستخدم
`.del <n>` - حذف رسائل
`.block <user>` - حظر
`.unblock <user>` - الغاء الحظر
`.leave` - مغادرة المحادثة
`.q <text>` - عرض النص بشكل جميل
`.bold <text>` - نص عريض
`.italic <text>` - نص مائل
`.mono <text>` - نص احادي المسافة
`.strike <text>` - نص مشطوب
`.underline <text>` - نص تحته خط
`.upper <text>` - نص كبير
`.small <text>` - نص صغير
`.mock <text>` - نص ساخر
`.reverse <text>` - عكس النص
`.hash <word>` - توليد هاشتاقات
`.calc <expr>` - آلة حاسبة
`.date` - التاريخ والوقت
`.emoji <text>` - تحويل النص لاموجيات
`.agree` - موافقة على الشروط
`.accept` - تأكيد"""

_small_t = str.maketrans("abcdefghijklmnopqrstuvwxyz0123456789", "ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖqʳˢᵗᵘᵛʷˣʸᶻ⁰¹²³⁴⁵⁶⁷⁸⁹")


async def process_dot_command(event, c):
    uid = event.sender_id
    text = event.raw_text.strip()
    if not text.startswith("."):
        return
    parts = text.split(maxsplit=1)
    cmd = parts[0][1:].lower()
    arg = parts[1] if len(parts) > 1 else ""
    no_client = ("ping", "id", "date", "help", "calc", "hash", "agree", "accept", "emoji", "q", "bold", "italic", "mono", "strike", "underline", "upper", "small", "mock", "reverse", "hash")
    if not c and cmd not in no_client:
        return

    if cmd == "help":
        return await event.reply(DOT_HELP)

    if cmd == "ping":
        s = datetime.now()
        m = await event.reply("🏓 ...")
        ms = (datetime.now() - s).microseconds // 1000
        await m.edit(f"🏓 **{ms}ms**")

    elif cmd == "id":
        if event.is_reply:
            rm = await event.get_reply_message()
            return await event.reply(f"`{rm.sender_id}`")
        await event.reply(f"`{uid}`")

    elif cmd == "me":
        try:
            u = await c.get_me()
            fn = await c(functions.users.GetFullUserRequest(u.id))
            b = fn.full_user.about or "—"
            await event.reply(f"**{utils.get_display_name(u)}**\n@{u.username or '—'}\n\nالآيدي: `{u.id}`\nالرقم: `+{u.phone or '—'}`\nالبايو: {b}")
        except Exception as e:
            await event.reply(f"خطأ: {e}")

    elif cmd == "info":
        if not arg:
            return await event.reply("ارسـل يوزر بعده\nمثال: `.info @username`")
        try:
            u = await c.get_entity(arg)
            fn = await c(functions.users.GetFullUserRequest(u.id))
            await event.reply(f"**{utils.get_display_name(u)}**\n@{u.username or '—'}\nالآيدي: `{u.id}`\nالبايو: {fn.full_user.about or '—'}\nبوت: {'✅' if u.bot else '❌'}")
        except Exception as e:
            await event.reply(f"خطأ: {e}")

    elif cmd == "del":
        n = 1
        if arg and arg.isdigit():
            n = min(int(arg), 50)
        try:
            if event.is_reply and n == 1:
                rm = await event.get_reply_message()
                await c.delete_messages(rm.chat_id, [rm.id])
                await event.reply("✅")
            else:
                msgs = [m.id async for m in c.iter_messages(uid, limit=n, from_user="me")]
                if msgs:
                    await c.delete_messages(uid, msgs)
                await event.reply(f"✅ حذف {len(msgs)}")
        except Exception as e:
            await event.reply(f"خطأ: {e}")

    elif cmd == "block":
        if not arg: return await event.reply("ارسـل يوزر")
        try:
            await c(functions.contacts.BlockRequest(arg))
            await event.reply("✅")
        except Exception as e:
            await event.reply(f"خطأ: {e}")

    elif cmd == "unblock":
        if not arg: return await event.reply("ارسـل يوزر")
        try:
            await c(functions.contacts.UnblockRequest(arg))
            await event.reply("✅")
        except Exception as e:
            await event.reply(f"خطأ: {e}")

    elif cmd == "leave":
        chat = arg or (await event.get_reply_message()).chat_id if event.is_reply else None
        if not chat: return await event.reply("ارسـل آيدي المحادثة")
        try:
            await c(functions.channels.LeaveChannelRequest(int(chat) if str(chat).isdigit() else chat))
            await event.reply("✅")
        except Exception as e:
            await event.reply(f"خطأ: {e}")

    elif cmd == "q":
        t = arg or (await event.get_reply_message()).raw_text if event.is_reply else ""
        if not t: return await event.reply("ارسـل نص او رد على رسالة")
        await event.reply(f"📌 **{t}**")

    elif cmd in ("bold", "italic", "mono", "strike", "underline"):
        if not arg: return await event.reply("ارسـل نص")
        fmts = {"bold": "**{}**", "italic": "__{}__", "mono": "`{}`", "strike": "~~{}~~", "underline": "--{}--"}
        await event.reply(fmts[cmd].format(arg))

    elif cmd == "upper":
        if not arg: return await event.reply("ارسـل نص")
        await event.reply(arg.upper())

    elif cmd == "small":
        if not arg: return await event.reply("ارسـل نص")
        await event.reply(arg.lower().translate(_small_t))

    elif cmd == "mock":
        if not arg: return await event.reply("ارسـل نص")
        await event.reply("".join(c.upper() if i % 2 else c.lower() for i, c in enumerate(arg)))

    elif cmd == "reverse":
        if not arg: return await event.reply("ارسـل نص")
        await event.reply(arg[::-1])

    elif cmd == "hash":
        if not arg: return await event.reply("ارسـل كلمة")
        words = arg.split()
        hs = "\n".join(f"#{w}" for w in words)
        await event.reply(hs + "\n" + "\n".join(f"#{w.capitalize()}" for w in words))

    elif cmd == "calc":
        if not arg: return await event.reply("ارسـل عملية\nمثال: `.calc 2+2*3`")
        try:
            r = eval(arg, {"__builtins__": {}}, {"math": math})
            await event.reply(f"`{arg} = {r}`")
        except Exception as e:
            await event.reply(f"خطأ: {e}")

    elif cmd == "date":
        n = datetime.now()
        await event.reply(n.strftime("📅 %Y/%m/%d\n⏰ %H:%M:%S"))

    elif cmd == "emoji":
        if not arg: return await event.reply("ارسـل نص")
        em = arg.replace("a", "🅰").replace("b", "🅱").replace("c", "🅲").replace("d", "🅳").replace("e", "🅴").replace("o", "🅾")
        await event.reply(em)

    elif cmd == "agree":
        await event.reply("✅ تمت الموافقة على الشروط والاحكام")

    elif cmd == "accept":
        await event.reply("✅ تم التأكيد")

    else:
        await event.reply(f"❌ أمر غير معروف. استخدم `.help`")


@bot_client.on(events.NewMessage)
async def text_handler(event):
    uid = event.sender_id
    if event.raw_text.startswith("."):
        return await handle_dot(event)
    if uid not in user_states or event.raw_text.startswith("/"):
        return
    action = user_states[uid].get("action", "")
    text = event.raw_text.strip()

    try:
        if action.startswith("admin_"):
            if uid != OWNER_ID:
                return
            await handle_admin_text(event, action, text)
            return

        if action == "auth_phone":
            st = user_states[uid]
            c = TelegramClient(StringSession(), st["api_id"], st["api_hash"])
            await c.connect()
            try:
                sent = await c.send_code_request(text.strip())
                user_states[uid] = {"action": "auth_code", "client": c, "phone": text.strip(), "phone_hash": sent.phone_code_hash, "api_id": st["api_id"], "api_hash": st["api_hash"]}
                await event.reply("📲 أرسل كود التفعيل\nبين كل رقم والثاني مسافة حتى ينرسل صح\nمثال: `1 2 3 4 5`")
            except Exception as e:
                await event.reply(f"❌ خطأ: {e}")
            return

        if action == "auth_code":
            st = user_states[uid]
            c = st["client"]
            code = text.strip().replace(" ", "")
            if code.startswith("+"):
                user_states[uid] = {"action": "auth_2fa", "client": c, "phone": st["phone"], "phone_hash": st["phone_hash"], "api_id": st["api_id"], "api_hash": st["api_hash"]}
                await event.reply("🔑 أرسل كلمة مرور التحقق بخطوتين")
                return
            try:
                await c.sign_in(st["phone"], code, phone_code_hash=st["phone_hash"])
                await save_session(uid, c, st["api_id"], st["api_hash"])
                user_clients[uid] = c
                user_states.pop(uid, None)
                mk = main_menu_markup(uid == OWNER_ID)
                await event.reply("✅ تم تسجيل الدخول بنجاح!", buttons=mk)
            except errors.SessionPasswordNeededError:
                user_states[uid] = {"action": "auth_2fa", "client": c, "phone": st["phone"], "phone_hash": st["phone_hash"], "api_id": st["api_id"], "api_hash": st["api_hash"]}
                await event.reply("🔑 التحقق بخطوتين مفعل. أرسل كلمة المرور")
            except Exception as e:
                await event.reply(f"❌ خطأ: {e}")
                user_states.pop(uid, None)
            return

        if action == "auth_2fa":
            st = user_states[uid]
            c = st["client"]
            try:
                await c.sign_in(password=text.strip())
                await save_session(uid, c, st["api_id"], st["api_hash"])
                user_clients[uid] = c
                user_states.pop(uid, None)
                mk = main_menu_markup(uid == OWNER_ID)
                await event.reply("✅ تم تسجيل الدخول بنجاح!", buttons=mk)
            except Exception as e:
                await event.reply(f"❌ خطأ: {e}")
                user_states.pop(uid, None)
            return

        c = await get_client(event)
        if not c:
            return

        if action == "setname":
            await c(functions.account.UpdateProfileRequest(first_name=text, last_name=""))
            await event.reply("✅")

        elif action == "setbio":
            await c(functions.account.UpdateProfileRequest(about=text))
            await event.reply("✅")

        elif action == "msg_target":
            user_states[uid] = {"action": "msg_text", "target": text}
            await event.reply("ارسـل النص")
            return

        elif action == "msg_text":
            target = user_states[uid].get("target", "")
            await c.send_message(target, text)
            await event.reply("✅")

        elif action == "block":
            await c(functions.contacts.BlockRequest(text))
            await event.reply("✅")

        elif action == "unblock":
            await c(functions.contacts.UnblockRequest(text))
            await event.reply("✅")

        elif action == "del_chat":
            user_states[uid] = {"action": "del_msg", "chat": text}
            await event.reply("ارسـل رقم الرسالة")
            return

        elif action == "del_msg":
            chat = user_states[uid].get("chat", "")
            e = await c.get_entity(chat)
            await c.delete_messages(e, [int(text)])
            await event.reply("✅")

        elif action == "purge_chat":
            e = await c.get_entity(text)
            ids = [m.id async for m in c.iter_messages(e, from_user="me")]
            if ids:
                await c.delete_messages(e, ids)
                await event.reply(f"✅ {len(ids)}")
            else:
                await event.reply("ماكو")

        elif action == "id":
            e = await c.get_entity(text)
            await event.reply(f"{e.id}")

        elif action == "uinfo":
            u = await c.get_entity(text)
            f = await c(functions.users.GetFullUserRequest(u.id))
            await event.reply(f"**{utils.get_display_name(u)}**\n@{u.username or '—'}\n\nالآيدي : {u.id}\nالبايو : {f.full_user.about or '—'}\nبوت : {'✅' if u.bot else '❌'}")

        elif action == "phone":
            u = await c.get_entity(text)
            p = getattr(u, "phone", None)
            if p:
                return await event.reply(f"📞 **{utils.get_display_name(u)}**\n`+{p}`")
            await event.reply("⏳ أحاول بإضافته للاتصالات مؤقتاً ...")
            try:
                await c(functions.contacts.AddContactRequest(
                    id=u.id, first_name="_", last_name="", phone="", add_phone_privacy_exception=True
                ))
                await asyncio.sleep(0.5)
                u2 = await c.get_entity(u.id)
                p2 = getattr(u2, "phone", None)
                try:
                    await c(functions.contacts.DeleteContactsRequest(id=[u.id]))
                except Exception:
                    pass
                if p2:
                    await event.reply(f"📞 **{utils.get_display_name(u)}**\n`+{p2}`")
                else:
                    await event.reply("رقمه مخفي حتى بعد الاضافة")
            except Exception as e:
                await event.reply(f"ما ظاهر رقمه ({e})")

        elif action == "leave":
            await c(functions.channels.LeaveChannelRequest(int(text) if text.isdigit() else text))
            await event.reply("✅")

        elif action == "log":
            e = await c.get_entity(text)
            ms = [f"`{m.date.strftime('%H:%M')}` {(m.raw_text or '[ميديا]')[:50]}" async for m in c.iter_messages(e, limit=10, from_user="me")]
            r = "── ─ ── ─ ──\n\nآخر 10\n\n" + "\n".join(reversed(ms)) if ms else "ماكو"
            await event.reply(r[:4000])

        elif action == "auto_text":
            ac = await get_auto_config(uid)
            from telethon.extensions import html
            ac["text"] = html.unparse(event.message.message, event.message.entities)
            await save_auto_config(uid, ac)
            await event.reply("✅")

        elif action == "auto_interval":
            ac = await get_auto_config(uid)
            ac["interval"] = max(int(text), 10)
            await save_auto_config(uid, ac)
            await event.reply(f"✅ {ac['interval']}ث")
            return

    except Exception as e:
        await event.reply(f"خطأ : {e}")

    user_states.pop(uid, None)


async def handle_admin_text(event, action, text):
    uid = event.sender_id

    if action == "admin_add_id":
        user_states[uid] = {"action": "admin_add_api", "target_id": text.strip()}
        await event.reply("ارسـل API_ID (رقم)")
        return

    elif action == "admin_add_api":
        target_id = user_states[uid].get("target_id", "")
        user_states[uid] = {"action": "admin_add_hash", "target_id": target_id, "api_id": text.strip()}
        await event.reply("ارسـل API_HASH")
        return

    elif action == "admin_add_hash":
        target_id = user_states[uid].get("target_id", "")
        api_id = user_states[uid].get("api_id", "")
        api_hash = text.strip()
        if not api_id.isdigit():
            await event.reply("API_ID خطأ"); return
        tid = int(target_id) if target_id.isdigit() else 0
        data = {"user_id": tid, "session_string": "", "api_id": int(api_id), "api_hash": api_hash, "is_active": True}
        existing = await supa_select("sessions", {"user_id": tid})
        if existing:
            await supa_update("sessions", {"api_id": int(api_id), "api_hash": api_hash, "is_active": True}, {"user_id": tid})
        else:
            await supa_upsert("sessions", data)
        await event.reply(f"✅ تم اضافة `{target_id}`")

    elif action == "admin_setapi_id":
        user_states[uid] = {"action": "admin_setapi_api", "target_id": text.strip()}
        await event.reply("ارسـل API_ID الجديد")
        return

    elif action == "admin_setapi_api":
        target_id = user_states[uid].get("target_id", "")
        user_states[uid] = {"action": "admin_setapi_hash", "target_id": target_id, "api_id": text.strip()}
        await event.reply("ارسـل API_HASH الجديد")
        return

    elif action == "admin_setapi_hash":
        target_id = user_states[uid].get("target_id", "")
        api_id = user_states[uid].get("api_id", "")
        api_hash = text.strip()
        if not api_id.isdigit():
            await event.reply("API_ID خطأ"); return
        tid = int(target_id) if target_id.isdigit() else 0
        rows = await supa_select("sessions", {"user_id": tid})
        if not rows:
            await event.reply("المشترك مو موجود"); return
        await supa_update("sessions", {"api_id": int(api_id), "api_hash": api_hash, "is_active": True}, {"user_id": tid})
        if tid in user_clients:
            user_clients.pop(tid, None)
        await event.reply(f"✅ تم تحديث API لـ `{target_id}`")

    elif action == "admin_remove_id":
        target_id = text.strip()
        tid = int(target_id) if target_id.isdigit() else 0
        rows = await supa_select("sessions", {"user_id": tid})
        if not rows:
            await event.reply("ما موجود"); return
        await supa_delete("sessions", {"user_id": tid})
        if tid in user_clients:
            user_clients.pop(tid, None)
        await event.reply(f"✅ تم حذف `{target_id}`")

    elif action == "admin_block_id":
        target_id = text.strip()
        tid = int(target_id) if target_id.isdigit() else 0
        rows = await supa_select("sessions", {"user_id": tid})
        if not rows:
            await event.reply("المشترك غير موجود"); return
        await supa_update("sessions", {"is_active": False}, {"user_id": tid})
        if tid in user_clients:
            try:
                await user_clients[tid].disconnect()
            except Exception:
                pass
            user_clients.pop(tid, None)
        await event.reply(f"🚫 تم حظر المشترك `{target_id}` بنجاح")

    elif action == "admin_unblock_id":
        target_id = text.strip()
        tid = int(target_id) if target_id.isdigit() else 0
        rows = await supa_select("sessions", {"user_id": tid})
        if not rows:
            await event.reply("المشترك غير موجود"); return
        await supa_update("sessions", {"is_active": True}, {"user_id": tid})
        await event.reply(f"✅ تم إلغاء حظر المشترك `{target_id}` بنجاح")

    elif action == "admin_broadcast_msg":
        await event.reply("⏳ جاري بدء الإذاعة للكل...")
        rows = await supa_select("sessions")
        if not rows:
            await event.reply("لا يوجد مشتركين للإرسال إليهم"); return
        success = 0
        failed = 0
        for r in rows:
            tid = r.get("user_id")
            if not tid or tid == OWNER_ID:
                continue
            try:
                await bot_client.send_message(tid, event.message)
                success += 1
                await asyncio.sleep(0.2)
            except Exception:
                failed += 1
        await event.reply(f"📢 **تمت الإذاعة بنجاح!**\n\n🟢 نجاح: {success}\n🔴 فشل: {failed}")

    user_states.pop(uid, None)


async def auto_sender():
    global _auto_last_send
    while True:
        await asyncio.sleep(5)
        try:
            rows = await supa_select("user_prefs")
            if not rows:
                continue
            now = time.time()
            for row in rows:
                try:
                    prefs = row.get("prefs", {})
                    ac = prefs.get("autopublish", {})
                    if not (ac.get("enabled") and ac.get("text") and ac.get("groups")):
                        continue
                    uid = row["user_id"]
                    interval = max(int(ac.get("interval", 300)), 10)
                    key = (uid, tuple(ac["groups"]))
                    last = _auto_last_send.get(key, 0)
                    if now - last < interval:
                        continue
                    oc = await get_user_client(uid)
                    if not oc:
                        continue
                    for chat_id in ac["groups"]:
                        try:
                            await oc.send_message(chat_id, ac["text"], parse_mode='html')
                            await asyncio.sleep(2)
                        except Exception:
                            pass
                    _auto_last_send[key] = now
                except Exception:
                    continue
        except Exception:
            continue


async def health(request):
    return web.Response(text="OK")


async def main():
    logger.info("🚀 جاري تشغيل البوت...")
    await bot_client.start(bot_token=BOT_TOKEN)
    b = await bot_client.get_me()
    logger.info(f"✅ البوت: @{b.username}")

    asyncio.create_task(auto_sender())

    aio_app = web.Application()
    aio_app.router.add_get("/", health)
    aio_app.router.add_get("/health", health)
    runner = web.AppRunner(aio_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 7860)
    await site.start()

    logger.info("📡 استقبال الاوامر...")
    await bot_client.run_until_disconnected()


if __name__ == "__main__":
    bot_client.loop.run_until_complete(main())
