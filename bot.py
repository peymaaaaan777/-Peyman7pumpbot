import os
import time
import json
import threading
import requests
import telebot
from telebot import types

# =========================================================
# 🦈 MEME HUNTER V7
# =========================================================

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise ValueError("❌ BOT_TOKEN پیدا نشد")

bot = telebot.TeleBot(TOKEN)

# =========================================================
# API
# =========================================================

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

SOL_MINT = (
    "So11111111111111111111111111111111111111112"
)

# =========================================================
# DEFAULT SETTINGS
# =========================================================

DEFAULT_SETTINGS = {

    "min_score": 70,

    "min_buy_pressure": 60,

    "min_liquidity": 5000,

    "min_m5_volume": 1000,

    "trade_size": 0.50,

    "take_profit": 20,

    "stop_loss": 10,

    "max_open": 3,

    "auto_hunter": True,

    "paper_trading": True,

    "real_trading": False
}

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
            **result.get(
                "settings",
                {}
            )
        }

        return result

    except Exception as e:

        print(
            "❌ State load error:",
            e
        )

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

        print(
            "❌ State save error:",
            e
        )


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
# GECKO TERMINAL
# =========================================================

def get_new_pools():

    headers = {

        "Accept":
        "application/json;version=20230203"
    }

    data = get_json(

        NEW_POOLS_API,

        headers=headers
    )

    return data.get(
        "data",
        []
    )


def get_pool(address):

    try:

        headers = {

            "Accept":
            "application/json;version=20230203"
        }

        data = get_json(

            POOL_API + address,

            headers=headers
        )

        return data.get("data")

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
# PARSE POOL
# =========================================================

