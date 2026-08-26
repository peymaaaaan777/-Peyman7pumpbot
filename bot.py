import os
import requests
import telebot
from datetime import datetime, timezone

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise ValueError("BOT_TOKEN پیدا نشد")

bot = telebot.TeleBot(TOKEN)

API = "https://api.dexscreener.com/latest/dex/search"


def get_pairs():
    r = requests.get(
        API,
        params={"q": "pump"},
        timeout=15
    )
    r.raise_for_status()

    data = r.json()

    return [
        p for p in data.get("pairs", [])
        if p.get("chainId") == "solana"
    ]


def score_pair(pair):
    score = 0

    liquidity = float(
        pair.get("liquidity", {}).get("usd", 0) or 0
    )

    volume = float(
        pair.get("volume", {}).get("h24", 0) or 0
    )

    txns = pair.get("txns", {}).get("h24", {})
    buys = int(txns.get("buys", 0) or 0)
    sells = int(txns.get("sells", 0) or 0)

    change = float(
        pair.get("priceChange", {}).get("h24", 0) or 0
    )

    # نقدینگی
    if liquidity >= 10000:
        score += 25
    elif liquidity >= 5000:
        score += 15

    # حجم
    if volume >= 50000:
        score += 25
    elif volume >= 10000:
        score += 15

    # فشار خرید
    total = buys + sells

    if total > 0:
        buy_ratio = buys / total

        if buy_ratio >= 0.65:
            score += 25
        elif buy_ratio >= 0.55:
            score += 15

    # مومنتوم
    if change >= 20:
        score += 25
    elif change >= 10:
        score += 15
    elif change > 0:
        score += 5

    return min(score, 100)


@bot.message_handler(commands=["start"])
def start(message):
    bot.reply_to(
        message,
        "🦈 Paper Meme Hunter فعال شد!\n\n"
        "/hunt = شکار خودکار\n"
        "/status = وضعیت ربات"
    )


@bot.message_handler(commands=["status"])
def status(message):
    bot.reply_to(
        message,
        "🟢 ربات آنلاین است\n"
        "🧪 حالت: Paper Trading\n"
        "💰 معامله واقعی: خاموش"
    )


@bot.message_handler(commands=["hunt"])
def hunt(message):

    bot.send_message(
        message.chat.id,
        "🦈 در حال شکار میم‌کوین‌های سولانا..."
    )

    try:
        pairs = get_pairs()

        results = []

        for pair in pairs:

            score = score_pair(pair)

            if score < 50:
                continue

            token = pair.get("baseToken", {})

            name = token.get("name", "Unknown")
            symbol = token.get("symbol", "?")

            price = pair.get("priceUsd", "N/A")

            liquidity = float(
                pair.get("liquidity", {}).get("usd", 0) or 0
            )

            volume = float(
                pair.get("volume", {}).get("h24", 0) or 0
            )

            results.append({
                "score": score,
                "name": name,
                "symbol": symbol,
                "price": price,
                "liquidity": liquidity,
                "volume": volume
            })

        results.sort(
            key=lambda x: x["score"],
            reverse=True
        )

        if not results:
            bot.send_message(
                message.chat.id,
                "🔎 فعلاً شکار مناسبی با فیلترهای ما پیدا نشد."
            )
            return

        text = "🦈 بهترین شکارهای فعلی:\n\n"

        for i, item in enumerate(results[:5], 1):

            text += (
                f"#{i} 🪙 {item['name']} "
                f"({item['symbol']})\n"
                f"⭐ Score: {item['score']}/100\n"
                f"💵 Price: ${item['price']}\n"
                f"💧 Liquidity: "
                f"${item['liquidity']:,.0f}\n"
                f"📊 Volume 24h: "
                f"${item['volume']:,.0f}\n\n"
            )

        text += (
            "🧪 حالت Paper Trading\n"
            "⚠️ هنوز هیچ خرید یا فروش واقعی انجام نمی‌شود."
        )

        bot.send_message(message.chat.id, text)

    except Exception as e:

        bot.send_message(
            message.chat.id,
            f"❌ خطا:\n{e}"
        )


print("🦈 Paper Meme Hunter is running...")

bot.infinity_polling()
