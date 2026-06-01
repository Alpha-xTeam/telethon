---
title: Telegram Controller Bot
emoji: 🤖
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
license: mit
---

# Telegram Controller Bot 🤖

بوت تيليكرام (عادي من BotFather) يستخدم تيليثون بحسابك الشخصي لتنفيذ الأوامر.

**الفكرة:** تكتب أوامر للبوت، والبوت ينفذها بحسابك (مثل: مسح رسائل، انضمام لقنوات، ارسال رسائل، الخ).

## المتطلبات

1. **API_ID و API_HASH**: من [my.telegram.org](https://my.telegram.org) - سجل، اعمل تطبيق، انسخ القيم.
2. **BOT_TOKEN**: من [@BotFather](https://t.me/BotFather) - اكتب `/newbot` واتبع الخطوات.
3. **OWNER_ID**: آيدي تيليكرام الخاص بك (من [@userinfobot](https://t.me/userinfobot)).
4. **حساب تيليكرام عادي** (مو بوت) - اللي تيليثون راح يتصل بيه.

## الإعداد على Hugging Face

1. اعمل Space جديد بـ **Docker SDK**.
2. ارفع كل ملفات المشروع (بما فيها `userbot.session` اللي راح تولده محلياً).
3. روح **Settings → Variables and secrets** واضف:
   - `API_ID` = آيدي التطبيق (رقم)
   - `API_HASH` = هاش التطبيق
   - `BOT_TOKEN` = توكن البوت من BotFather
   - `OWNER_ID` = آيدي حسابك
   - `SESSION_NAME` = اسم السيشن (افتراضي `userbot`)
   - `LOG_LEVEL` = مستوى اللوق (افتراضي `INFO`)

## تسجيل الدخول أول مرة (محلياً)

قبل ما ترفع على Hugging Face، لازم تسجل دخول بحسابك أول مرة محلياً:

```bash
pip install -r requirements.txt
cp .env.example .env
# عدل .env بالقيم
python bot.py
```

ادخل رقمك والكود اللي يجيك من تيليكرام. راح يتولد ملف `userbot.session` - **ارفعه للـ Space**.

## الاستخدام

1. افتح البوت على تيليكرام (اللي سويته بـ BotFather).
2. اضغط `/start` أو `/help` لعرض الأوامر.
3. استخدم الأوامر.

## الأوامر المتاحة

**معلومات:** `/me` `/ping` `/uptime` `/dialogs` `/id` `/uinfo` `/cinfo`
**ادارة:** `/join` `/leave` `/block` `/unblock` `/purge` `/del` `/log`
**رسائل:** `/msg` `/forward` `/typing` `/dl` `/broadcast`
**بروفايل:** `/setname` `/setbio`

## تحذير ⚠️

- يوزربوتات ممكن تسبب حظر حسابك من تيليقرام.
- OWNER_ID ضروري عشان ما احد ثاني يستخدم بوتك.
- استخدمه على مسؤوليتك.
