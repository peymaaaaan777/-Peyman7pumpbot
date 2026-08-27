import os
import time
import json
import threading
import requests
import telebot
from telebot import types

# =========================================================
# 🦈 MEME HUNTER V8
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

# =========================================================
# DEFAULT SETTINGS
# =========================================================

DEFAULT_SETTINGS = {

    "min_score": 60,

    "min_buy_pressure": 58,

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
            "State load error:",
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
            "Save error:",
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
# GECKO
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
            "Pool error:",
            e
        )

        return None


# =========================================================
# HELPERS
# =========================================================

def number(value):

    try:

        return float(
            value or 0
        )

    except:

        return 0.0


def safe_int(value):

    try:

        return int(
            value or 0
        )

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

    name = attrs.get(
        "name",
        "Unknown"
    )

    return {

        "address":
        attrs.get(
            "address",
            ""
        ),

        "name":
        name,

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

    blocked = [

        "USDC",

        "USDT",

        "WSOL",

        "SOL/USDC",

        "SOL/USDT"
    ]

    for word in blocked:

        if word in name:

            return False

    if info["liquidity"] <= 0:

        return False

    if info["price"] <= 0:

        return False

    return True


# =========================================================
# SCORE V8
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
    # VOLUME 0-25
    # -------------------------

    if volume >= 50000:

        score += 25

    elif volume >= 20000:

        score += 22

    elif volume >= 10000:

        score += 19

    elif volume >= 5000:

        score += 16

    elif volume >= 1000:

        score += 12

    elif volume >= 500:

        score += 7

    # -------------------------
    # LIQUIDITY 0-20
    # -------------------------

    if liquidity >= 50000:

        score += 20

    elif liquidity >= 20000:

        score += 18

    elif liquidity >= 10000:

        score += 15

    elif liquidity >= 5000:

        score += 12

    elif liquidity >= 2500:

        score += 6

    # -------------------------
    # PRESSURE 0-30
    # -------------------------

    if pressure >= 0.85:

        score += 30

    elif pressure >= 0.75:

        score += 26

    elif pressure >= 0.65:

        score += 21

    elif pressure >= 0.60:

        score += 16

    elif pressure >= 0.55:

        score += 10

    # -------------------------
    # TRANSACTIONS 0-15
    # -------------------------

    if total >= 500:

        score += 15

    elif total >= 250:

        score += 13

    elif total >= 100:

        score += 10

    elif total >= 50:

        score += 7

    elif total >= 20:

        score += 4

    # -------------------------
    # BUY/SELL QUALITY
    # -------------------------

    if buys > sells * 2:

        score += 5

    elif buys > sells:

        score += 3

    # -------------------------
    # LIQUIDITY SAFETY
    # -------------------------

    if liquidity < 2000:

        score -= 10

    if volume > 0 and liquidity > 0:

        ratio = volume / liquidity

        if ratio > 20:

            score -= 5

        elif ratio > 10:

            score -= 2

    return max(
        0,
        min(
            score,
            100
        )
    )


# =========================================================
# FILTER
# =========================================================

def passes_filters(
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
        s["min_volume"]
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

    address = info["address"]

    if not address:

        return False

    if address in state[
        "open_positions"
    ]:

        return False

    if not passes_filters(
        info,
        score
    ):

        return False

    if len(
        state["open_positions"]
    ) >= s["max_open"]:

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

    real_change = (

        price - entry
    ) / entry

    pnl = (
        size
        * real_change
    )

    state["balance"] += (

        size
        + pnl
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
# POSITION MONITOR
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
                ].get(
                    address
                )
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

                    "🎯 TAKE PROFIT\n\n"

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

                    "🛑 STOP LOSS\n\n"

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
# SCAN
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

            candidates.append({

                "score":
                score,

                "info":
                info
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

    return candidates[:10]


# =========================================================
# HUNT
# =========================================================

def run_hunt():

    candidates = scan_market()

    results = []

    for item in candidates:

        info = item[
            "info"
        ]

        score = item[
            "score"
        ]

        opened = False

        if (
            state["settings"]
            ["paper_trading"]
            and
            state["settings"]
            ["auto_hunter"]
        ):

            opened = paper_buy(
                info,
                score
            )

        results.append({

            "score":
            score,

            "info":
            info,

            "opened":
            opened
        })

    return results


# =========================================================
# TELEGRAM
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
# SETTINGS TEXT
# =========================================================

def settings_text():

    s = state[
        "settings"
    ]

    return (

        "⚙️ تنظیمات MEME HUNTER V8\n\n"

        f"⭐ حداقل Score: "
        f"{s['min_score']}\n"

        f"🟢 حداقل Buy Pressure: "
        f"{s['min_buy_pressure']}%\n"

        f"💧 حداقل Liquidity: "
        f"${s['min_liquidity']:,.0f}\n"

        f"📊 حداقل M5 Volume: "
        f"${s['min_volume']:,.0f}\n\n"

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

        "💰 Real Trading: 🔒 قفل"
    )


# =========================================================
# SETTINGS KEYBOARD
# =========================================================

def settings_keyboard():

    kb = types.InlineKeyboardMarkup()

    kb.row(

        types.InlineKeyboardButton(
            "⭐ Score −",
            callback_data="score_minus"
        ),

        types.InlineKeyboardButton(
            "⭐ Score +",
            callback_data="score_plus"
        )
    )

    kb.row(

        types.InlineKeyboardButton(
            "🟢 Buy% −",
            callback_data="buy_minus"
        ),

        types.InlineKeyboardButton(
            "🟢 Buy% +",
            callback_data="buy_plus"
        )
    )

    kb.row(

        types.InlineKeyboardButton(
            "💧 Liquidity −",
            callback_data="liq_minus"
        ),

        types.InlineKeyboardButton(
            "💧 Liquidity +",
            callback_data="liq_plus"
        )
    )

    kb.row(

        types.InlineKeyboardButton(
            "📊 Volume −",
            callback_data="vol_minus"
        ),

        types.InlineKeyboardButton(
            "📊 Volume +",
            callback_data="vol_plus"
        )
    )

    kb.row(

        types.InlineKeyboardButton(
            "💵 مبلغ −",
            callback_data="size_minus"
        ),

        types.InlineKeyboardButton(
            "💵 مبلغ +",
            callback_data="size_plus"
        )
    )

    kb.row(

        types.InlineKeyboardButton(
            "🎯 TP −",
            callback_data="tp_minus"
        ),

        types.InlineKeyboardButton(
            "🎯 TP +",
            callback_data="tp_plus"
        )
    )

    kb.row(

        types.InlineKeyboardButton(
            "🛑 SL −",
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
            "🔄 Reset Settings",
            callback_data="reset"
        )
    )

    kb.row(

        types.InlineKeyboardButton(
            "🔒 Real Trading",
            callback_data="real"
        )
    )

    return kb


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

    kb = types.InlineKeyboardMarkup()

    kb.row(

        types.InlineKeyboardButton(
            "🦈 شکار Meme Coin",
            callback_data="hunt"
        )
    )

    kb.row(

        types.InlineKeyboardButton(
            "⚙️ تنظیمات",
            callback_data="settings"
        ),

        types.InlineKeyboardButton(
            "📊 Paper",
            callback_data="paper"
        )
    )

    kb.row(

        types.InlineKeyboardButton(
            "📡 وضعیت",
            callback_data="status"
        )
    )

    bot.send_message(

        message.chat.id,

        "🦈 MEME HUNTER V8\n\n"

        "ربات آماده است.\n\n"

        "🔎 شکار Meme Coin\n"
        "⭐ سیستم امتیازدهی\n"
        "💧 فیلتر نقدینگی\n"
        "📊 فیلتر Volume\n"
        "🟢 Buy Pressure\n"
        "🧪 Paper Trading\n"
        "🎯 TP / 🛑 SL\n"
        "🦈 Auto Hunter\n\n"

        "💰 Real Trading: 🔒 قفل",

        reply_markup=kb
    )


# =========================================================
# COMMAND SETTINGS
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
# COMMAND HUNT
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

        "🔎 در حال بررسی Meme Coinهای جدید سولانا...\n"
        "⏳ چند ثانیه صبر کن."
    )

    try:

        results = run_hunt()

        if not results:

            bot.send_message(

                message.chat.id,

                "🦈 فعلاً داده‌ای مناسب پیدا نشد."
            )

            return

        text = (
            "🦈 TOP MEME HUNTS V8\n\n"
        )

        shown = 0

        for result in results:

            info = result[
                "info"
            ]

            score = result[
                "score"
            ]

            opened = result[
                "opened"
            ]

            if shown >= 5:

                break

            shown += 1

            qualified = passes_filters(
                info,
                score
            )

            text += (

                f"#{shown} 🪙 "
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
            f"${s['min_volume']:,.0f}\n\n"

            f"🧪 Paper Trading: "
            f"{'ON' if s['paper_trading'] else 'OFF'}\n"

            "💰 Real Trading: 🔒 LOCKED"
        )

        bot.send_message(

            message.chat.id,

            text
        )

    except Exception as e:

        bot.send_message(

            message.chat.id,

            "❌ خطا در اسکن:\n\n"
            f"{e}"
        )


# =========================================================
# PAPER
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

        for t in trades

        if t["pnl"] > 0
    )

    losses = sum(

        1

        for t in trades

        if t["pnl"] < 0
    )

    total = len(
        trades
    )

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

        message.chat.id,

        "🧪 PAPER TRADING V8\n\n"

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
        f"${pnl:+.4f}"
    )


# =========================================================
# STATUS
# =========================================================

@bot.message_handler(
    commands=["status"]
)
def status_command(message):

    s = state[
        "settings"
    ]

    bot.send_message(

        message.chat.id,

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
        f"{len(state['trades'])}"
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

    # -------------------------
    # HUNT
    # -------------------------

    if data == "hunt":

        bot.answer_callback_query(
            call.id,
            "🔎 در حال اسکن..."
        )

        try:

            results = run_hunt()

            if not results:

                bot.send_message(

                    call.message.chat.id,

                    "🦈 فعلاً فرصت مناسبی پیدا نشد."
                )

                return

            text = (
                "🦈 TOP MEME HUNTS V8\n\n"
            )

            count = 0

            for result in results:

                if count >= 5:

                    break

                count += 1

                info = result[
                    "info"
                ]

                score = result[
                    "score"
                ]

                opened = result[
                    "opened"
                ]

                qualified = passes_filters(
                    info,
                    score
                )

                text += (

                    f"#{count} 🪙 "
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

            bot.send_message(

                call.message.chat.id,

                text
            )

        except Exception as e:

            bot.send_message(

                call.message.chat.id,

                f"❌ Scan error:\n{e}"
            )

        return

    # -------------------------
    # SETTINGS
    # -------------------------

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

    # -------------------------
    # STATUS
    # -------------------------

    if data == "status":

        bot.answer_callback_query(
            call.id
        )

        s = state[
            "settings"
        ]

        bot.send_message(

            call.message.chat.id,

            "📡 STATUS\n\n"

            "🟢 ONLINE\n"

            f"🦈 Auto: "
            f"{'ON' if s['auto_hunter'] else 'OFF'}\n"

            f"🧪 Paper: "
            f"{'ON' if s['paper_trading'] else 'OFF'}\n"

            "💰 Real: 🔒 LOCKED\n\n"

            f"💵 Balance: "
            f"${state['balance']:.2f}\n"

            f"📂 Open: "
            f"{len(state['open_positions'])}"
        )

        return

    # -------------------------
    # PAPER
    # -------------------------

    if data == "paper_menu":

        bot.answer_callback_query(
            call.id
        )

        return

    # -------------------------
    # SCORE
    # -------------------------

    if data == "score_minus":

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

            100000,

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

            50000,

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

            5.0,

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

    elif data == "paper":

        s["paper_trading"] = not s[
            "paper_trading"
        ]

    # -------------------------
    # RESET
    # -------------------------

    elif data == "reset":

        s.clear()

        s.update(
            DEFAULT_SETTINGS.copy()
        )

    # -------------------------
    # REAL
    # -------------------------

    elif data == "real":

        bot.answer_callback_query(

            call.id,

            "🔒 Real Trading فعلاً قفل است.\n"
            "هیچ معامله واقعی انجام نمی‌شود.",

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
            "Edit settings error:",
            e
        )


# =========================================================
# AUTO HUNTER
# =========================================================

def auto_loop():

    print(
        "🦈 Auto Hunter V8 started"
    )

    while True:

        try:

            s = state[
                "settings"
            ]

            if s["auto_hunter"]:

                monitor_positions()

                results = scan_market()

                for item in results:

                    info = item[
                        "info"
                    ]

                    score = item[
                        "score"
                    ]

                    if not passes_filters(
                        info,
                        score
                    ):

                        continue

                    if not s[
                        "paper_trading"
                    ]:

                        continue

                    opened = paper_buy(

                        info,

                        score
                    )

                    if opened:

                        notify(

                            "🚨 🦈 AUTO PAPER BUY\n\n"

                            f"🪙 {info['name']}\n"

                            f"⭐ Score: "
                            f"{score}/100\n"

                            f"💵 Price: "
                            f"${info['price']:.10f}\n"

                            f"💧 Liquidity: "
                            f"${info['liquidity']:,.2f}\n"

                            f"🟢 Buy pressure: "
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
    "🦈 MEME HUNTER V8 RUNNING..."
)

bot.infinity_polling()
