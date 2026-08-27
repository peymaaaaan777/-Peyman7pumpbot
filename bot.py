import os
import json
import time
import threading
import requests
import telebot
from telebot import types

# =========================================================
# MEME HUNTER V9
# Auto Meme Scanner + Paper Trading + Telegram Control
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
JUPITER_API_KEY = os.getenv("JUPITER_API_KEY")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN تنظیم نشده")

bot = telebot.TeleBot(BOT_TOKEN)

STATE_FILE = "bot_state.json"

START_BALANCE = 5.0
SCAN_INTERVAL = 180

SOL_MINT = "So11111111111111111111111111111111111111112"

NEW_POOLS_API = (
    "https://api.geckoterminal.com/api/v2/"
    "networks/solana/new_pools"
)

POOL_API = (
    "https://api.geckoterminal.com/api/v2/"
    "networks/solana/pools/"
)

JUPITER_ORDER_API = "https://api.jup.ag/swap/v2/order"


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

        print("State save error:", e)


# =========================================================
# DAILY RESET
# =========================================================

def daily_reset():

    today = time.strftime("%Y-%m-%d")

    if state.get("daily_date") != today:

        state["daily_date"] = today

        state["daily_pnl"] = 0.0

        save_state()


# =========================================================
# HTTP
# =========================================================

def get_json(
    url,
    headers=None,
    params=None
):

    response = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=20
    )

    response.raise_for_status()

    return response.json()


# =========================================================
# GECKO
# =========================================================

def get_new_pools():

    headers = {
        "Accept": "application/json"
    }

    data = get_json(
        NEW_POOLS_API,
        headers=headers
    )

    return data.get("data", [])


def get_pool(address):

    try:

        headers = {
            "Accept": "application/json"
        }

        data = get_json(
            POOL_API + address,
            headers=headers
        )

        return data.get("data")

    except Exception as e:

        print("Pool error:", e)

        return None


# =========================================================
# HELPERS
# =========================================================

def number(value):

    try:
        return float(value or 0)

    except Exception:
        return 0.0


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

        "buys": buys,

        "sells": sells,

        "buy_pressure":
        pressure
    }


# =========================================================
# MEME FILTER
# =========================================================

