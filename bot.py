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

# فیلتر شکار
MIN_SCORE = 70
MIN_BUY_PRESSURE = 0.60
MIN_M5_VOLUME = 100


def default_state():
    return {
        "balance": START_BALANCE,
        "trades": [],
        "open": {}
    }


def load_state():

    if not os.path.exists(STATE_FILE):
        return default_state()

    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)

    except Exception:
        return default_state()


state = load_state()


def save_state():

    with open(STATE_FILE, "w") as f:
        json.dump(
            state,
            f,
            indent=2
        )


def num(value):

    try:
        return float(value or 0)

    except Exception:
        return 0.0


def get_pools():

    response = requests.get(
        API,
        headers={
            "Accept": "application/json"
        },
        timeout=20
    )

    response.raise_for_status()

    return response.json().get(
        "data",
        []
    )


def parse_pool(pool):

    attrs = pool.get(
        "attributes",
        {}
    )

    transactions = attrs.get(
        "transactions",
        {}
    )

    volumes = attrs.get(
        "volume_usd",
        {}
    )

    m5_transactions = transactions.get(
        "m5",
        {}
    )

    buys = int(
        m5_transactions.get(
            "buys",
            0
        ) or 0
    )

    sells = int(
        m5_transactions.get(
            "sells",
            0
        ) or 0
    )

    total = buys + sells

    buy_ratio = (
        buys / total
        if total > 0
        else 0
    )

    return {

        "id": pool.get(
            "id",
            ""
        ),

        "address": attrs.get(
            "address",
            ""
        ),

        "name": attrs.get(
            "name",
            "Unknown"
        ),

        "price": num(
            attrs.get(
                "base_token_price_usd"
            )
        ),

        "fdv": num(
            attrs.get(
                "fdv_usd"
            )
        ),

        "liquidity": num(
            attrs.get(
                "reserve_in_usd"
            )
        ),

        "m5_volume": num(
            volumes.get(
                "m5"
            )
        ),

        "h24_volume": num(
            volumes.get(
                "h24"
            )
        ),

        "buys": buys,

        "sells": sells,

        "buy_ratio": buy_ratio,

        "created": attrs.get(
            "pool_created_at",
            ""
        )
    }


def score_pool(x):

    score = 0

    # حجم 5 دقیقه
    if x["m5_volume"] >= 10000:
        score += 25

    elif x["m5_volume"] >= 1000:
        score += 20

    elif x["m5_volume"] >= 250:
        score += 15

    elif x["m5_volume"] >= 100:
        score += 8

    # تعداد معاملات
    total = (
        x["buys"] +
        x["sells"]
    )

    if total >= 100:
        score += 20

    elif total >= 50:
        score += 15

    elif total >= 20:
        score += 10

    elif total >= 10:
        score += 5

    # فشار خرید
    if x["buy_ratio"] >= 0.75:
        score += 35

    elif x["buy_ratio"] >= 0.65:
        score += 28

    elif x["buy_ratio"] >= 0.60:
        score += 20

    elif x["buy_ratio"] >= 0.55:
        score += 10

    # حجم 24 ساعت
    if x["h24_volume"] >= 100000:
        score += 10

    elif x["h24_volume"] >= 10000:
        score += 7

    elif x["h24_volume"] >= 1000:
        score += 4

    # FDV
    if x["fdv"] >= 10000:
        score += 5

    return min(
        score,
        100
    )


def open_paper_trade(x, score):

    address = x["address"]

    if not address:
        return False

    if address in state["open"]:
        return False

    # امتیاز حداقل
    if score < MIN_SCORE:
        return False

    # فشار خرید حداقل 60 درصد
    if x["buy_ratio"] < MIN_BUY_PRESSURE:
        return False

    # حجم 5 دقیقه حداقل
    if x["m5_volume"] < MIN_M5_VOLUME:
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

        "tp": (
            x["price"] *
            (1 + TAKE_PROFIT)
        ),

        "sl": (
            x["price"] *
            (1 - STOP_LOSS)
        ),

        "score": score,

        "buy_ratio": x["buy_ratio"],

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

    result = None
    pnl = 0

    if price >= trade["tp"]:

        pnl = (
            trade["size"] *
            TAKE_PROFIT
        )

        result = "TP"

    elif price <= trade["sl"]:

        pnl = -(
            trade["size"] *
            STOP_LOSS
        )

        result = "SL"

    else:
        return None

    state["balance"] += (
        trade["size"] +
        pnl
    )

    state["trades"].append({

        "name": trade["name"],

        "entry": trade["entry"],

        "exit": price,

        "pnl": pnl,

        "result": result,

        "score": trade["score"],

        "opened": trade["opened"],

        "closed": time.time()
    })

    del state["open"][address]

    save_state()

    return result, pnl