def parse_pool(pool):

    attrs = pool.get(
        "attributes",
        {}
    )

    relationships = pool.get(
        "relationships",
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

    volume = attrs.get(
        "volume_usd",
        {}
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

    if total > 0:

        buy_pressure = (
            buys / total
        )

    else:

        buy_pressure = 0

    # -----------------------------------------------------
    # Base token mint
    # -----------------------------------------------------

    base_token = (
        relationships
        .get("base_token", {})
        .get("data", {})
    )

    base_id = base_token.get(
        "id",
        ""
    )

    if base_id.startswith(
        "solana_"
    ):

        token_mint = base_id.replace(
            "solana_",
            "",
            1
        )

    else:

        token_mint = base_id

    # -----------------------------------------------------
    # Pool address
    # -----------------------------------------------------

    pool_address = attrs.get(
        "address",
        ""
    )

    return {

        "pool_address":
        pool_address,

        "token_mint":
        token_mint,

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

        "total_tx":
        total,

        "buy_pressure":
        buy_pressure
    }


# =========================================================
# MEME FILTER
# =========================================================

def is_stable_pair(name):

    upper = name.upper()

    blocked = [

        "USDC",

        "USDT",

        "DAI",

        "USD1",

        "USDE",

        "WSOL"
    ]

    for word in blocked:

        if word in upper:

            return True

    return False


def is_probable_meme(info):

    name = info["name"].upper()

    blocked_words = [

        "USDC",

        "USDT",

        "DAI",

        "USD1",

        "USDE",

        "WSOL",

        "WETH",

        "WBTC"
    ]

    for word in blocked_words:

        if word in name:

            return False

    return True


# =========================================================
# SCORE V7
# =========================================================

def calculate_score(info):

    score = 0

    volume = info["m5_volume"]

    liquidity = info["liquidity"]

    pressure = info["buy_pressure"]

    total = info["total_tx"]

    fdv = info["fdv"]

    # -----------------------------------------------------
    # M5 VOLUME - 25
    # -----------------------------------------------------

    if volume >= 50000:

        score += 25

    elif volume >= 20000:

        score += 23

    elif volume >= 10000:

        score += 21

    elif volume >= 5000:

        score += 18

    elif volume >= 2500:

        score += 14

    elif volume >= 1000:

        score += 10

    elif volume >= 500:

        score += 5

    # -----------------------------------------------------
    # LIQUIDITY - 25
    # -----------------------------------------------------

    if liquidity >= 50000:

        score += 25

    elif liquidity >= 25000:

        score += 23

    elif liquidity >= 15000:

        score += 20

    elif liquidity >= 10000:

        score += 17

    elif liquidity >= 5000:

        score += 12

    elif liquidity >= 2500:

        score += 7

    elif liquidity >= 1000:

        score += 3

    # -----------------------------------------------------
    # TRANSACTIONS - 20
    # -----------------------------------------------------

    if total >= 500:

        score += 20

    elif total >= 300:

        score += 18

    elif total >= 200:

        score += 16

    elif total >= 100:

        score += 13

    elif total >= 50:

        score += 9

    elif total >= 25:

        score += 5

    elif total >= 10:

        score += 2

    # -----------------------------------------------------
    # BUY PRESSURE - 25
    # -----------------------------------------------------

    if pressure >= 0.90:

        score += 25

    elif pressure >= 0.80:

        score += 23

    elif pressure >= 0.70:

        score += 20

    elif pressure >= 0.65:

        score += 16

    elif pressure >= 0.60:

        score += 12

    elif pressure >= 0.55:

        score += 6

    # -----------------------------------------------------
    # FDV QUALITY - 5
    # -----------------------------------------------------

    if fdv > 0:

        if 10000 <= fdv <= 5000000:

            score += 5

        elif 5000 <= fdv <= 10000000:

            score += 3

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

    s = state["settings"]

    address = info["pool_address"]

    if not address:

        return False

    if address in state[
        "open_positions"
    ]:

        return False

    if not qualifies(
        info,
        score
    ):

        return False

    if (
        len(
            state["open_positions"]
        )
        >=
        s["max_open"]
    ):

        return False

    size = min(

        s["trade_size"],

        state["balance"]
    )

    if size <= 0:

        return False

    state["balance"] -= size

    state[
        "open_positions"
    ][address] = {

        "name":
        info["name"],

        "pool_address":
        address,

        "token_mint":
        info["token_mint"],

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

    positions = state[
        "open_positions"
    ]

    if address not in positions:

        return None

    position = positions[
        address
    ]

    entry = position[
        "entry"
    ]

    size = position[
        "size"
    ]

    if entry <= 0:

        return None

    # Calculate REAL price-based PnL

    price_change = (
        price - entry
    ) / entry

    pnl = (
        size
        * price_change
    )

    state["balance"] += (
        size + pnl
    )

    state["trades"].append({

        "name":
        position["name"],

        "entry":
        entry,

        "exit":
        price,

        "size":
        size,

        "pnl":
        pnl,

        "result":
        reason,

        "score":
        position["score"],

        "opened":
        position["opened"],

        "closed":
        time.time()
    })

    del positions[
        address
    ]

    save_state()

    return pnl


# =========================================================
# MONITOR POSITIONS
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

            price = info[
                "price"
            ]

            if price <= 0:

                continue

            position = (
                state[
                    "open_positions"
                ].get(address)
            )

            if not position:

                continue

            entry = position[
                "entry"
            ]

            s = state[
                "settings"
            ]

            tp_price = (
                entry
                *
                (
                    1
                    +
                    s["take_profit"]
                    / 100
                )
            )

            sl_price = (
                entry
                *
                (
                    1
                    -
                    s["stop_loss"]
                    / 100
                )
            )

            if price >= tp_price:

                pnl = close_position(

                    address,

                    price,

                    "TP"
                )

                notify(

                    "🎯 PAPER TAKE PROFIT\n\n"

                    f"🪙 {position['name']}\n"

                    f"💵 Entry: "
                    f"${entry:.10f}\n"

                    f"💵 Exit: "
                    f"${price:.10f}\n"

                    f"💰 PnL: "
                    f"${pnl:+.4f}"
                )

            elif price <= sl_price:

                pnl = close_position(

                    address,

                    price,

                    "SL"
                )

                notify(

                    "🛑 PAPER STOP LOSS\n\n"

                    f"🪙 {position['name']}\n"

                    f"💵 Entry: "
                    f"${entry:.10f}\n"

                    f"💵 Exit: "
                    f"${price:.10f}\n"

                    f"💰 PnL: "
                    f"${pnl:+.4f}"
                )

        except Exception as e:

            print(
                "Monitor error:",
                e
            )


# =========================================================
# MARKET SCANNER
# =========================================================

def scan_market():

    pools = get_new_pools()

    candidates = []

    seen = set()

    for pool in pools:

        try:

            info = parse_pool(
                pool
            )

            address = info[
                "pool_address"
            ]

            if not address:

                continue

            if address in seen:

                continue

            seen.add(address)

            if is_stable_pair(
                info["name"]
            ):

                continue

            if not is_probable_meme(
                info
            ):

                continue

            if info["price"] <= 0:

                continue

            score = calculate_score(
                info
            )

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
                opened
            })

        except Exception as e:

            print(
                "Scanner error:",
                e
            )

    candidates.sort(

        key=lambda x:
        x["score"],

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
            "Telegram notify error:",
            e
        )


# =========================================================
# SETTINGS TEXT
# =========================================================

def settings_text():

    s = state[
        "settings"
    ]

    return (

        "⚙️ تنظیمات MEME HUNTER V7\n\n"

        f"⭐ حداقل Score: "
        f"{s['min_score']}\n"

        f"🟢 حداقل Buy Pressure: "
        f"{s['min_buy_pressure']}%\n"

        f"💧 حداقل Liquidity: "
        f"${s['min_liquidity']:,.0f}\n"

        f"📊 حداقل M5 Volume: "
        f"${s['min_m5_volume']:,.0f}\n\n"

        f"💵 حجم هر معامله: "
        f"${s['trade_size']:.2f}\n"

        f"🎯 Take Profit: "
        f"{s['take_profit']}%\n"

        f"🛑 Stop Loss: "
        f"{s['stop_loss']}%\n"

        f"📂 حداکثر پوزیشن: "
        f"{s['max_open']}\n\n"

        f"🦈 Auto Hunter: "
        f"{'🟢 روشن' if s['auto_hunter'] else '🔴 خاموش'}\n"

        f"🧪 Paper Trading: "
        f"{'🟢 روشن' if s['paper_trading'] else '🔴 خاموش'}\n\n"

        "💰 Real Trading: 🔒 قفل\n\n"

        "⚠️ این نسخه برای تست و Paper Trading است."
    )


# =========================================================
# SETTINGS KEYBOARD
# =========================================================

def settings_keyboard():

    keyboard = (
        types.InlineKeyboardMarkup()
    )

    keyboard.row(

        types.InlineKeyboardButton(
            "⭐ Score -",
            callback_data="score_minus"
        ),

        types.InlineKeyboardButton(
            "⭐ Score +",
            callback_data="score_plus"
        )
    )

    keyboard.row(

        types.InlineKeyboardButton(
            "🟢 Buy% -",
            callback_data="buy_minus"
        ),

        types.InlineKeyboardButton(
            "🟢 Buy% +",
            callback_data="buy_plus"
        )
    )

    keyboard.row(

        types.InlineKeyboardButton(
            "💧 Liquidity -",
            callback_data="liq_minus"
        ),

        types.InlineKeyboardButton(
            "💧 Liquidity +",
            callback_data="liq_plus"
        )
    )

    keyboard.row(

        types.InlineKeyboardButton(
            "📊 Volume -",
            callback_data="vol_minus"
        ),

        types.InlineKeyboardButton(
            "📊 Volume +",
            callback_data="vol_plus"
        )
    )

    keyboard.row(

        types.InlineKeyboardButton(
            "💵 مبلغ -",
            callback_data="size_minus"
        ),

        types.InlineKeyboardButton(
            "💵 مبلغ +",
            callback_data="size_plus"
        )
    )

    keyboard.row(

        types.InlineKeyboardButton(
            "🎯 TP -",
            callback_data="tp_minus"
        ),

        types.InlineKeyboardButton(
            "🎯 TP +",
            callback_data="tp_plus"
        )
    )

    keyboard.row(

        types.InlineKeyboardButton(
            "🛑 SL -",
            callback_data="sl_minus"
        ),

        types.InlineKeyboardButton(
            "🛑 SL +",
            callback_data="sl_plus"
        )
    )

    keyboard.row(

        types.InlineKeyboardButton(
            "🦈 Auto ON/OFF",
            callback_data="auto"
        ),

        types.InlineKeyboardButton(
            "🧪 Paper ON/OFF",
            callback_data="paper"
        )
    )

    keyboard.row(

        types.InlineKeyboardButton(
            "📊 وضعیت",
            callback_data="status"
        ),

        types.InlineKeyboardButton(
            "🦈 Hunt",
            callback_data="hunt"
        )
    )

    keyboard.row(

        types.InlineKeyboardButton(
            "💰 Real Trading 🔒",
            callback_data="real"
        )
    )

    return keyboard


# =========================================================
# START MENU
# =========================================================

def main_keyboard():

    keyboard = (
        types.InlineKeyboardMarkup()
    )

    keyboard.row(

        types.InlineKeyboardButton(
            "🦈 شکار میم‌کوین",
            callback_data="hunt"
        )
    )

    keyboard.row(

        types.InlineKeyboardButton(
            "⚙️ تنظیمات",
            callback_data="settings"
        ),

        types.InlineKeyboardButton(
            "📊 Paper",
            callback_data="status"
        )
    )

    keyboard.row(

        types.InlineKeyboardButton(
            "📡 وضعیت ربات",
            callback_data="status"
        )
    )

    return keyboard


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

        "🦈 MEME HUNTER V7\n\n"

        "ربات آماده است.\n\n"

        "🎯 سیستم شکار برای میم‌کوین‌های سولانا\n"

        "💧 فیلتر Liquidity\n"

        "📊 فیلتر M5 Volume\n"

        "🟢 Buy Pressure\n"

        "⭐ Smart Score\n"

        "🧪 Paper Trading\n"

        "🎯 Take Profit\n"

        "🛑 Stop Loss\n\n"

        "💰 Real Trading: 🔒 قفل",

        reply_markup=main_keyboard()
    )


