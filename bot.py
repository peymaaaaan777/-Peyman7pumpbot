import os
import time
import threading
import requests
import telebot

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise ValueError("BOT_TOKEN پیدا نشد")

bot = telebot.TeleBot(TOKEN)

API = "https://api.geckoterminal.com/api/v2/networks/solana/new_pools"

# -----------------------------
# Paper Trading Settings
# -----------------------------

START_BALANCE = 5.0
RISK_PER_TRADE = 0.50
TAKE_PROFIT = 0.20
STOP_LOSS = 0.10

paper_balance = START_BALANCE
trades = []
open_positions = {}

last_scan = 0


# -----------------------------
# API
# -----------------------------

def get_new_pools():

    headers = {
        "Accept": "application/json;version=20230203"
    }

    response = requests.get(
        API,
        headers=headers,
        timeout=20
    )

    response.raise_for_status()

    data = response.json()

    return data.get("data", [])


# -----------------------------
# Helpers
# -----------------------------

def number(value):

    try:
        return float(value or 0)
    except:
        return 0.0


def pool_info(pool):

    attrs = pool.get("attributes", {})
    relationships = pool.get("relationships", {})

    name = attrs.get("name", "Unknown")

    price = number(
        attrs.get("base_token_price_usd")
    )

    liquidity = number(
        attrs.get("reserve_in_usd")
    )

    volume = number(
        attrs.get("volume_usd", {}).get("h24")
    )

    txns = attrs.get("transactions", {}).get("h24", {})

    buys = int(
        txns.get("buys", 0) or 0
    )

    sells = int(
        txns.get("sells", 0) or 0
    )

    address = pool.get("id", "")

    return {
        "name": name,
        "price": price,
        "liquidity": liquidity,
        "volume": volume,
        "buys": buys,
        "sells": sells,
        "address": address,
        "relationships": relationships
    }


# -----------------------------
# Scoring
# -----------------------------

def score_pool(info):

    liquidity = info["liquidity"]
    volume = info["volume"]
    buys = info["buys"]
    sells = info["sells"]

    score = 0

    # Liquidity
    if liquidity >= 100000:
        score += 30
    elif liquidity >= 50000:
        score += 25
    elif liquidity >= 20000:
        score += 18
    elif liquidity >= 10000:
        score += 10
    else:
        return 0

    # Volume
    if volume >= 100000:
        score += 30
    elif volume >= 50000:
        score += 25
    elif volume >= 20000:
        score += 18
    elif volume >= 5000:
        score += 10

    # Buy pressure
    total = buys + sells

    if total > 0:

        ratio = buys / total

        if ratio >= 0.70:
            score += 30
        elif ratio >= 0.60:
            score += 22
        elif ratio >= 0.55:
            score += 12

    # Activity
    if total >= 500:
        score += 10
    elif total >= 200:
        score += 7
    elif total >= 100:
        score += 4

    return min(score, 100)


# -----------------------------
# Paper Entry
# -----------------------------

def paper_entry(info, score):

    global paper_balance

    address = info["address"]

    if address in open_positions:
        return False

    if score < 70:
        return False

    if info["price"] <= 0:
        return False

    if paper_balance < RISK_PER_TRADE:
        return False

    position = {
        "name": info["name"],
        "address": address,
        "entry": info["price"],
        "size": RISK_PER_TRADE,
        "tp": info["price"] * (1 + TAKE_PROFIT),
        "sl": info["price"] * (1 - STOP_LOSS),
        "score": score,
        "opened": time.time()
    }

    paper_balance -= RISK_PER_TRADE

    open_positions[address] = position

    return True


# -----------------------------
# Check positions
# -----------------------------

def check_position(info):

    global paper_balance

    address = info["address"]

    if address not in open_positions:
        return None

    position = open_positions[address]

    price = info["price"]

    if price <= 0:
        return None

    result = None

    if price >= position["tp"]:

        pnl = position["size"] * TAKE_PROFIT

        paper_balance += position["size"] + pnl

        result = ("TP", pnl)

    elif price <= position["sl"]:

        pnl = -position["size"] * STOP_LOSS

        paper_balance += position["size"] + pnl

        result = ("SL", pnl)

    if result:

        trades.append({
            "name": position["name"],
            "entry": position["entry"],
            "exit": price,
            "pnl": result[1],
            "result": result[0],
            "score": position["score"]
        })

        del open_positions[address]

    return result


