import os
import json
import time
import threading
import requests
import telebot

# =========================================================
# CONFIG
# =========================================================

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise ValueError("BOT_TOKEN پیدا نشد")

bot = telebot.TeleBot(TOKEN)

NEW_POOLS_API = (
    "https://api.geckoterminal.com/api/v2/"
    "networks/solana/new_pools"
)

POOL_API = (
    "https://api.geckoterminal.com/api/v2/"
    "networks/solana/pools/"
)

STATE_FILE = "paper_state.json"

START_BALANCE = 5.00
TRADE_SIZE = 0.50

TAKE_PROFIT = 0.20
STOP_LOSS = 0.10

MIN_SCORE = 70
MIN_BUY_PRESSURE = 0.60
MIN_M5_VOLUME = 100

AUTO_SCAN_SECONDS = 180

# برای جلوگیری از چند معامله روی یک توکن
MAX_OPEN_TRADES = 3

# =========================================================
# STATE
# =========================================================

def default_state():
    return {
        "balance": START_BALANCE,
        "trades": [],
        "open": {},
        "chat_id": None
    }


def load_state():

    if not os.path.exists(STATE_FILE):
        return default_state()

    try:

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except Exception:

        return default_state()


state = load_state()


def save_state():

    with open(
        STATE_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            state,
            f,
            indent=2,
            ensure_ascii=False
        )


# =========================================================
# HELPERS
# =========================================================

def num(value):

    try:
        return float(value or 0)

    except Exception:
        return 0.0


def send_user(text):

    chat_id = state.get("chat_id")

    if not chat_id:
        return

    try:

        bot.send_message(
            chat_id,
            text
        )

    except Exception as e:

        print(
            "Telegram error:",
            e
        )


# =========================================================
# API
# =========================================================

def api_get(url):

    response = requests.get(

        url,

        headers={
            "Accept":
            "application/json;version=20230203"
        },

        timeout=20
    )

    response.raise_for_status()

    return response.json()


def get_new_pools():

    data = api_get(
        NEW_POOLS_API
    )

    return data.get(
        "data",
        []
    )


def get_pool(address):

    if not address:
        return None

    try:

        data = api_get(
            POOL_API + address
        )

        return data.get(
            "data"
        )

    except Exception as e:

        print(
            "Pool lookup error:",
            e
        )

        return None


# =========================================================
# PARSING
# =========================================================

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

    m5 = transactions.get(
        "m5",
        {}
    )

    buys = int(
        m5.get(
            "buys",
            0
        ) or 0
    )

    sells = int(
        m5.get(
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


# =========================================================
# SCORING
# =========================================================

def score_pool(x):

    score = 0

    volume = x["m5_volume"]

    total = (
        x["buys"] +
        x["sells"]
    )

    # M5 volume
    if volume >= 10000:

        score += 25

    elif volume >= 1000:

        score += 20

    elif volume >= 250:

        score += 15

    elif volume >= 100:

        score += 8

    # Activity
    if total >= 100:

        score += 20

    elif total >= 50:

        score += 15

    elif total >= 20:

        score += 10

    elif total >= 10:

        score += 5

    # Buy pressure
    if x["buy_ratio"] >= 0.75:

        score += 35

    elif x["buy_ratio"] >= 0.65:

        score += 28

    elif x["buy_ratio"] >= 0.60:

        score += 20

    elif x["buy_ratio"] >= 0.55:

        score += 10

    # 24h volume
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


# =========================================================
# PAPER ENTRY
# =========================================================

def open_paper_trade(x, score):

    address = x["address"]

    if not address:
        return False

    if address in state["open"]:
        return False

    if len(state["open"]) >= MAX_OPEN_TRADES:
        return False

    if score < MIN_SCORE:
        return False

    if x["buy_ratio"] < MIN_BUY_PRESSURE:
        return False

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

        "last_price": x["price"],

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


# =========================================================
# POSITION MONITOR
# =========================================================

def close_trade(
    address,
    price,
    reason
):

    if address not in state["open"]:
        return None

    trade = state["open"][address]

    entry = trade["entry"]
    size = trade["size"]

    change = (
        price - entry
    ) / entry

    pnl = size * change

    # جلوگیری از اختلاف بیشتر از TP/SL
    if reason == "TP":

        pnl = size * TAKE_PROFIT

    elif reason == "SL":

        pnl = -size * STOP_LOSS

    returned = size + pnl

    state["balance"] += returned

    state["trades"].append({

        "name": trade["name"],

        "address": address,

        "entry": entry,

        "exit": price,

        "pnl": pnl,

        "result": reason,

        "score": trade["score"],

        "opened": trade["opened"],

        "closed": time.time()
    })

    del state["open"][address]

    save_state()

    return pnl


def monitor_open_positions():

    addresses = list(
        state["open"].keys()
    )

    for address in addresses:

        pool = get_pool(
            address
        )

        if not pool:
            continue

        x = parse_pool(
            pool
        )

        price = x["price"]

        if price <= 0:
            continue

        trade = state["open"].get(
            address
        )

        if not trade:
            continue

        trade["last_price"] = price

        entry = trade["entry"]

        change = (
            (price - entry)
            / entry
        )

        if price >= trade["tp"]:

            pnl = close_trade(
                address,
                price,
                "TP"
            )

            if pnl is not None:

                send_user(

                    "🎯 TAKE PROFIT\n\n"

                    f"🪙 {trade['name']}\n"

                    f"💵 Entry: "
                    f"${entry:.10f}\n"

                    f"💵 Exit: "
                    f"${price:.10f}\n"

                    f"📈 Change: "
                    f"{change*100:+.2f}%\n"

                    f"💰 PnL: "
                    f"${pnl:+.4f}"
                )

        elif price <= trade["sl"]:

            pnl = close_trade(
                address,
                price,
                "SL"
            )

            if pnl is not None:

                send_user(

                    "🛑 STOP LOSS\n\n"

                    f"🪙 {trade['name']}\n"

                    f"💵 Entry: "
                    f"${entry:.10f}\n"

                    f"💵 Exit: "
                    f"${price:.10f}\n"

                    f"📉 Change: "
                    f"{change*100:+.2f}%\n"

                    f"💰 PnL: "
                    f"${pnl:+.4f}"
                )


# =========================================================
# MARKET SCANNER
# =========================================================

def scan_market():

    pools = get_new_pools()

    candidates = []

    for pool in pools:

        x = parse_pool(
            pool
        )

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

        # حذف توکن‌های اصلی
        if name.startswith("SOL /"):
            continue

        score = score_pool(
            x
        )

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

                "opened": opened
            })

    candidates.sort(

        key=lambda item:
        item["score"],

        reverse=True
    )

    return candidates[:5]


