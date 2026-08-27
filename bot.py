import os
import time
import json
import threading
import requests
import telebot
from telebot import types

# =========================================================
# 🦈 MEME HUNTER V9 FINAL
# =========================================================

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise ValueError("❌ BOT_TOKEN پیدا نشد")

bot = telebot.TeleBot(TOKEN)

NEW_POOLS_API = (
    "https://api.geckoterminal.com/api/v2/"
    "networks/solana/new_pools"
)

POOL_API = (
    "https://api.geckoterminal.com/api/v2/"
    "networks/solana/pools/"
)

STATE_FILE = "bot_state.json"

START_BALANCE = 5.00
SCAN_INTERVAL = 180

# =========================================================
# DEFAULT SETTINGS
# =========================================================

DEFAULT_SETTINGS = {
    "min_score": 60,
    "min_buy_pressure": 60,
    "min_liquidity": 5000,
    "min_volume": 500,
    "trade_size": 0.50,
    "take_profit": 20,
    "stop_loss": 10,
    "max_open": 3,
    "auto_hunter": True,
    "paper_trading": True,
    "real_trading": False
}

BLOCKED_WORDS = [
    "USDC",
    "USDT",
    "WSOL",
    "SOL",
    "BTC",
    "ETH",
    "WBTC",
    "WETH"
]

# =========================================================
# STATE
# =========================================================

