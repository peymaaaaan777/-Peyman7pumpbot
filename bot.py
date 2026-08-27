import os
import json
import time
import requests
import telebot

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise ValueError("BOT_TOKEN پیدا نشد")

bot = telebot.TeleBot(TOKEN)

API = "https://api.geckoterminal.com/api/v2/networks/solana/new_pools"
STATE_FILE = "paper_state.json"

START_BALANCE = 5.0
TRADE_SIZE = 0.50

TAKE_PROFIT = 0.20
STOP_LOSS = 0.10

MIN_LIQUIDITY = 10000
MIN_VOLUME = 5000
MIN_SCORE = 70


def load_state():
    if not os.path.exists(STATE_FILE):
        return {
            "balance": START_BALANCE,
            "trades": [],
            "open": {}
        }

    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except:
        return {
            "balance": START_BALANCE,
            "trades": [],
            "open": {}
        }


def save_state():
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


state = load_state()


def num(value):
    try:
        return float(value or 0)
    except:
        return 0.0


def get_pools():

    headers = {
        "Accept": "application/json;version=20230203"
    }

    r = requests.get(
        API,
        headers=headers,
        timeout=20
    )

    r.raise_for_status()

    return r.json().get("data", [])


def get_info(pool):

    a = pool.get("attributes", {})

    price = num(
        a.get("base_token_price_usd")
    )

    liquidity = num(
        a.get("reserve_in_usd")
    )

    volume = num(
        a.get("volume_usd", {}).get("h24")
    )

    tx = a.get("transactions", {}).get(
        "h24", {}
    )

    buys = int(tx.get("buys", 0) or 0)
    sells = int(tx.get("sells", 0) or 0)

    return {
        "id": pool.get("id", ""),
        "name": a.get("name", "Unknown"),
        "price": price,
        "liquidity": liquidity,
        "volume": volume,
        "buys": buys,
        "sells": sells
    }


def score(x):

    liquidity = x["liquidity"]
    volume = x["volume"]

    buys = x["buys"]
    sells = x["sells"]

    total = buys + sells

    points = 0

    if liquidity >= 100000:
        points += 30
    elif liquidity >= 50000:
        points += 25
    elif liquidity >= 20000:
        points += 20
    elif liquidity >= MIN_LIQUIDITY:
        points += 10
    else:
        return 0

    if volume >= 100000:
        points += 30
    elif volume >= 50000:
        points += 25
    elif volume >= 20000:
        points += 20
    elif volume >= MIN_VOLUME:
        points += 10
    else:
        return 0

    if total:

        buy_ratio = buys / total

        if buy_ratio >= 0.70:
            points += 30
        elif buy_ratio >= 0.60:
            points += 20
        elif buy_ratio >= 0.55:
            points += 10

    if total >= 500:
        points += 10
    elif total >= 200:
        points += 7
    elif total >= 100:
        points += 4

    return min(points, 100)


def open_paper_trade(x, s):

    address = x["id"]

    if address in state["open"]:
        return False

    if s < MIN_SCORE:
        return False

    if x["price"] <= 0:
        return False

    if state["balance"] < TRADE_SIZE:
        return False

    state["balance"] -= TRADE_SIZE

    state["open"][address] = {
        "name": x["name"],
        "entry": x["price"],
        "size": TRADE_SIZE,
        "tp": x["price"] * (1 + TAKE_PROFIT),
        "sl": x["price"] * (1 - STOP_LOSS),
        "score": s,
        "time": time.time()
    }

    save_state()

    return True


def update_trade(x):

    address = x["id"]

    if address not in state["open"]:
        return None

    trade = state["open"][address]

    price = x["price"]

    if price <= 0:
        return None

    result = None

    if price >= trade["tp"]:

        pnl = trade["size"] * TAKE_PROFIT
        result = "TP"

    elif price <= trade["sl"]:

        pnl = -trade["size"] * STOP_LOSS
        result = "SL"

    else:
        return None

    state["balance"] += (
        trade["size"] + pnl
    )

    state["trades"].append({
        "name": trade["name"],
        "entry": trade["entry"],
        "exit": price,
        "pnl": pnl,
        "result": result,
        "score": trade["score"],
        "time": time.time()
    })

    del state["open"][address]

    save_state()

    return result, pnl