# =========================================================
# AUTO HUNTER
# =========================================================

def auto_hunter():

    print(
        "🦈 Auto Hunter started"
    )

    while True:

        try:

            print(
                "🔎 Checking open positions..."
            )

            monitor_open_positions()

            print(
                "🔎 Scanning new pools..."
            )

            results = scan_market()

            for item in results:

                if not item["opened"]:
                    continue

                x = item["data"]

                send_user(

                    "🚨 🦈 NEW PAPER BUY\n\n"

                    f"🪙 {x['name']}\n"

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
                    f"{x['buy_ratio']*100:.0f}%\n\n"

                    f"💰 Size: "
                    f"${TRADE_SIZE:.2f}\n"

                    f"🎯 TP: "
                    f"+{TAKE_PROFIT*100:.0f}%\n"

                    f"🛑 SL: "
                    f"-{STOP_LOSS*100:.0f}%"
                )

        except Exception as e:

            print(
                "❌ Auto Hunter error:",
                e
            )

        print(
            f"⏳ Next scan in "
            f"{AUTO_SCAN_SECONDS} seconds"
        )

        time.sleep(
            AUTO_SCAN_SECONDS
        )


# =========================================================
# TELEGRAM COMMANDS
# =========================================================

@bot.message_handler(
    commands=["start"]
)
def start(message):

    state["chat_id"] = message.chat.id

    save_state()

    bot.reply_to(

        message,

        "🦈 Hunter FINAL فعال شد!\n\n"

        "🔄 Auto Scanner: فعال\n"

        "🧪 Paper Trading: فعال\n"

        "📡 Position Monitor: فعال\n"

        "💰 Real Trading: خاموش\n\n"

        "/hunt = شکار فوری\n"

        "/paper = آمار معاملات\n"

        "/status = وضعیت ربات"
    )


@bot.message_handler(
    commands=["status"]
)
def status(message):

    state["chat_id"] = message.chat.id

    save_state()

    bot.reply_to(

        message,

        "🟢 ربات آنلاین است\n\n"

        "🦈 Auto Hunter: فعال\n"

        "📡 Position Monitor: فعال\n"

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

    state["chat_id"] = message.chat.id

    save_state()

    try:

        bot.send_message(

            message.chat.id,

            "🦈 در حال شکار..."
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
                x["address"]
                in state["open"]
            ):

                text += (
                    "📂 POSITION: OPEN\n"
                )

            elif item["score"] >= MIN_SCORE:

                text += (
                    "👀 WATCHING\n"
                )

            else:

                text += (
                    "⏸️ FILTERED\n"
                )

            text += "\n"

        text += (

            "🧪 Paper Trading فعال\n"

            f"🎯 Score >= "
            f"{MIN_SCORE}\n"

            f"🟢 Buy pressure >= "
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

    state["chat_id"] = message.chat.id

    save_state()

    trades = state["trades"]

    wins = sum(

        1

        for t in trades

        if t["pnl"] > 0
    )

    losses = sum(

        1

        for t in trades

        if t["pnl"] < 0
    )

    pnl = sum(

        t["pnl"]

        for t in trades
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


# =========================================================
# START
# =========================================================

threading.Thread(

    target=auto_hunter,

    daemon=True

).start()


print(
    "🦈 Hunter FINAL running..."
)

bot.infinity_polling()
