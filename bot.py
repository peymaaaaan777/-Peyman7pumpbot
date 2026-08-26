import os
import requests
import telebot

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise ValueError("BOT_TOKEN پیدا نشد")

bot = telebot.TeleBot(TOKEN)

API = "https://api.dexscreener.com/latest/dex/search"

@bot.message_handler(commands=["start"])
def start(message):
    bot.reply_to(
        message,
        "🦈 Meme Hunter فعال شد!\n\n"
        "🔎 برای شکار فرصت‌ها /scan را بفرست."
    )

@bot.message_handler(commands=["scan"])
def scan(message):
    try:
        r = requests.get(
            API,
            params={"q": "SOL"},
            timeout=15
        )
        data = r.json()

        pairs = [
            p for p in data.get("pairs", [])
            if p.get("chainId") == "solana"
        ]

        if not pairs:
            bot.reply_to(message, "❌ فعلاً داده‌ای پیدا نشد.")
            return

        pairs.sort(
            key=lambda p: float(
                p.get("volume", {}).get("h24", 0) or 0
            ),
            reverse=True
        )

        text = "🦈 بهترین فرصت‌های فعلی سولانا:\n\n"

        for i, p in enumerate(pairs[:5], 1):
            base = p.get("baseToken", {})
            name = base.get("name", "Unknown")
            symbol = base.get("symbol", "?")

            price = p.get("priceUsd", "N/A")
            liquidity = p.get("liquidity", {}).get("usd", 0)
            volume = p.get("volume", {}).get("h24", 0)

            text += (
                f"#{i} 🪙 {name} ({symbol})\n"
                f"💵 Price: ${price}\n"
                f"💧 Liquidity: ${float(liquidity or 0):,.0f}\n"
                f"📊 Volume 24h: ${float(volume or 0):,.0f}\n\n"
            )

        text += "⚠️ این اطلاعات توصیه خرید نیست و ربات هنوز معامله نمی‌کند."

        bot.reply_to(message, text)

    except Exception as e:
        bot.reply_to(message, f"❌ خطا در دریافت بازار:\n{e}")


@bot.message_handler(commands=["status"])
def status(message):
    bot.reply_to(message, "🟢 Meme Hunter آنلاین است.")


print("🦈 Meme Hunter is running...")
bot.infinity_polling()