def meme_filter(info):

    name = (
        info["name"]
        .upper()
    )

    blocked = [
        "USDC",
        "USDT",
        "USDE",
        "DAI",
        "USD",
        "WSOL"
    ]

    for item in blocked:

        if item in name:

            return False

    if info["liquidity"] <= 0:
        return False

    if info["price"] <= 0:
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

    fdv = info["fdv"]

    # -----------------------------------------------------
    # VOLUME
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # LIQUIDITY
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # TRANSACTIONS
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # BUY PRESSURE
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # FDV
    # -----------------------------------------------------

    if fdv > 0:

        if fdv <= 100000:
            score += 10

        elif fdv <= 500000:
            score += 7

        elif fdv <= 1000000:
            score += 4

    return min(
        score,
        100
    )


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

    address = info["address"]

    if not address:
        return False

    if state["emergency_stop"] if "emergency_stop" in state else False:
        return False

    if s["emergency_stop"]:
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

    max_daily_loss = (
        state["initial_balance"]
        *
        s["daily_loss_limit"]
        / 100
    )

    if (
        state["daily_pnl"]
        <= -max_daily_loss
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
# PAPER CLOSE
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

    actual_change = (
        price - entry
    ) / entry

    pnl = (
        position["size"]
        *
        actual_change
    )

    state["balance"] += (
        position["size"]
        +
        pnl
    )

    state["daily_pnl"] += pnl

    state["trades"].append({

        "name":
        position["name"],

        "entry":
        entry,

        "exit":
        price,

        "size":
        position["size"],

        "pnl":
        pnl,

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

            entry = position["entry"]

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
# SCANNER
# =========================================================

def scan_market():

    try:

        pools = get_new_pools()

    except Exception as e:

        print(
            "Market scan error:",
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
                "Scanner item error:",
                e
            )

    candidates.sort(
        key=lambda x: x[0],
        reverse=True
    )

    return candidates[:10]


# =========================================================
# JUPITER QUOTE TEST
# =========================================================

def jupiter_test(
    token_address
):

    if not JUPITER_API_KEY:

        return {
            "ok": False,
            "error":
            "JUPITER_API_KEY تنظیم نشده"
        }

    amount = int(
        state["settings"]
        ["trade_size"]
        *
        1_000_000_000
    )

    params = {

        "inputMint":
        SOL_MINT,

        "outputMint":
        token_address,

        "amount":
        str(amount)
    }

    headers = {

        "x-api-key":
        JUPITER_API_KEY
    }

    try:

        response = requests.get(

            JUPITER_ORDER_API,

            params=params,

            headers=headers,

            timeout=20
        )

        response.raise_for_status()

        return {
            "ok": True,
            "data":
            response.json()
        }

    except Exception as e:

        return {
            "ok": False,
            "error":
            str(e)
        }


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
            "Telegram notify error:",
            e
        )


# =========================================================
# SETTINGS TEXT
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
        f"${s['min_m5_volume']:,.0f}\n\n"

        f"💵 حجم معامله: "
        f"${s['trade_size']:.2f}\n"

        f"🎯 Take Profit: "
        f"{s['take_profit']}%\n"

        f"🛑 Stop Loss: "
        f"{s['stop_loss']}%\n"

        f"📂 Max Open: "
        f"{s['max_open']}\n"

        f"🚨 Daily Loss Limit: "
        f"{s['daily_loss_limit']}%\n\n"

        f"🦈 Auto Hunter: "
        f"{'🟢 روشن' if s['auto_hunter'] else '🔴 خاموش'}\n"

        f"🧪 Paper Trading: "
        f"{'🟢 روشن' if s['paper_trading'] else '🔴 خاموش'}\n\n"

        f"🚨 Emergency Stop: "
        f"{'🔴 فعال' if s['emergency_stop'] else '🟢 خاموش'}\n\n"

        "💰 Real Trading: 🔒 تأیید دستی"
    )


# =========================================================
# SETTINGS KEYBOARD
# =========================================================

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
            "💵 مبلغ −",
            callback_data="size_minus"
        ),

        types.InlineKeyboardButton(
            "💵 مبلغ +",
            callback_data="size_plus"
        )
    )

    k.row(

        types.InlineKeyboardButton(
            "💧 Liquidity −",
            callback_data="liq_minus"
        ),

        types.InlineKeyboardButton(
            "💧 Liquidity +",
            callback_data="liq_plus"
        )
    )

    k.row(

        types.InlineKeyboardButton(
            "📊 Volume −",
            callback_data="vol_minus"
        ),

        types.InlineKeyboardButton(
            "📊 Volume +",
            callback_data="vol_plus"
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
            "📂 Max Open −",
            callback_data="open_minus"
        ),

        types.InlineKeyboardButton(
            "📂 Max Open +",
            callback_data="open_plus"
        )
    )

    k.row(

        types.InlineKeyboardButton(
            "🚨 Daily Loss −",
            callback_data="loss_minus"
        ),

        types.InlineKeyboardButton(
            "🚨 Daily Loss +",
            callback_data="loss_plus"
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
            callback_data="paper"
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
            "🪐 Jupiter Test",
            callback_data="jupiter"
        )
    )

    return k


# =========================================================
# START
# =========================================================