def scan_market():

    pools = get_pools()

    candidates = []

    for pool in pools:

        x = parse_pool(pool)

        name = x["name"].upper()

        # فقط جفت‌های سولانا
        if "SOL" not in name:
            continue

        # حذف استیبل‌کوین‌ها
        if (
            "USDC" in name or
            "USDT" in name
        ):
            continue

        closed = update_trade(x)

        score = score_pool(x)

        opened = False

        if score >= MIN_SCORE:

            opened = open_paper_trade(
                x,
                score
            )

        if score >= 40:

            candidates.append({

                "score": score,

                "data": x,

                "opened": opened,

                "closed": closed
            })

    candidates.sort(
        key=lambda item:
        item["score"],
        reverse=True
    )

    return candidates[:5]


@bot.message_handler(
    commands=["start"]
)
def start(message):

    bot.reply_to(

        message,

        "🦈 Hunter v5 فعال شد!\n\n"

        "/hunt = شکار جدید\n"

        "/paper = آمار Paper Trading\n"

        "/status = وضعیت ربات"
    )


@bot.message_handler(
    commands=["status"]
)
def status(message):

    bot.reply_to(

        message,

        "🟢 ربات آنلاین است\n\n"

        "🦈 Hunter: فعال\n"

        "🧪 Paper Trading: فعال\n"

        "💰 Real Trading: خاموش\n\n"

        f"💵 Balance: "
        f"${state['balance']:.2f}\n"

        f"📂 Open: "
        f"{len(state['open'])}\n"

        f"🔢 Closed: "
        f"{len(state['trades'])}"
    )


@bot.message_handler(
    commands=["hunt"]
)
def hunt(message):

    try:

        bot.send_message(

            message.chat.id,

            "🦈 در حال شکار میم‌کوین‌های سولانا..."
        )

        results = scan_market()

        if not results:

            bot.send_message(

                message.chat.id,

                "🔎 فعلاً فرصت مناسبی پیدا نشد."
            )

            return

        text = (
            "🦈 TOP HUNTS\n\n"
        )

        for i, item in enumerate(
            results,
            1
        ):

            x = item["data"]

            text += (

                f"#{i} 🪙 "
                f"{x['name']}\n"

                f"⭐ Score: "
                f"{item['score']}/100\n"

                f"💵 Price: "
                f"${x['price']:.10f}\n"

                f"📊 M5 Volume: "
                f"${x['m5_volume']:,.2f}\n"

                f"🛒 Buys: "
                f"{x['buys']}\n"

                f"📉 Sells: "
                f"{x['sells']}\n"

                f"🟢 Buy pressure: "
                f"{x['buy_ratio']*100:.0f}%\n"
            )

            if item["opened"]:

                text += (
                    "🧪 PAPER BUY: OPEN\n"
                )

            elif (
                item["score"] >= MIN_SCORE
            ):

                text += (
                    "⏸️ شرایط خرید "
                    "کامل نبود\n"
                )

            if item["closed"]:

                text += (

                    f"📤 CLOSED: "
                    f"{item['closed'][0]} "

                    f"${item['closed'][1]:+.4f}\n"
                )

            text += "\n"

        text += (

            "🧪 Paper Trading فعال\n"

            "🎯 حداقل Score: "
            f"{MIN_SCORE}\n"

            "🟢 حداقل Buy pressure: "
            f"{MIN_BUY_PRESSURE*100:.0f}%\n\n"

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


@bot.message_handler(
    commands=["paper"]
)
def paper(message):

    trades = state["trades"]

    wins = sum(

        1 for trade in trades

        if trade["pnl"] > 0
    )

    losses = sum(

        1 for trade in trades

        if trade["pnl"] < 0
    )

    pnl = sum(

        trade["pnl"]

        for trade in trades
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

        f"💵 Balance: "
        f"${state['balance']:.2f}\n"

        f"📂 Open: "
        f"{len(state['open'])}\n"

        f"🔢 Closed: "
        f"{total}\n"

        f"✅ Wins: "
        f"{wins}\n"

        f"❌ Losses: "
        f"{losses}\n"

        f"🎯 Win rate: "
        f"{win_rate:.1f}%\n"

        f"💰 PnL: "
        f"${pnl:+.4f}"
    )


print(
    "🦈 Hunter v5 running..."
)

bot.infinity_polling()