def default_state():
    return {
        "balance": START_BALANCE,
        "starting_balance": START_BALANCE,
        "trades": [],
        "open_positions": {},
        "chat_id": None,
        "settings": DEFAULT_SETTINGS.copy()
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

            data = json.load(f)

        result = default_state()

        result.update(data)

        result["settings"] = {
            **DEFAULT_SETTINGS,
            **result.get("settings", {})
        }

        return result

    except Exception as e:

        print("State load error:", e)

        return default_state()


state = load_state()


def save_state():

    try:

        with open(
            STATE_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                state,
                f,
                ensure_ascii=False,
                indent=2
            )

    except Exception as e:

        print("Save error:", e)


# =========================================================
# HTTP
# =========================================================

def get_json(url):

    headers = {
        "Accept":
        "application/json;version=20230203",
        "User-Agent":
        "MemeHunterV9/1.0"
    }

    response = requests.get(
        url,
        headers=headers,
        timeout=20
    )

    response.raise_for_status()

    return response.json()


# =========================================================
# GECKO
# =========================================================

def get_new_pools():

    try:

        data = get_json(
            NEW_POOLS_API
        )

        return data.get(
            "data",
            []
        )

    except Exception as e:

        print(
            "New pools error:",
            e
        )

        return []


def get_pool(address):

    try:

        data = get_json(
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
# HELPERS
# =========================================================

def number(value):

    try:
        return float(value or 0)

    except:
        return 0.0


def safe_int(value):

    try:
        return int(value or 0)

    except:
        return 0


# =========================================================
# PARSE
# =========================================================

def parse_pool(pool):

    attrs = pool.get(
        "attributes",
        {}
    )

    transactions = (
        attrs
        .get("transactions", {})
        .get("m5", {})
    )

    volume = (
        attrs
        .get("volume_usd", {})
    )

    buys = safe_int(
        transactions.get(
            "buys",
            0
        )
    )

    sells = safe_int(
        transactions.get(
            "sells",
            0
        )
    )

    total = buys + sells

    pressure = (
        buys / total
        if total > 0
        else 0
    )

    return {

        "address":
        attrs.get(
            "address",
            ""
        ),

        "name":
        attrs.get(
            "name",
            "Unknown"
        ),

        "price":
        number(
            attrs.get(
                "base_token_price_usd"
            )
        ),

        "liquidity":
        number(
            attrs.get(
                "reserve_in_usd"
            )
        ),

        "fdv":
        number(
            attrs.get(
                "fdv_usd"
            )
        ),

        "m5_volume":
        number(
            volume.get(
                "m5"
            )
        ),

        "h24_volume":
        number(
            volume.get(
                "h24"
            )
        ),

        "buys":
        buys,

        "sells":
        sells,

        "buy_pressure":
        pressure
    }


# =========================================================
# MEME FILTER
# =========================================================

def is_meme_candidate(info):

    name = info["name"].upper()

    for word in BLOCKED_WORDS:

        if word in name:
            return False

    if info["price"] <= 0:
        return False

    if info["liquidity"] <= 0:
        return False

    return True


# =========================================================
# SCORE V9
# =========================================================

def calculate_score(info):

    score = 0

    volume = info["m5_volume"]
    liquidity = info["liquidity"]
    pressure = info["buy_pressure"]

    buys = info["buys"]
    sells = info["sells"]

    total = buys + sells

    # -------------------------
    # VOLUME 25
    # -------------------------

    if volume >= 20000:
        score += 25

    elif volume >= 10000:
        score += 22

    elif volume >= 5000:
        score += 18

    elif volume >= 2000:
        score += 15

    elif volume >= 1000:
        score += 11

    elif volume >= 500:
        score += 7

    # -------------------------
    # LIQUIDITY 20
    # -------------------------

    if liquidity >= 50000:
        score += 20

    elif liquidity >= 20000:
        score += 17

    elif liquidity >= 10000:
        score += 14

    elif liquidity >= 5000:
        score += 10

    elif liquidity >= 2500:
        score += 5

    # -------------------------
    # BUY PRESSURE 25
    # -------------------------

    if pressure >= 0.85:
        score += 25

    elif pressure >= 0.75:
        score += 21

    elif pressure >= 0.65:
        score += 17

    elif pressure >= 0.60:
        score += 13

    elif pressure >= 0.55:
        score += 7

    # -------------------------
    # TRANSACTIONS 15
    # -------------------------

    if total >= 300:
        score += 15

    elif total >= 200:
        score += 13

    elif total >= 100:
        score += 10

    elif total >= 50:
        score += 7

    elif total >= 20:
        score += 4

    # -------------------------
    # BUY/SELL BALANCE 15
    # -------------------------

    if buys > sells * 3:
        score += 15

    elif buys > sells * 2:
        score += 12

    elif buys > sells:
        score += 8

    elif buys == sells:
        score += 3

    return min(
        score,
        100
    )


# =========================================================
# RISK
# =========================================================

def risk_level(info):

    liquidity = info["liquidity"]
    volume = info["m5_volume"]
    sells = info["sells"]
    buys = info["buys"]

    if liquidity < 2500:
        return "🔴 HIGH"

    if volume > liquidity * 5:
        return "🔴 HIGH"

    if sells > buys:
        return "🟠 MEDIUM"

    if buys >= sells * 2:
        return "🟢 LOWER"

    return "🟡 MEDIUM"


# =========================================================
# QUALIFICATION
# =========================================================

def qualifies(info, score):

    s = state["settings"]

    if score < s["min_score"]:
        return False

    if (
        info["buy_pressure"]
        <
        s["min_buy_pressure"] / 100
    ):
        return False

    if info["liquidity"] < s["min_liquidity"]:
        return False

    if info["m5_volume"] < s["min_volume"]:
        return False

    return True


# =========================================================
# PAPER BUY
# =========================================================

def paper_buy(info, score):

    s = state["settings"]

    address = info["address"]

    if not address:
        return False

    if address in state["open_positions"]:
        return False

    if not qualifies(
        info,
        score
    ):
        return False

    if (
        len(state["open_positions"])
        >= s["max_open"]
    ):
        return False

    size = min(
        s["trade_size"],
        state["balance"]
    )

    if size <= 0:
        return False

    state["balance"] -= size

    state["open_positions"][address] = {

        "name":
        info["name"],

        "address":
        address,

        "entry":
        info["price"],

        "size":
        size,

        "score":
        score,

        "opened":
        time.time()
    }

    save_state()

    return True


# =========================================================
# CLOSE PAPER POSITION
# =========================================================

def close_position(
    address,
    price,
    reason
):

    if address not in state["open_positions"]:
        return None

    position = (
        state["open_positions"]
        [address]
    )

    entry = position["entry"]

    if entry <= 0:
        return None

    real_change = (
        price - entry
    ) / entry

    pnl = (
        position["size"]
        *
        real_change
    )

    state["balance"] += (
        position["size"]
        +
        pnl
    )

    state["trades"].append({

        "name":
        position["name"],

        "entry":
        entry,

        "exit":
        price,

        "pnl":
        pnl,

        "result":
        reason,

        "score":
        position["score"],

        "closed":
        time.time()
    })

    del state[
        "open_positions"
    ][address]

    save_state()

    return pnl


# =========================================================
# MONITOR
# =========================================================

def monitor_positions():

    for address in list(
        state["open_positions"]
    ):

        try:

            pool = get_pool(
                address
            )

            if not pool:
                continue

            info = parse_pool(
                pool
            )

            price = info["price"]

            if price <= 0:
                continue

            position = (
                state["open_positions"]
                .get(address)
            )

            if not position:
                continue

            entry = position["entry"]

            tp = entry * (
                1 +
                state["settings"]
                ["take_profit"] / 100
            )

            sl = entry * (
                1 -
                state["settings"]
                ["stop_loss"] / 100
            )

            if price >= tp:

                pnl = close_position(
                    address,
                    price,
                    "TP"
                )

                notify(
                    "🎯 TAKE PROFIT\n\n"
                    f"🪙 {position['name']}\n"
                    f"📈 Entry: ${entry:.10f}\n"
                    f"📈 Exit: ${price:.10f}\n"
                    f"💰 PnL: ${pnl:+.4f}"
                )

            elif price <= sl:

                pnl = close_position(
                    address,
                    price,
                    "SL"
                )

                notify(
                    "🛑 STOP LOSS\n\n"
                    f"🪙 {position['name']}\n"
                    f"📉 Entry: ${entry:.10f}\n"
                    f"📉 Exit: ${price:.10f}\n"
                    f"💰 PnL: ${pnl:+.4f}"
                )

        except Exception as e:

            print(
                "Monitor error:",
                e
            )


# =========================================================
# SCAN MARKET
# =========================================================

def scan_market():

    pools = get_new_pools()

    candidates = []

    for pool in pools:

        try:

            info = parse_pool(
                pool
            )

            if not is_meme_candidate(
                info
            ):
                continue

            score = calculate_score(
                info
            )

            if score < 30:
                continue

            opened = False

            if (
                state["settings"]
                ["paper_trading"]
            ):

                opened = paper_buy(
                    info,
                    score
                )

            candidates.append({

                "score":
                score,

                "info":
                info,

                "opened":
                opened,

                "risk":
                risk_level(info)
            })

        except Exception as e:

            print(
                "Scanner error:",
                e
            )

    candidates.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    return candidates[:5]


# =========================================================
# TELEGRAM NOTIFY
# =========================================================

def notify(text):

    chat_id = state.get(
        "chat_id"
    )

    if not chat_id:
        return

    try:

        bot.send_message(
            chat_id,
            text
        )

    except Exception as e:

        print(
            "Notify error:",
            e
        )


# =========================================================
# MAIN MENU
# =========================================================

def main_keyboard():

    kb = types.InlineKeyboardMarkup()

    kb.row(
        types.InlineKeyboardButton(
            "🦈 Hunt",
            callback_data="hunt"
        ),
        types.InlineKeyboardButton(
            "📊 Paper",
            callback_data="paper"
        )
    )

    kb.row(
        types.InlineKeyboardButton(
            "⚙️ Settings",
            callback_data="settings"
        ),
        types.InlineKeyboardButton(
            "📡 Status",
            callback_data="status"
        )
    )

    kb.row(
        types.InlineKeyboardButton(
            "📂 Positions",
            callback_data="positions"
        ),
        types.InlineKeyboardButton(
            "🔄 Refresh",
            callback_data="refresh"
        )
    )

    return kb


# =========================================================
# SETTINGS
# =========================================================

def settings_text():

    s = state["settings"]

    return (

        "⚙️ تنظیمات MEME HUNTER V9\n\n"

        f"⭐ حداقل Score: "
        f"{s['min_score']}\n"

        f"🟢 حداقل Buy Pressure: "
        f"{s['min_buy_pressure']}%\n"

        f"💧 حداقل Liquidity: "
        f"${s['min_liquidity']:,.0f}\n"

        f"📊 حداقل M5 Volume: "
        f"${s['min_volume']:,.0f}\n\n"

        f"💵 حجم معامله: "
        f"${s['trade_size']:.2f}\n"

        f"🎯 Take Profit: "
        f"{s['take_profit']}%\n"

        f"🛑 Stop Loss: "
        f"{s['stop_loss']}%\n"

        f"📂 Max Open: "
        f"{s['max_open']}\n\n"

        f"🦈 Auto Hunter: "
        f"{'🟢 روشن' if s['auto_hunter'] else '🔴 خاموش'}\n"

        f"🧪 Paper Trading: "
        f"{'🟢 روشن' if s['paper_trading'] else '🔴 خاموش'}\n\n"

        "💰 Real Trading: 🔒 قفل"
    )


def settings_keyboard():

    kb = types.InlineKeyboardMarkup()

    kb.row(
        types.InlineKeyboardButton(
            "⭐ Score -",
            callback_data="score_minus"
        ),
        types.InlineKeyboardButton(
            "⭐ Score +",
            callback_data="score_plus"
        )
    )

    kb.row(
        types.InlineKeyboardButton(
            "🟢 Buy% -",
            callback_data="buy_minus"
        ),
        types.InlineKeyboardButton(
            "🟢 Buy% +",
            callback_data="buy_plus"
        )
    )

    kb.row(
        types.InlineKeyboardButton(
            "💧 Liquidity -",
            callback_data="liq_minus"
        ),
        types.InlineKeyboardButton(
            "💧 Liquidity +",
            callback_data="liq_plus"
        )
    )

    kb.row(
        types.InlineKeyboardButton(
            "📊 Volume -",
            callback_data="vol_minus"
        ),
        types.InlineKeyboardButton(
            "📊 Volume +",
            callback_data="vol_plus"
        )
    )

    kb.row(
        types.InlineKeyboardButton(
            "💵 مبلغ -",
            callback_data="size_minus"
        ),
        types.InlineKeyboardButton(
            "💵 مبلغ +",
            callback_data="size_plus"
        )
    )

    kb.row(
        types.InlineKeyboardButton(
            "🎯 TP -",
            callback_data="tp_minus"
        ),
        types.InlineKeyboardButton(
            "🎯 TP +",
            callback_data="tp_plus"
        )
    )

    kb.row(
        types.InlineKeyboardButton(
            "🛑 SL -",
            callback_data="sl_minus"
        ),
        types.InlineKeyboardButton(
            "🛑 SL +",
            callback_data="sl_plus"
        )
    )

    kb.row(
        types.InlineKeyboardButton(
            "🦈 Auto ON/OFF",
            callback_data="auto"
        )
    )

    kb.row(
        types.InlineKeyboardButton(
            "🧪 Paper ON/OFF",
            callback_data="paper"
        )
    )

    kb.row(
        types.InlineKeyboardButton(
            "🔒 Real Trading",
            callback_data="real"
        )
    )

    kb.row(
        types.InlineKeyboardButton(
            "🔙 منوی اصلی",
            callback_data="home"
        )
    )

    return kb


# =========================================================
# HUNT TEXT
# =========================================================

def hunt_text(candidates):

    if not candidates:

        return (
            "🦈 فعلاً هیچ Meme Coin مناسبی "
            "پیدا نشد."
        )

    text = (
        "🦈 TOP MEME HUNTS V9\n\n"
    )

    for i, item in enumerate(
        candidates,
        1
    ):

        info = item["info"]
        score = item["score"]

        if item["opened"]:

            status = "🧪 PAPER BUY: OPEN"

        elif qualifies(
            info,
            score
        ):

            status = "🎯 QUALIFIED"

        else:

            status = "👀 WATCHING"

        text += (

            f"#{i} 🪙 "
            f"{info['name']}\n"

            f"⭐ Score: "
            f"{score}/100\n"

            f"💵 Price: "
            f"${info['price']:.10f}\n"

            f"📊 M5 Volume: "
            f"${info['m5_volume']:,.2f}\n"

            f"💧 Liquidity: "
            f"${info['liquidity']:,.2f}\n"

            f"🛒 Buys: "
            f"{info['buys']}\n"

            f"📉 Sells: "
            f"{info['sells']}\n"

            f"🟢 Buy pressure: "
            f"{info['buy_pressure'] * 100:.0f}%\n"

            f"⚠️ Risk: "
            f"{item['risk']}\n"

            f"{status}\n\n"
        )

    s = state["settings"]

    text += (

        "⚙️ FILTERS\n"

        f"⭐ Score ≥ {s['min_score']}\n"

        f"🟢 Buy Pressure ≥ "
        f"{s['min_buy_pressure']}%\n"

        f"💧 Liquidity ≥ "
        f"${s['min_liquidity']:,.0f}\n"

        f"📊 M5 Volume ≥ "
        f"${s['min_volume']:,.0f}\n\n"

        "🧪 Paper Trading: "
        f"{'ON' if s['paper_trading'] else 'OFF'}\n"

        "💰 Real Trading: 🔒 LOCKED"
    )

    return text


# =========================================================
# START
# =========================================================

@bot.message_handler(
    commands=["start"]
)
def start(message):

    state["chat_id"] = message.chat.id

    save_state()

    bot.send_message(
        message.chat.id,
        "🦈 MEME HUNTER V9 FINAL\n\n"
        "ربات آماده است.\n"
        "تمام کنترل‌های اصلی از همین منو انجام می‌شود.\n\n"
        "🧪 Paper Trading فعال است.\n"
        "💰 Real Trading فعلاً قفل است. 🔒",
        reply_markup=main_keyboard()
    )


# =========================================================
# SETTINGS COMMAND
# =========================================================

@bot.message_handler(
    commands=["settings"]
)
def settings_command(message):

    state["chat_id"] = message.chat.id

    save_state()

    bot.send_message(
        message.chat.id,
        settings_text(),
        reply_markup=settings_keyboard()
    )


# =========================================================
# HUNT COMMAND
# =========================================================

@bot.message_handler(
    commands=["hunt"]
)
def hunt_command(message):

    state["chat_id"] = message.chat.id

    save_state()

    bot.send_message(
        message.chat.id,
        "🔎 در حال شکار Meme Coin های سولانا..."
    )

    candidates = scan_market()

    bot.send_message(
        message.chat.id,
        hunt_text(candidates),
        reply_markup=main_keyboard()
    )


# =========================================================
# PAPER COMMAND
# =========================================================

@bot.message_handler(
    commands=["paper"]
)
def paper_command(message):

    send_paper(
        message.chat.id
    )


def send_paper(chat_id):

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

    total = len(trades)

    pnl = sum(
        t["pnl"]
        for t in trades
    )

    win_rate = (
        wins / total * 100
        if total
        else 0
    )

    bot.send_message(

        chat_id,

        "🧪 PAPER TRADING V9\n\n"

        f"💵 Balance: "
        f"${state['balance']:.2f}\n"

        f"📂 Open: "
        f"{len(state['open_positions'])}\n"

        f"🔢 Closed: "
        f"{total}\n"

        f"✅ Wins: "
        f"{wins}\n"

        f"❌ Losses: "
        f"{losses}\n"

        f"🎯 Win rate: "
        f"{win_rate:.1f}%\n"

        f"💰 PnL: "
        f"${pnl:+.4f}",

        reply_markup=main_keyboard()
    )


# =========================================================
# STATUS
# =========================================================

def send_status(chat_id):

    s = state["settings"]

    bot.send_message(

        chat_id,

        "📡 MEME HUNTER STATUS\n\n"

        "🟢 Bot: ONLINE\n"

        f"🦈 Auto Hunter: "
        f"{'ON' if s['auto_hunter'] else 'OFF'}\n"

        f"🧪 Paper Trading: "
        f"{'ON' if s['paper_trading'] else 'OFF'}\n"

        "💰 Real Trading: 🔒 LOCKED\n\n"

        f"💵 Balance: "
        f"${state['balance']:.2f}\n"

        f"📂 Open Positions: "
        f"{len(state['open_positions'])}\n"

        f"🔢 Closed Trades: "
        f"{len(state['trades'])}",

        reply_markup=main_keyboard()
    )


@bot.message_handler(
    commands=["status"]
)
def status_command(message):

    state["chat_id"] = message.chat.id

    save_state()

    send_status(
        message.chat.id
    )


# =========================================================
# CALLBACKS
# =========================================================

@bot.callback_query_handler(
    func=lambda call: True
)
def callbacks(call):

    data = call.data

    s = state["settings"]

    try:

        if data == "home":

            bot.edit_message_text(
                "🦈 MEME HUNTER V9\n\n"
                "آماده شکار هستیم. 🦈",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=main_keyboard()
            )

        elif data == "hunt":

            bot.answer_callback_query(
                call.id,
                "🔎 در حال اسکن..."
            )

            candidates = scan_market()

            bot.edit_message_text(
                hunt_text(candidates),
                call.message.chat.id,
                call.message.message_id,
                reply_markup=main_keyboard()
            )

        elif data == "paper":

            bot.answer_callback_query(
                call.id
            )

            send_paper(
                call.message.chat.id
            )

        elif data == "status":

            bot.answer_callback_query(
                call.id
            )

            send_status(
                call.message.chat.id
            )

        elif data == "settings":

            bot.edit_message_text(
                settings_text(),
                call.message.chat.id,
                call.message.message_id,
                reply_markup=settings_keyboard()
            )

        elif data == "refresh":

            bot.answer_callback_query(
                call.id,
                "🔄 به‌روزرسانی شد"
            )

            candidates = scan_market()

            bot.edit_message_text(
                hunt_text(candidates),
                call.message.chat.id,
                call.message.message_id,
                reply_markup=main_keyboard()
            )

        elif data == "positions":

            text = (
                "📂 OPEN POSITIONS\n\n"
            )

            if not state["open_positions"]:

                text += "❌ پوزیشن بازی وجود ندارد."

            else:

                for position in state[
                    "open_positions"
                ].values():

                    text += (

                        f"🪙 {position['name']}\n"

                        f"💵 Entry: "
                        f"${position['entry']:.10f}\n"

                        f"💰 Size: "
                        f"${position['size']:.2f}\n"

                        f"⭐ Score: "
                        f"{position['score']}/100\n\n"
                    )

            bot.send_message(
                call.message.chat.id,
                text,
                reply_markup=main_keyboard()
            )

        # -------------------------
        # SCORE
        # -------------------------

        elif data == "score_minus":

            s["min_score"] = max(
                40,
                s["min_score"] - 5
            )

        elif data == "score_plus":

            s["min_score"] = min(
                90,
                s["min_score"] + 5
            )

        # -------------------------
        # BUY PRESSURE
        # -------------------------

        elif data == "buy_minus":

            s["min_buy_pressure"] = max(
                50,
                s["min_buy_pressure"] - 5
            )

        elif data == "buy_plus":

            s["min_buy_pressure"] = min(
                90,
                s["min_buy_pressure"] + 5
            )

        # -------------------------
        # LIQUIDITY
        # -------------------------

        elif data == "liq_minus":

            s["min_liquidity"] = max(
                1000,
                s["min_liquidity"] - 1000
            )

        elif data == "liq_plus":

            s["min_liquidity"] = min(
                50000,
                s["min_liquidity"] + 1000
            )

        # -------------------------
        # VOLUME
        # -------------------------

        elif data == "vol_minus":

            s["min_volume"] = max(
                100,
                s["min_volume"] - 250
            )

        elif data == "vol_plus":

            s["min_volume"] = min(
                20000,
                s["min_volume"] + 250
            )

        # -------------------------
        # SIZE
        # -------------------------

        elif data == "size_minus":

            s["trade_size"] = max(
                0.10,
                round(
                    s["trade_size"] - 0.10,
                    2
                )
            )

        elif data == "size_plus":

            s["trade_size"] = min(
                5.00,
                round(
                    s["trade_size"] + 0.10,
                    2
                )
            )

        # -------------------------
        # TP
        # -------------------------

        elif data == "tp_minus":

            s["take_profit"] = max(
                5,
                s["take_profit"] - 5
            )

        elif data == "tp_plus":

            s["take_profit"] = min(
                100,
                s["take_profit"] + 5
            )

        # -------------------------
        # SL
        # -------------------------

        elif data == "sl_minus":

            s["stop_loss"] = max(
                5,
                s["stop_loss"] - 5
            )

        elif data == "sl_plus":

            s["stop_loss"] = min(
                50,
                s["stop_loss"] + 5
            )

        # -------------------------
        # AUTO
        # -------------------------

        elif data == "auto":

            s["auto_hunter"] = not s[
                "auto_hunter"
            ]

        # -------------------------
        # PAPER
        # -------------------------

        elif data == "paper_toggle":

            s["paper_trading"] = not s[
                "paper_trading"
            ]

        # -------------------------
        # REAL
        # -------------------------

        elif data == "real":

            bot.answer_callback_query(

                call.id,

                "🔒 Real Trading در V9 قفل است. "
                "هیچ کلید خصوصی داخل ربات ذخیره نمی‌شود.",

                show_alert=True
            )

            return

        else:

            bot.answer_callback_query(
                call.id
            )

            return

        save_state()

        bot.answer_callback_query(
            call.id,
            "✅ ذخیره شد"
        )

        bot.edit_message_text(
            settings_text(),
            call.message.chat.id,
            call.message.message_id,
            reply_markup=settings_keyboard()
        )

    except Exception as e:

        print(
            "Callback error:",
            e
        )

        try:

            bot.answer_callback_query(
                call.id,
                "❌ خطا"
            )

        except:
            pass


# =========================================================
# AUTO HUNTER
# =========================================================

def auto_loop():

    print(
        "🦈 MEME HUNTER V9 AUTO STARTED"
    )

    while True:

        try:

            if state["settings"][
                "auto_hunter"
            ]:

                monitor_positions()

                candidates = scan_market()

                for item in candidates:

                    if item["opened"]:

                        info = item["info"]

                        notify(

                            "🚨 🦈 PAPER BUY V9\n\n"

                            f"🪙 {info['name']}\n"

                            f"⭐ Score: "
                            f"{item['score']}/100\n"

                            f"💵 Price: "
                            f"${info['price']:.10f}\n"

                            f"💧 Liquidity: "
                            f"${info['liquidity']:,.2f}\n"

                            f"🟢 Buy Pressure: "
                            f"{info['buy_pressure']*100:.0f}%\n\n"

                            "🧪 Paper Trading"
                        )

        except Exception as e:

            print(
                "Auto Hunter error:",
                e
            )

        time.sleep(
            SCAN_INTERVAL
        )


# =========================================================
# RUN
# =========================================================

threading.Thread(
    target=auto_loop,
    daemon=True
).start()

print(
    "🦈 MEME HUNTER V9 FINAL RUNNING..."
)

bot.infinity_polling()