@bot.message_handler(
    commands=["start"]
)
def start(message):

    state["chat_id"] = (
        message.chat.id
    )

    save_state()

    keyboard = types.InlineKeyboardMarkup()

    keyboard.row(

        types.InlineKeyboardButton(
            "🦈 Hunt",
            callback_data="menu_hunt"
        ),

        types.InlineKeyboardButton(
            "⚙️ Settings",
            callback_data="menu_settings"
        )
    )

    keyboard.row(

        types.InlineKeyboardButton(
            "📊 Paper",
            callback_data="menu_paper"
        ),

        types.InlineKeyboardButton(
            "📡 Status",
            callback_data="menu_status"
        )
    )

    bot.send_message(

        message.chat.id,

        "🦈 MEME HUNTER V9\n\n"

        "ربات آماده است.\n\n"

        "🧪 Paper Trading فعال است.\n"

        "💰 Real Trading با تأیید دستی انجام می‌شود.\n\n"

        "از منوی زیر کنترلش کن:",

        reply_markup=keyboard
    )


# =========================================================
# SETTINGS
# =========================================================

@bot.message_handler(
    commands=["settings"]
)
def settings_command(message):

    state["chat_id"] = (
        message.chat.id
    )

    save_state()

    bot.send_message(

        message.chat.id,

        settings_text(),

        reply_markup=
        settings_keyboard()
    )


# =========================================================
# STATUS
# =========================================================

@bot.message_handler(
    commands=["status"]
)
def status_command(message):

    daily_reset()

    s = state["settings"]

    bot.reply_to(

        message,

        "📡 MEME HUNTER STATUS\n\n"

        "🟢 Online\n\n"

        f"💵 Balance: "
        f"${state['balance']:.4f}\n"

        f"📂 Open: "
        f"{len(state['open_positions'])}\n"

        f"🔢 Closed: "
        f"{len(state['trades'])}\n"

        f"💰 Daily PnL: "
        f"${state['daily_pnl']:+.4f}\n\n"

        f"🦈 Auto: "
        f"{'ON' if s['auto_hunter'] else 'OFF'}\n"

        f"🧪 Paper: "
        f"{'ON' if s['paper_trading'] else 'OFF'}\n"

        f"🚨 Emergency: "
        f"{'ON' if s['emergency_stop'] else 'OFF'}"
    )


# =========================================================
# PAPER STATS
# =========================================================

@bot.message_handler(
    commands=["paper"]
)
def paper_command(message):

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

    bot.reply_to(

        message,

        "🧪 PAPER TRADING\n\n"

        f"💵 Balance: "
        f"${state['balance']:.4f}\n"

        f"📂 Open: "
        f"{len(state['open_positions'])}\n"

        f"🔢 Closed: "
        f"{total}\n"

        f"✅ Wins: "
        f"{wins}\n"

        f"❌ Losses: "
        f"{losses}\n"

        f"🎯 Win Rate: "
        f"{win_rate:.1f}%\n"

        f"💰 PnL: "
        f"${pnl:+.4f}"
    )


# =========================================================
# HUNT
# =========================================================