# =========================================================
# /SETTINGS
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
# /STATUS
# =========================================================

@bot.message_handler(
    commands=["status"]
)
def status_command(message):

    state["chat_id"] = (
        message.chat.id
    )

    save_state()

    send_status(
        message.chat.id
    )


def send_status(chat_id):

    s = state[
        "settings"
    ]

    pnl = sum(

        trade.get(
            "pnl",
            0
        )

        for trade in state[
            "trades"
        ]
    )

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
        f"${state['balance']:.4f}\n"

        f"📂 Open Positions: "
        f"{len(state['open_positions'])}\n"

        f"🔢 Closed Trades: "
        f"{len(state['trades'])}\n"

        f"💰 Total PnL: "
        f"${pnl:+.4f}"
    )


# =========================================================
# /PAPER
# =========================================================

@bot.message_handler(
    commands=["paper"]
)
def paper_command(message):

    trades = state[
        "trades"
    ]

    wins = sum(

        1

        for trade in trades

        if trade.get(
            "pnl",
            0
        ) > 0
    )

    losses = sum(

        1

        for trade in trades

        if trade.get(
            "pnl",
            0
        ) < 0
    )

    total = len(
        trades
    )

    pnl = sum(

        trade.get(
            "pnl",
            0
        )

        for trade in trades
    )

    win_rate = (

        wins / total * 100

        if total

        else 0
    )

    bot.send_message(

        message.chat.id,

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
# /HUNT
# =========================================================

@bot.message_handler(
    commands=["hunt"]
)
def hunt_command(message):

    state["chat_id"] = (
        message.chat.id
    )

    save_state()

    perform_hunt(
        message.chat.id
    )


def perform_hunt(chat_id):

    bot.send_message(

        chat_id,

        "🔎 در حال اسکن میم‌کوین‌های جدید سولانا...\n"
        "⏳ لطفاً چند ثانیه صبر کن."
    )

    try:

        candidates = scan_market()

        if not candidates:

            bot.send_message(

                chat_id,

                "🔎 فعلاً کاندید مناسبی پیدا نشد."
            )

            return

        text = (
            "🦈 TOP MEME HUNTS V7\n\n"
        )

        for index, item in enumerate(

            candidates,

            1
        ):

            score = item[
                "score"
            ]

            info = item[
                "info"
            ]

            opened = item[
                "opened"
            ]

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

                f"🟢 Buy pressure: "
                f"{info['buy_pressure']*100:.0f}%\n"
            )

            if opened:

                text += (
                    "🧪 PAPER BUY: OPEN\n"
                )

            elif qualified:

                text += (
                    "🎯 QUALIFIED\n"
                )

            else:

                text += (
                    "👀 WATCHING\n"
                )

            text += "\n"

        s = state[
            "settings"
        ]

        text += (

            "⚙️ FILTERS\n"

            f"⭐ Min Score: "
            f"{s['min_score']}\n"

            f"🟢 Min Buy Pressure: "
            f"{s['min_buy_pressure']}%\n"

            f"💧 Min Liquidity: "
            f"${s['min_liquidity']:,.0f}\n"

            f"📊 Min M5 Volume: "
            f"${s['min_m5_volume']:,.0f}\n\n"

            f"🧪 Paper Trading: "
            f"{'ON' if s['paper_trading'] else 'OFF'}\n"

            "💰 Real Trading: 🔒 LOCKED"
        )

        bot.send_message(

            chat_id,

            text
        )

    except Exception as e:

        bot.send_message(

            chat_id,

            "❌ خطا در اسکن:\n\n"
            f"{e}"
        )


