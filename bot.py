import os
import json
import time
import threading
import requests
import telebot
from telebot import types

# =========================================================
# 🦈 MEME HUNTER V9.1
# Paper Trading + Dashboard + PnL + TP/SL
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN تنظیم نشده")

bot = telebot.TeleBot(BOT_TOKEN)

STATE_FILE = "bot_state.json"

START_BALANCE = 5.0
SCAN_INTERVAL = 180

# Solana wrapped SOL
SOL_MINT = "So11111111111111111111111111111111111111112"

NEW_POOLS_API = (
    "https://api.geckoterminal.com/api/v2/"
    "networks/solana/new_pools"
)

POOL_API = (
    "https://api.geckoterminal.com/api/v2/"
    "networks/solana/pools/"
)


# =========================================================
# DEFAULT SETTINGS
# =========================================================

DEFAULT_SETTINGS = {
    "min_score": 60,
    "min_buy_pressure": 60,
    "min_liquidity": 5000,
    "min_m5_volume": 500,

    "trade_size": 0.50,

    "take_profit": 20,
    "stop_loss": 10,

    "max_open": 2,

    "daily_loss_limit": 10,

    "auto_hunter": True,
    "paper_trading": True,

    "emergency_stop": False
}


# =========================================================
# STATE
# =========================================================

def default_state():

    return {
        "balance": START_BALANCE,

        "initial_balance": START_BALANCE,

        "chat_id": None,

        "trades": [],

        "open_positions": {},

        "daily_pnl": 0.0,

        "daily_date": time.strftime("%Y-%m-%d"),

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

        state = default_state()

        state.update(data)

        state["settings"] = {
            **DEFAULT_SETTINGS,
            **state.get("settings", {})
        }

        return state

    except Exception as e:

        print("State error:", e)

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
# DAILY RESET
# =========================================================

def daily_reset():

    today = time.strftime("%Y-%m-%d")

    if state["daily_date"] != today:

        state["daily_date"] = today

        state["daily_pnl"] = 0.0

        save_state()


# =========================================================
# HTTP
# =========================================================

def get_json(url):

    headers = {
        "Accept": "application/json"
    }

    response = requests.get(
        url,
        headers=headers,
        timeout=20
    )

    response.raise_for_status()

    return response.json()


# =========================================================
# MARKET DATA
# =========================================================

def get_new_pools():

    data = get_json(
        NEW_POOLS_API
    )

    return data.get(
        "data",
        []
    )


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
            "Pool error:",
            e
        )

        return None


# =========================================================
# NUMBER
# =========================================================

def number(value):

    try:
        return float(
            value or 0
        )

    except Exception:
        return 0.0


# =========================================================
# PARSE POOL
# =========================================================