# -----------------------------
# Scan
# -----------------------------

def perform_scan():

    global last_scan

    now = time.time()

    if now - last_scan < 70:
        return None, "⏳ کمی صبر کن؛ API هنوز در cooldown است."

    last_scan = now

    pools = get_new_pools()

    candidates = []

    for pool in pools:

        info = pool_info(pool)

        name_upper = info["name"].upper()

        # Ignore obvious major-token pools
        blocked = [
            "SOL /",
            "SOL/",
            "WSOL",
            "USDC",
            "USDT"
        ]

        if any(x in name_upper for x in blocked):
            continue

        score = score_pool(info)

        if score >= 50:

            check_position(info)

            paper_entry(info, score)

            candidates.append(
                (score, info)
            )

    candidates.sort(
        key=lambda x: x[0],
        reverse=True
    )

    return candidates[:5], None


# -----------------------------
# Telegram
# -----------------------------

@bot.message_handler(commands=["start"])
def start(message):

    bot.reply_to(
        message,
        "🦈 Paper Meme Hunter v2 فعال شد!\n\n"
        "/hunt = شکار جدید\n"
        "/paper = وضعیت معاملات فرضی\n"
        "/status = وضعیت ربات"
    )


@bot.message_handler(commands=["status"])
def status(message):

    bot.reply_to(
        message,
        "🟢 آنلاین\n"
        "🧪 Paper Trading: فعال\n"
        "💰 معامله واقعی: خاموش\n"
        f"💵 Paper Balance: ${paper_balance:.2f}\n"
        f"📂 Open Positions: {len(open_positions)}"
    )


@bot.message_handler(commands=["hunt"])
def hunt(message):

    bot.send_message(
        message.chat.id,
        "🦈 در حال اسکن New Pools سولانا..."
    )

    try:

        candidates, error = perform_scan()

        if error:

            bot.send_message(
                message.chat.id,
                error
            )
            return

        if not candidates:

            bot.send_message(
                message.chat.id,
                "🔎 فعلاً شکار مناسبی پیدا نشد."
            )
            return

        text = "🦈 بهترین شکارهای جدید:\n\n"

        for i, (score, info) in enumerate(
            candidates,
            1
        ):

            total = info["buys"] + info["sells"]

            buy_ratio = 0

            if total:
                buy_ratio = (
                    info["buys"] / total
                ) * 100

            text += (
                f"#{i} 🪙 {info['name']}\n"
                f"⭐ Score: {score}/100\n"
                f"💵 Price: ${info['price']:.10f}\n"
                f"💧 Liquidity: "
                f"${info['liquidity']:,.0f}\n"
                f"📊 Volume: "
                f"${info['volume']:,.0f}\n"
                f"🟢 Buy ratio: "
                f"{buy_ratio:.0f}%\n"
            )

            if info["address"] in open_positions:
                text += "🧪 PAPER ENTRY: OPEN\n"
            else:
                text += "👀 WATCHING\n"

            text += "\n"

        text += (
            "🧪 Paper Trading فعال است.\n"
            "⚠️ هیچ معامله واقعی انجام نمی‌شود."
        )

        bot.send_message(
            message.chat.id,
            text
        )

    except Exception as e:

        bot.send_message(
            message.chat.id,
            f"❌ خطا:\n{e}"
        )


@bot.message_handler(commands=["paper"])
def paper(message):

    total_pnl = sum(
        t["pnl"] for t in trades
    )

    wins = sum(
        1 for t in trades
        if t["pnl"] > 0
    )

    losses = sum(
        1 for t in trades
        if t["pnl"] < 0
    )

    total = wins + losses

    win_rate = (
        wins / total * 100
        if total else 0
    )

    text = (
        "📊 PAPER TRADING\n\n"
        f"💵 Balance: ${paper_balance:.2f}\n"
        f"📂 Open: {len(open_positions)}\n"
        f"✅ Wins: {wins}\n"
        f"❌ Losses: {losses}\n"
        f"🎯 Win rate: {win_rate:.1f}%\n"
        f"💰 Total PnL: ${total_pnl:.4f}\n"
        f"🔢 Closed trades: {total}\n"
    )

    bot.reply_to(
        message,
        text
    )


# -----------------------------
# Run
# -----------------------------

print(
    "🦈 Paper Meme Hunter v2 running..."
)

bot.infinity_polling()