@bot.message_handler(
    commands=["hunt"]
)
def hunt_command(message):

    state["chat_id"] = (
        message.chat.id
    )

    save_state()

    bot.send_message(

        message.chat.id,

        "🔎 در حال اسکن Meme Coinهای Solana..."
    )

    candidates = scan_market()

    if not candidates:

        bot.send_message(

            message.chat.id,

            "🦈 فعلاً کاندید مناسبی پیدا نشد."
        )

        return

    text = (
        "🦈 TOP MEME HUNTS V9\n\n"
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

    text += (

        "⚙️ FILTERS\n"

        f"⭐ Score ≥ "
        f"{state['settings']['min_score']}\n"

        f"🟢 Buy Pressure ≥ "
        f"{state['settings']['min_buy_pressure']}%\n"

        f"💧 Liquidity ≥ "
        f"${state['settings']['min_liquidity']:,.0f}\n"

        f"📊 M5 Volume ≥ "
        f"${state['settings']['min_m5_volume']:,.0f}\n\n"

        "🧪 Paper Trading: "
        f"{'ON' if state['settings']['paper_trading'] else 'OFF'}"
    )

    bot.send_message(
        message.chat.id,
        text
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

    # -----------------------------------------------------
    # MENU
    # -----------------------------------------------------

    if data == "menu_settings":

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

    if data == "menu_hunt":

        bot.answer_callback_query(
            call.id
        )

        bot.send_message(

            call.message.chat.id,

            "🔎 برای اسکن، دستور /hunt را بزن."
        )

        return

    if data == "menu_paper":

        bot.answer_callback_query(
            call.id
        )

        paper_command(
            call.message
        )

        return

    if data == "menu_status":

        bot.answer_callback_query(
            call.id
        )

        status_command(
            call.message
        )

        return

    # -----------------------------------------------------
    # SCORE
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # BUY PRESSURE
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # TRADE SIZE
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # LIQUIDITY
    # -----------------------------------------------------

    elif data == "liq_minus":

        s["min_liquidity"] = max(
            1000,
            s["min_liquidity"] - 1000
        )

    elif data == "liq_plus":

        s["min_liquidity"] += 1000

    # -----------------------------------------------------
    # VOLUME
    # -----------------------------------------------------

    elif data == "vol_minus":

        s["min_m5_volume"] = max(
            100,
            s["min_m5_volume"] - 100
        )

    elif data == "vol_plus":

        s["min_m5_volume"] += 100

    # -----------------------------------------------------
    # TP
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # SL
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # MAX OPEN
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # DAILY LOSS
    # -----------------------------------------------------

    elif data == "loss_minus":

        s["daily_loss_limit"] = max(
            1,
            s["daily_loss_limit"] - 1
        )

    elif data == "loss_plus":

        s["daily_loss_limit"] = min(
            50,
            s["daily_loss_limit"] + 1
        )

    # -----------------------------------------------------
    # AUTO
    # -----------------------------------------------------

    elif data == "auto":

        s["auto_hunter"] = (
            not s["auto_hunter"]
        )

    # -----------------------------------------------------
    # PAPER
    # -----------------------------------------------------

    elif data == "paper":

        s["paper_trading"] = (
            not s["paper_trading"]
        )

    # -----------------------------------------------------
    # EMERGENCY
    # -----------------------------------------------------

    elif data == "emergency":

        s["emergency_stop"] = True

        s["auto_hunter"] = False

        bot.answer_callback_query(

            call.id,

            "🚨 Emergency Stop فعال شد",

            show_alert=True
        )

        save_state()

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

    # -----------------------------------------------------
    # JUPITER
    # -----------------------------------------------------

    elif data == "jupiter":

        bot.answer_callback_query(

            call.id,

            "🪐 در حال تست Jupiter..."
        )

        candidates = scan_market()

        if not candidates:

            bot.send_message(

                call.message.chat.id,

                "❌ کاندید مناسبی پیدا نشد."
            )

            return

        score, info = candidates[0]

        result = jupiter_test(
            info["address"]
        )

        if not result["ok"]:

            bot.send_message(

                call.message.chat.id,

                "❌ Jupiter Test Failed\n\n"
                f"{result['error']}"
            )

            return

        bot.send_message(

            call.message.chat.id,

            "🪐 JUPITER TEST\n\n"

            f"🪙 {info['name']}\n"

            f"⭐ Score: "
            f"{score}/100\n\n"

            "✅ Quote دریافت شد.\n"

            "🧪 Paper Trading فعال است.\n"

            "💰 معامله واقعی بدون تأیید دستی انجام نمی‌شود."
        )

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

    except Exception as e:

        print(
            "Settings edit error:",
            e
        )


# =========================================================
# AUTO HUNTER
# =========================================================

def auto_loop():

    print(
        "🦈 MEME HUNTER V9 AUTO LOOP STARTED"
    )

    while True:

        try:

            daily_reset()

            s = state["settings"]

            if s["auto_hunter"]:

                if not s["emergency_stop"]:

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
                "Auto loop error:",
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
    "🦈 MEME HUNTER V9 RUNNING..."
)

bot.infinity_polling(
    skip_pending=True
)