def parse_pool(pool):

    attrs = pool.get(
        "attributes",
        {}
    )

    transactions = (
        attrs
        .get(
            "transactions",
            {}
        )
        .get(
            "m5",
            {}
        )
    )

    volume = (
        attrs
        .get(
            "volume_usd",
            {}
        )
    )

    buys = int(
        transactions.get(
            "buys",
            0
        ) or 0
    )

    sells = int(
        transactions.get(
            "sells",
            0
        ) or 0
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

        "m5_volume":
        number(
            volume.get(
                "m5"
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

def meme_filter(info):

    name = info["name"].upper()

    blocked = [
        "USDC",
        "USDT",
        "USDE",
        "DAI",
        "USD"
    ]

    for word in blocked:

        if word in name:
            return False

    if info["price"] <= 0:
        return False

    if info["liquidity"] <= 0:
        return False

    return True


# =========================================================
# SCORE
# =========================================================

def calculate_score(info):

    score = 0

    volume = info["m5_volume"]

    liquidity = info["liquidity"]

    buys = info["buys"]

    sells = info["sells"]

    total = buys + sells

    pressure = info["buy_pressure"]

    # Volume

    if volume >= 50000:
        score += 25

    elif volume >= 20000:
        score += 22

    elif volume >= 10000:
        score += 20

    elif volume >= 5000:
        score += 16

    elif volume >= 1000:
        score += 12

    elif volume >= 500:
        score += 8

    # Liquidity

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

    # Transactions

    if total >= 500:
        score += 20

    elif total >= 250:
        score += 17

    elif total >= 100:
        score += 14

    elif total >= 50:
        score += 10

    elif total >= 20:
        score += 6

    # Buy pressure

    if pressure >= 0.90:
        score += 25

    elif pressure >= 0.80:
        score += 22

    elif pressure >= 0.70:
        score += 18

    elif pressure >= 0.60:
        score += 12

    elif pressure >= 0.55:
        score += 6

    return min(
        score,
        100
    )


# =========================================================
# QUALIFY
# =========================================================

def qualifies(
    info,
    score
):

    s = state["settings"]

    if score < s["min_score"]:
        return False

    if (
        info["buy_pressure"]
        <
        s["min_buy_pressure"] / 100
    ):
        return False

    if (
        info["liquidity"]
        <
        s["min_liquidity"]
    ):
        return False

    if (
        info["m5_volume"]
        <
        s["min_m5_volume"]
    ):
        return False

    return True


# =========================================================
# PAPER BUY
# =========================================================

def paper_buy(
    info,
    score
):

    daily_reset()

    s = state["settings"]

    if s["emergency_stop"]:
        return False

    if not s["paper_trading"]:
        return False

    if not s["auto_hunter"]:
        return False

    if not qualifies(
        info,
        score
    ):
        return False

    address = info["address"]

    if not address:
        return False

    if address in state["open_positions"]:
        return False

    if (
        len(state["open_positions"])
        >= s["max_open"]
    ):
        return False

    # Daily loss protection

    max_loss = (
        state["initial_balance"]
        *
        s["daily_loss_limit"]
        / 100
    )

    if state["daily_pnl"] <= -max_loss:
        return False

    size = min(
        float(s["trade_size"]),
        float(state["balance"])
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
# CLOSE POSITION
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

    entry = float(
        position["entry"]
    )

    size = float(
        position["size"]
    )

    if entry <= 0 or size <= 0:
        return None

    # REAL percentage price change

    change = (
        price - entry
    ) / entry

    # REAL PNL

    pnl = (
        size * change
    )

    # Return original capital + PNL

    returned = (
        size + pnl
    )

    returned = max(
        0.0,
        returned
    )

    state["balance"] += returned

    state["daily_pnl"] += pnl

    state["trades"].append({

        "name":
        position["name"],

        "address":
        address,

        "entry":
        entry,

        "exit":
        price,

        "size":
        size,

        "pnl":
        pnl,

        "change_percent":
        change * 100,

        "result":
        reason,

        "score":
        position["score"],

        "time":
        time.time()
    })

    del state[
        "open_positions"
    ][address]

    save_state()

    return pnl


# =========================================================
# TOTAL PNL
# =========================================================

def total_pnl():

    return sum(
        float(t["pnl"])
        for t in state["trades"]
    )


def pnl_percent():

    initial = float(
        state["initial_balance"]
    )

    if initial <= 0:
        return 0

    return (
        total_pnl()
        / initial
        * 100
    )


# =========================================================
# DASHBOARD
# =========================================================

def dashboard_text():

    daily_reset()

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

    closed = len(trades)

    win_rate = (

        wins / closed * 100

        if closed

        else 0
    )

    pnl = total_pnl()

    pnl_pct = pnl_percent()

    s = state["settings"]

    return (

        "🦈 MEME HUNTER V9.1\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        "💰 DASHBOARD\n\n"

        f"💵 Balance: "
        f"${state['balance']:.4f}\n"

        f"📈 Total PnL: "
        f"${pnl:+.4f}\n"

        f"📊 Return: "
        f"{pnl_pct:+.2f}%\n"

        f"📅 Today PnL: "
        f"${state['daily_pnl']:+.4f}\n\n"

        f"📂 Open Positions: "
        f"{len(state['open_positions'])}\n"

        f"🔢 Closed Trades: "
        f"{closed}\n"

        f"✅ Wins: "
        f"{wins}\n"

        f"❌ Losses: "
        f"{losses}\n"

        f"🎯 Win Rate: "
        f"{win_rate:.1f}%\n\n"

        "⚙️ SETTINGS\n\n"

        f"⭐ Min Score: "
        f"{s['min_score']}\n"

        f"🟢 Buy Pressure: "
        f"{s['min_buy_pressure']}%\n"

        f"💧 Liquidity: "
        f"${s['min_liquidity']:,.0f}\n"

        f"📊 M5 Volume: "
        f"${s['min_m5_volume']:,.0f}\n"

        f"💵 Trade Size: "
        f"${s['trade_size']:.2f}\n"

        f"🎯 Take Profit: "
        f"{s['take_profit']}%\n"

        f"🛑 Stop Loss: "
        f"{s['stop_loss']}%\n"

        f"📂 Max Open: "
        f"{s['max_open']}\n\n"

        f"🦈 Auto Hunter: "
        f"{'🟢 ON' if s['auto_hunter'] else '🔴 OFF'}\n"

        f"🧪 Paper Trading: "
        f"{'🟢 ON' if s['paper_trading'] else '🔴 OFF'}\n\n"

        "💰 Real Trading: 🔒 LOCKED"
    )


# =========================================================
# DASHBOARD KEYBOARD
# =========================================================

def dashboard_keyboard():

    k = types.InlineKeyboardMarkup()

    k.row(

        types.InlineKeyboardButton(
            "🔄 Refresh",
            callback_data="dashboard"
        ),

        types.InlineKeyboardButton(
            "🦈 Hunt",
            callback_data="hunt"
        )
    )

    k.row(

        types.InlineKeyboardButton(
            "📂 Positions",
            callback_data="positions"
        ),

        types.InlineKeyboardButton(
            "📊 Trades",
            callback_data="trades"
        )
    )

    k.row(

        types.InlineKeyboardButton(
            "⚙️ Settings",
            callback_data="settings"
        )
    )

    k.row(

        types.InlineKeyboardButton(
            "🚨 EMERGENCY STOP",
            callback_data="emergency"
        )
    )

    return k


# =========================================================
# /START
# =========================================================

@bot.message_handler(
    commands=["start"]
)
def start(message):

    state["chat_id"] = (
        message.chat.id
    )

    save_state()

    bot.send_message(

        message.chat.id,

        dashboard_text(),

        reply_markup=
        dashboard_keyboard()
    )


# =========================================================
# /DASHBOARD
# =========================================================

@bot.message_handler(
    commands=["dashboard"]
)
def dashboard(message):

    state["chat_id"] = (
        message.chat.id
    )

    save_state()

    bot.send_message(

        message.chat.id,

        dashboard_text(),

        reply_markup=
        dashboard_keyboard()
    )


# =========================================================
# /STATUS
# =========================================================

@bot.message_handler(
    commands=["status"]
)
def status(message):

    bot.send_message(

        message.chat.id,

        dashboard_text(),

        reply_markup=
        dashboard_keyboard()
    )


# =========================================================
# /PAPER
# =========================================================

@bot.message_handler(
    commands=["paper"]
)
def paper(message):

    bot.send_message(

        message.chat.id,

        dashboard_text(),

        reply_markup=
        dashboard_keyboard()
    )


# =========================================================
# POSITIONS
# =========================================================

def positions_text():

    positions = (
        state["open_positions"]
    )

    if not positions:

        return (
            "📂 OPEN POSITIONS\n\n"
            "فعلاً پوزیشن بازی وجود ندارد."
        )

    text = (
        "📂 OPEN POSITIONS\n\n"
    )

    for position in positions.values():

        text += (

            f"🪙 {position['name']}\n"

            f"💵 Entry: "
            f"${position['entry']:.10f}\n"

            f"💰 Size: "
            f"${position['size']:.2f}\n"

            f"⭐ Score: "
            f"{position['score']}/100\n\n"
        )

    return text


# =========================================================
# TRADES
# =========================================================

def trades_text():

    trades = state["trades"]

    if not trades:

        return (
            "📊 CLOSED TRADES\n\n"
            "هنوز معامله بسته‌شده‌ای نداریم."
        )

    recent = trades[-10:]

    text = (
        "📊 LAST TRADES\n\n"
    )

    for trade in reversed(
        recent
    ):

        emoji = (
            "✅"
            if trade["pnl"] > 0
            else "❌"
        )

        text += (

            f"{emoji} "
            f"{trade['name']}\n"

            f"💰 PnL: "
            f"${trade['pnl']:+.4f}\n"

            f"📈 Change: "
            f"{trade.get('change_percent', 0):+.2f}%\n"

            f"🎯 {trade['result']}\n\n"
        )

    return text


# =========================================================
# SETTINGS
# =========================================================

def settings_text():

    s = state["settings"]

    return (

        "⚙️ MEME HUNTER V9.1\n\n"

        f"⭐ Score: "
        f"{s['min_score']}\n"

        f"🟢 Buy Pressure: "
        f"{s['min_buy_pressure']}%\n"

        f"💧 Liquidity: "
        f"${s['min_liquidity']:,.0f}\n"

        f"📊 M5 Volume: "
        f"${s['min_m5_volume']:,.0f}\n\n"

        f"💵 Trade Size: "
        f"${s['trade_size']:.2f}\n"

        f"🎯 TP: "
        f"{s['take_profit']}%\n"

        f"🛑 SL: "
        f"{s['stop_loss']}%\n"

        f"📂 Max Open: "
        f"{s['max_open']}\n\n"

        f"🦈 Auto: "
        f"{'🟢 ON' if s['auto_hunter'] else '🔴 OFF'}\n"

        f"🧪 Paper: "
        f"{'🟢 ON' if s['paper_trading'] else '🔴 OFF'}\n\n"

        "💰 Real Trading: 🔒 LOCKED"
    )


def settings_keyboard():

    k = types.InlineKeyboardMarkup()

    k.row(

        types.InlineKeyboardButton(
            "⭐ Score −",
            callback_data="score_minus"
        ),

        types.InlineKeyboardButton(
            "⭐ Score +",
            callback_data="score_plus"
        )
    )

    k.row(

        types.InlineKeyboardButton(
            "🟢 Buy% −",
            callback_data="buy_minus"
        ),

        types.InlineKeyboardButton(
            "🟢 Buy% +",
            callback_data="buy_plus"
        )
    )

    k.row(

        types.InlineKeyboardButton(
            "💵 Size −",
            callback_data="size_minus"
        ),

        types.InlineKeyboardButton(
            "💵 Size +",
            callback_data="size_plus"
        )
    )

    k.row(

        types.InlineKeyboardButton(
            "🎯 TP −",
            callback_data="tp_minus"
        ),

        types.InlineKeyboardButton(
            "🎯 TP +",
            callback_data="tp_plus"
        )
    )

    k.row(

        types.InlineKeyboardButton(
            "🛑 SL −",
            callback_data="sl_minus"
        ),

        types.InlineKeyboardButton(
            "🛑 SL +",
            callback_data="sl_plus"
        )
    )

    k.row(

        types.InlineKeyboardButton(
            "📂 Open −",
            callback_data="open_minus"
        ),

        types.InlineKeyboardButton(
            "📂 Open +",
            callback_data="open_plus"
        )
    )

    k.row(

        types.InlineKeyboardButton(
            "🦈 Auto ON/OFF",
            callback_data="auto"
        )
    )

    k.row(

        types.InlineKeyboardButton(
            "🧪 Paper ON/OFF",
            callback_data="paper_toggle"
        )
    )

    k.row(

        types.InlineKeyboardButton(
            "🚨 EMERGENCY STOP",
            callback_data="emergency"
        )
    )

    k.row(

        types.InlineKeyboardButton(
            "🏠 Dashboard",
            callback_data="dashboard"
        )
    )

    return k


# =========================================================
# CALLBACKS
# =========================================================

@bot.callback_query_handler(
    func=lambda call: True
)
def callbacks(call):

    data = call.data

    s = state["settings"]

    if data == "dashboard":

        bot.answer_callback_query(
            call.id
        )

        try:

            bot.edit_message_text(

                dashboard_text(),

                call.message.chat.id,

                call.message.message_id,

                reply_markup=
                dashboard_keyboard()
            )

        except Exception:
            pass

        return

    if data == "hunt":

        bot.answer_callback_query(
            call.id
        )

        hunt(
            call.message
        )

        return

    if data == "positions":

        bot.answer_callback_query(
            call.id
        )

        bot.send_message(

            call.message.chat.id,

            positions_text()
        )

        return

    if data == "trades":

        bot.answer_callback_query(
            call.id
        )

        bot.send_message(

            call.message.chat.id,

            trades_text()
        )

        return

    if data == "settings":

        bot.answer_callback_query(
            call.id
        )

        bot.send_message(

            call.message.chat.id,

            settings_text(),

            reply_markup=
            settings_keyboard()
        )

        return

    if data == "score_minus":

        s["min_score"] = max(
            30,
            s["min_score"] - 5
        )

    elif data == "score_plus":

        s["min_score"] = min(
            95,
            s["min_score"] + 5
        )

    elif data == "buy_minus":

        s["min_buy_pressure"] = max(
            50,
            s["min_buy_pressure"] - 5
        )

    elif data == "buy_plus":

        s["min_buy_pressure"] = min(
            95,
            s["min_buy_pressure"] + 5
        )

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
            200.0,
            round(
                s["trade_size"] + 0.10,
                2
            )
        )

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

    elif data == "open_minus":

        s["max_open"] = max(
            1,
            s["max_open"] - 1
        )

    elif data == "open_plus":

        s["max_open"] = min(
            10,
            s["max_open"] + 1
        )

    elif data == "auto":

        s["auto_hunter"] = (
            not s["auto_hunter"]
        )

    elif data == "paper_toggle":

        s["paper_trading"] = (
            not s["paper_trading"]
        )

    elif data == "emergency":

        s["emergency_stop"] = True

        s["auto_hunter"] = False

        save_state()

        bot.answer_callback_query(

            call.id,

            "🚨 EMERGENCY STOP فعال شد",

            show_alert=True
        )

        try:

            bot.edit_message_text(

                settings_text(),

                call.message.chat.id,

                call.message.message_id,

                reply_markup=
                settings_keyboard()
            )

        except Exception:
            pass

        return

    save_state()

    bot.answer_callback_query(

        call.id,

        "✅ ذخیره شد"
    )

    try:

        bot.edit_message_text(

            settings_text(),

            call.message.chat.id,

            call.message.message_id,

            reply_markup=
            settings_keyboard()
        )

    except Exception:
        pass


# =========================================================
# HUNT FUNCTION
# =========================================================

def hunt(message):

    try:

        bot.send_message(

            message.chat.id,

            "🔎 در حال اسکن Meme Coinهای Solana..."
        )

        candidates = scan_market()

        if not candidates:

            bot.send_message(

                message.chat.id,

                "🦈 فعلاً مورد مناسبی پیدا نشد."
            )

            return

        text = (
            "🦈 TOP MEME HUNTS V9.1\n\n"
        )

        for index, (
            score,
            info
        ) in enumerate(
            candidates[:5],
            1
        ):

            qualified = qualifies(
                info,
                score
            )

            text += (

                f"#{index} 🪙 "
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

                f"🟢 Buy Pressure: "
                f"{info['buy_pressure']*100:.0f}%\n"

                f"{'🎯 QUALIFIED' if qualified else '👀 WATCHING'}\n\n"
            )

        bot.send_message(

            message.chat.id,

            text
        )

    except Exception as e:

        bot.send_message(

            message.chat.id,

            f"❌ خطا در اسکن:\n{e}"
        )


# =========================================================
# SCAN MARKET
# =========================================================

def scan_market():

    try:

        pools = get_new_pools()

    except Exception as e:

        print(
            "Scan error:",
            e
        )

        return []

    candidates = []

    for pool in pools:

        try:

            info = parse_pool(
                pool
            )

            if not meme_filter(
                info
            ):
                continue

            score = calculate_score(
                info
            )

            if score >= 30:

                candidates.append(
                    (
                        score,
                        info
                    )
                )

        except Exception as e:

            print(
                "Candidate error:",
                e
            )

    candidates.sort(
        key=lambda x: x[0],
        reverse=True
    )

    return candidates[:10]


# =========================================================
# MONITOR POSITIONS
# =========================================================

def monitor_positions():

    daily_reset()

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

            entry = float(
                position["entry"]
            )

            change = (
                price - entry
            ) / entry

            tp = (
                state["settings"]
                ["take_profit"]
                / 100
            )

            sl = -(
                state["settings"]
                ["stop_loss"]
                / 100
            )

            if change >= tp:

                pnl = close_position(

                    address,

                    price,

                    "TP"
                )

                notify(

                    "🎯 TAKE PROFIT\n\n"

                    f"🪙 {position['name']}\n"

                    f"📈 Change: "
                    f"{change*100:+.2f}%\n"

                    f"💰 PnL: "
                    f"${pnl:+.4f}"
                )

            elif change <= sl:

                pnl = close_position(

                    address,

                    price,

                    "SL"
                )

                notify(

                    "🛑 STOP LOSS\n\n"

                    f"🪙 {position['name']}\n"

                    f"📉 Change: "
                    f"{change*100:+.2f}%\n"

                    f"💰 PnL: "
                    f"${pnl:+.4f}"
                )

        except Exception as e:

            print(
                "Monitor error:",
                e
            )


# =========================================================
# NOTIFY
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
# AUTO HUNTER
# =========================================================

def auto_loop():

    print(
        "🦈 MEME HUNTER V9.1 AUTO LOOP STARTED"
    )

    while True:

        try:

            daily_reset()

            s = state["settings"]

            if (
                s["auto_hunter"]
                and
                not s["emergency_stop"]
            ):

                monitor_positions()

                if s["paper_trading"]:

                    candidates = (
                        scan_market()
                    )

                    for (
                        score,
                        info
                    ) in candidates:

                        if paper_buy(
                            info,
                            score
                        ):

                            notify(

                                "🚨 🦈 AUTO PAPER BUY\n\n"

                                f"🪙 {info['name']}\n"

                                f"⭐ Score: "
                                f"{score}/100\n"

                                f"💵 Price: "
                                f"${info['price']:.10f}\n"

                                f"💧 Liquidity: "
                                f"${info['liquidity']:,.2f}\n"

                                f"🟢 Buy Pressure: "
                                f"{info['buy_pressure']*100:.0f}%\n"

                                f"💵 Size: "
                                f"${s['trade_size']:.2f}"
                            )

        except Exception as e:

            print(
                "Auto error:",
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
    "🦈 MEME HUNTER V9.1 RUNNING..."
)

bot.infinity_polling(
    skip_pending=True
    )
