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

MIN_SCORE = 60


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


state = load_state()


def save_state():
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def num(x):
    try:
        return float(x or 0)
    except:
        return 0.0


def get_pools():

    r = requests.get(
        API,
        headers={
            "Accept": "application/json"
        },
        timeout=20
    )

    r.raise_for_status()

    return r.json().get("data", [])


def parse_pool(pool):

    a = pool.get("attributes", {})

    tx = a.get("transactions", {})
    vol = a.get("volume_usd", {})

    m5_tx = tx.get("m5", {})
    m5_vol = num(vol.get("m5"))

    h24_vol = num(vol.get("h24"))

    buys = int(m5_tx.get("buys", 0) or 0)
    sells = int(m5_tx.get("sells", 0) or 0)

    total = buys + sells

    buy_ratio = (
        buys / total
        if total > 0
        else 0
    )

    return {
        "id": pool.get("id", ""),
        "address": a.get("address", ""),
        "name": a.get("name", "Unknown"),
        "price": num(a.get("base_token_price_usd")),
        "fdv": num(a.get("fdv_usd")),
        "liquidity": num(a.get("reserve_in_usd")),
        "m5_volume": m5_vol,
        "h24_volume": h24_vol,
        "buys": buys,
        "sells": sells,
        "buy_ratio": buy_ratio,
        "created": a.get("pool_created_at", "")
    }


def score(x):

    points = 0

    # حجم 5 دقیقه
    if x["m5_volume"] >= 1000:
        points += 25
    elif x["m5_volume"] >= 250:
        points += 18
    elif x["m5_volume"] >= 50:
        points += 10
    elif x["m5_volume"] >= 10:
        points += 5

    # تعداد معاملات
    total = x["buys"] + x["sells"]

    if total >= 20:
        points += 20
    elif total >= 10:
        points += 15
    elif total >= 5:
        points += 10
    elif total >= 2:
        points += 5

    # فشار خرید
    if x["buy_ratio"] >= 0.75:
        points += 30
    elif x["buy_ratio"] >= 0.65:
        points += 22
    elif x["buy_ratio"] >= 0.55:
        points += 12

    # حجم 24 ساعت
    if x["h24_volume"] >= 100000:
        points += 15
    elif x["h24_volume"] >= 10000:
        points += 10
    elif x["h24_volume"] >= 1000:
        points += 5

    # FDV خیلی پایین = ریسک بیشتر
    if x["fdv"] >= 10000:
        points += 5

    return min(points, 100)


def open_trade(x, s):

    address = x["address"]

    if not address:
        return False

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
        "address": address,
        "entry": x["price"],
        "size": TRADE_SIZE,
        "tp": x["price"] * (1 + TAKE_PROFIT),
        "sl": x["price"] * (1 - STOP_LOSS),
        "score": s,
        "opened": time.time()
    }

    save_state()

    return True


def update_trade(x):

    address = x["address"]

    if address not in state["open"]:
        return None

    trade = state["open"][address]

    price = x["price"]

    if price <= 0:
        return None

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
        "closed": time.time()
    })

    del state["open"][address]

    save_state()

    return result, pnl


def scan():

    pools = get_pools()

    candidates = []

    for pool in pools:

        x = parse_pool(pool)

        name = x["name"].upper()

        # فقط جفت‌هایی که SOL دارند
        if "SOL" not in name:
            continue

        # استیبل‌کوین‌ها را حذف کن
        blocked = [
            "USDC",
            "USDT"
        ]

        if any(b in name for b in blocked):
            continue

        closed = update_trade(x)

        s = score(x)

        opened = False

        if s >= MIN_SCORE:
            opened = open_trade(x, s)

        if s >= 30:

            candidates.append({
                "score": s,
                "data": x,
                "opened": opened,
                "closed": closed
            })

    candidates.sort(
        key=lambda z: z["score"],
        reverse=True
    )

    return candidates[:5]


@bot.message_handler(commands=["start"])
def start(message):

    bot.reply_to(
        message,
        "🦈 Hunter v4 فعال شد!\n\n"
        "/hunt = شکار\n"
        "/paper = آمار\n"
        "/status = وضعیت"
    )


@bot.message_handler(commands=["status"])
def status(message):

    bot.reply_to(
        message,
        "🟢 ربات آنلاین\n"
        "🧪 Paper Trading: فعال\n"
        "💰 Real Trading: خاموش\n\n"
        f"💵 Balance: ${state['balance']:.2f}\n"
        f"📂 Open: {len(state['open'])}\n"
        f"🔢 Closed: {len(state['trades'])}"
    )


@bot.message_handler(commands=["hunt"])
def hunt(message):

    try:

        bot.send_message(
            message.chat.id,
            "🦈 در حال شکار توکن‌های تازه..."
        )

        results = scan()

        if not results:

            bot.send_message(
                message.chat.id,
                "🔎 فعلاً داده کافی برای شکار پیدا نشد."
            )
            return

        text = "🦈 TOP HUNTS\n\n"

        for i, item in enumerate(
            results,
            1
        ):

            x = item["data"]

            text += (
                f"#{i} 🪙 {x['name']}\n"
                f"⭐ Score: {item['score']}/100\n"
                f"💵 Price: ${x['price']:.10f}\n"
                f"📊 M5 Volume: ${x['m5_volume']:.2f}\n"
                f"🛒 Buys: {x['buys']}\n"
                f"📉 Sells: {x['sells']}\n"
                f"🟢 Buy pressure: "
                f"{x['buy_ratio']*100:.0f}%\n"
            )

            if item["opened"]:
                text += "🧪 PAPER BUY: OPEN\n"

            if item["closed"]:
                text += (
                    f"📤 CLOSED: "
                    f"{item['closed'][0]} "
                    f"${item['closed'][1]:+.4f}\n"
                )

            text += "\n"

        text += (
            "🧪 Paper Trading فعال\n"
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
        if total
        else 0
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


print("🦈 Hunter v4 running...")

bot.infinity_polling()