# =========================================================
# CALLBACKS
# =========================================================

@bot.callback_query_handler(
    func=lambda call: True
)
def callbacks(call):

    data = call.data

    s = state[
        "settings"
    ]

    try:

        # -------------------------------------------------
        # SETTINGS
        # -------------------------------------------------

        if data == "settings":

            bot.answer_callback_query(
                call.id
            )

            bot.edit_message_text(

                settings_text(),

                call.message.chat.id,

                call.message.message_id,

                reply_markup=
                settings_keyboard()
            )

            return

        # -------------------------------------------------
        # HUNT
        # -------------------------------------------------

        if data == "hunt":

            bot.answer_callback_query(

                call.id,

                "🔎 در حال اسکن..."
            )

            perform_hunt(
                call.message.chat.id
            )

            return

        # -------------------------------------------------
        # STATUS
        # -------------------------------------------------

        if data == "status":

            bot.answer_callback_query(
                call.id
            )

            send_status(
                call.message.chat.id
            )

            return

        # -------------------------------------------------
        # SCORE
        # -------------------------------------------------

        if data == "score_minus":

            s["min_score"] = max(

                40,

                s["min_score"] - 5
            )

        elif data == "score_plus":

            s["min_score"] = min(

                100,

                s["min_score"] + 5
            )

        # -------------------------------------------------
        # BUY PRESSURE
        # -------------------------------------------------

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

        # -------------------------------------------------
        # LIQUIDITY
        # -------------------------------------------------

        elif data == "liq_minus":

            s["min_liquidity"] = max(

                1000,

                s["min_liquidity"] - 1000
            )

        elif data == "liq_plus":

            s["min_liquidity"] = min(

                100000,

                s["min_liquidity"] + 1000
            )

        # -------------------------------------------------
        # VOLUME
        # -------------------------------------------------

        elif data == "vol_minus":

            s["min_m5_volume"] = max(

                100,

                s["min_m5_volume"] - 500
            )

        elif data == "vol_plus":

            s["min_m5_volume"] = min(

                100000,

                s["min_m5_volume"] + 500
            )

        # -------------------------------------------------
        # TRADE SIZE
        # -------------------------------------------------

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

        # -------------------------------------------------
        # TP
        # -------------------------------------------------

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

        # -------------------------------------------------
        # SL
        # -------------------------------------------------

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

        # -------------------------------------------------
        # AUTO
        # -------------------------------------------------

        elif data == "auto":

            s["auto_hunter"] = not (
                s["auto_hunter"]
            )

        # -------------------------------------------------
        # PAPER
        # -------------------------------------------------

        elif data == "paper":

            s["paper_trading"] = not (
                s["paper_trading"]
            )

        # -------------------------------------------------
        # REAL
        # -------------------------------------------------

        elif data == "real":

            bot.answer_callback_query(

                call.id,

                "🔒 Real Trading در این نسخه قفل است. "
                "هیچ معامله واقعی انجام نمی‌شود.",

                show_alert=True
            )

            return

        else:

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

            reply_markup=
            settings_keyboard()
        )

    except Exception as e:

        print(
            "Callback error:",
            e
        )


# =========================================================
# AUTO HUNTER
# =========================================================

def auto_loop():

    print(
        "🦈 Auto Hunter V7 started"
    )

    while True:

        try:

            s = state[
                "settings"
            ]

            if s["auto_hunter"]:

                # First monitor existing positions

                if state[
                    "open_positions"
                ]:

                    monitor_positions()

                # Then scan

                candidates = scan_market()

                for item in candidates:

                    if item["opened"]:

                        info = item[
                            "info"
                        ]

                        notify(

                            "🚨 🦈 AUTO PAPER BUY\n\n"

                            f"🪙 {info['name']}\n"

                            f"⭐ Score: "
                            f"{item['score']}/100\n"

                            f"💵 Price: "
                            f"${info['price']:.10f}\n"

                            f"💧 Liquidity: "
                            f"${info['liquidity']:,.2f}\n"

                            f"📊 M5 Volume: "
                            f"${info['m5_volume']:,.2f}\n"

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
    "🦈 MEME HUNTER V7 RUNNING..."
)

bot.infinity_polling()