def hunt():

    pools = get_pools()

    candidates = []

    for pool in pools:

        x = get_info(pool)

        name = x["name"].upper()

        blocked = [
            "SOL /",
            "SOL/",
            "WSOL",
            "USDC",
            "USDT"
        ]

        if any(b in name for b in blocked):
            continue

        s = score(x)

        if s >= 50:

            closed = update_trade(x)

            opened = False

            if s >= MIN_SCORE:
                opened = open_paper_trade(
                    x, s
                )

            candidates.append(
                (s, x, opened, closed)
            )

    candidates.sort(
        key=lambda z: z[0],
        reverse=True
    )

    return candidates[:5]


@bot.message_handler(commands=["start"])
def start(message):

    bot.reply_to(
        message,
        "🦈 Hunter v3 فعال شد!\n\n"
        "/hunt = اسکن بازار\n"
        "/paper = آمار معاملات\n"
        "/status = وضعیت"
    )


@bot.message_handler(commands=["status"])
def status(message):

    bot.reply_to(
        message,
        "🟢 Hunter آنلاین است\n"
        "🧪 Paper Trading: فعال\n"
        "💰 Real Trading: خاموش\n"
        f"💵 Balance: ${state['balance']:.2f}\n"
        f"📂 Open: {len(state['open'])}"
    )


@bot.message_handler(commands=["hunt"])
def hunt_command(message):

    try:

        bot.send_message(
            message.chat.id,
            "🦈 در حال شکار..."
        )

        results = hunt()

        if not results:

            bot.send_message(
                message.chat.id,
                "🔎 فعلاً فرصت مناسبی پیدا نشد."
            )
            return

        text = "🦈 شکارهای برتر:\n\n"

        for i, (s, x, opened, closed) in enumerate(
            results,
            1
        ):

            total = x["buys"] + x["sells"]

            ratio = (
                x["buys"] / total * 100
                if total else 0
            )

            text += (
                f"#{i} 🪙 {x['name']}\n"
                f"⭐ Score: {s}/100\n"
                f"💵 ${x['price']:.10f}\n"
                f"💧 ${x['liquidity']:,.0f}\n"
                f"📊 ${x['volume']:,.0f}\n"
                f"🟢 Buys: {ratio:.0f}%\n"
            )

            if opened:
                text += "🧪 PAPER BUY: OPEN\n"

            if closed:
                text += (
                    f"📤 CLOSED: "
                    f"{closed[0]} "
                    f"${closed[1]:+.4f}\n"
                )

            text += "\n"

        text += (
            "🧪 Paper Trading\n"
            "⚠️ معامله واقعی خاموش است."
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

    trades = state["trades"]

    wins = sum(
        1 for t in trades
        if t["pnl"] > 0
    )

    losses = sum(
        1 for t in trades
        if t["pnl"] < 0
    )

    pnl = sum(
        t["pnl"] for t in trades
    )

    total = len(trades)

    win_rate = (
        wins / total * 100
        if total else 0
    )

    bot.reply_to(
        message,
        "📊 PAPER TRADING\n\n"
        f"💵 Balance: ${state['balance']:.2f}\n"
        f"📂 Open: {len(state['open'])}\n"
        f"🔢 Closed: {total}\n"
        f"✅ Wins: {wins}\n"
        f"❌ Losses: {losses}\n"
        f"🎯 Win rate: {win_rate:.1f}%\n"
        f"💰 PnL: ${pnl:+.4f}"
    )


print("🦈 Hunter v3 running...")

bot.infinity_polling()
