#!/bin/sh
set -e

if [ -z "$API_ID" ] || [ -z "$API_HASH" ] || [ -z "$BOT_TOKEN" ]; then
    echo "❌ خطأ: API_ID و API_HASH و BOT_TOKEN ضرورين"
    echo "حطهم كـ Secrets في Hugging Face Space Settings"
    exit 1
fi

echo "🚀 بدء تشغيل البوت..."
exec python bot.py
