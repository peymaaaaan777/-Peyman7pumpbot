import os
import time
import json
import threading
import requests
import telebot
from telebot import types

# =========================================================
# 🦈 MEME HUNTER FINAL
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

JUPITER_ORDER_API = "https://api.jup.ag/swap/v2/order"

# =========================================================
# CONFIG
# =========================================================

STATE_FILE = "bot_state.json"

START_BALANCE = 5.00

SCAN_INTERVAL = 180

SOL_MINT = (
    "So11111111111111111111111111111111111111112"
)

# =========================================================
# 🐸 MEME FILTERS
# =========================================================

DEFAULT_SETTINGS = {

    "min_score": 70,

    "min_buy_pressure": 60,

    "min_liquidity": 10000,

    "min_m5_volume": 5000,

    "min_transactions": 30,

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
            "❌ Save error:",
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

        "buys":
        buys,

        "sells":
        sells,

        "transactions":
        total,

        "buy_pressure":
        pressure
    }

# =========================================================
# 🧠 SCORE ENGINE
# =========================================================

def calculate_score(info):

    score = 0

    volume = info["m5_volume"]

    liquidity = info["liquidity"]

    transactions = info["transactions"]

    pressure = info["buy_pressure"]

    fdv = info["fdv"]

    # -------------------------
    # VOLUME 30
    # -------------------------

    if volume >= 50000:

        score += 30

    elif volume >= 25000:

        score += 27

    elif volume >= 10000:

        score += 24

    elif volume >= 5000:

        score += 20

    elif volume >= 2500:

        score += 14

    elif volume >= 1000:

        score += 8

    # -------------------------
    # LIQUIDITY 25
    # -------------------------

    if liquidity >= 50000:

        score += 25

    elif liquidity >= 25000:

        score += 22

    elif liquidity >= 15000:

        score += 20

    elif liquidity >= 10000:

        score += 18

    elif liquidity >= 7500:

        score += 12

    elif liquidity >= 5000:

        score += 7

    # -------------------------
    # TRANSACTIONS 20
    # -------------------------

    if transactions >= 500:

        score += 20

    elif transactions >= 300:

        score += 18

    elif transactions >= 150:

        score += 16

    elif transactions >= 100:

        score += 13

    elif transactions >= 50:

        score += 10

    elif transactions >= 30:

        score += 6

    # -------------------------
    # BUY PRESSURE 20
    # -------------------------

    if pressure >= 0.85:

        score += 20

    elif pressure >= 0.75:

        score += 18

    elif pressure >= 0.70:

        score += 15

    elif pressure >= 0.65:

        score += 12

    elif pressure >= 0.60:

        score += 8

    # -------------------------
    # FDV BONUS 5
    # -------------------------

    if 10000 <= fdv <= 500000:

        score += 5

    return min(
        score,
        100
    )

# =========================================================
# 🐸 MEME VALIDATION
# =========================================================

def is_meme_candidate(info):

    name = (
        info["name"]
        .upper()
    )

    # فقط SOL pairs
    if "/ SOL" not in name:

        return False

    # حذف استیبل‌ها و توکن‌های نامناسب
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

    settings = state["settings"]

    # Liquidity
    if (
        info["liquidity"]
        <
        settings["min_liquidity"]
    ):

        return False

    # Volume
    if (
        info["m5_volume"]
        <
        settings["min_m5_volume"]
    ):

        return False

    # Transactions
    if (
        info["transactions"]
        <
        settings["min_transactions"]
    ):

        return False

    # Buy pressure
    if (
        info["buy_pressure"]
        <
        settings["min_buy_pressure"] / 100
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

    settings = state["settings"]

    address = info["address"]

    if not address:

        return False

    if address in state["open_positions"]:

        return False

    if score < settings["min_score"]:

        return False

    if (
        info["buy_pressure"]
        <
        settings["min_buy_pressure"] / 100
    ):

        return False

    if (
        len(
            state["open_positions"]
        )
        >=
        settings["max_open"]
    ):

        return False

    if info["price"] <= 0:

        return False

    size = min(

        settings["trade_size"],

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
# CLOSE
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

    settings = state["settings"]

    if reason == "TP":

        change = (
            settings["take_profit"]
            / 100
        )

    else:

        change = -(
            settings["stop_loss"]
            / 100
        )

    pnl = (
        position["size"]
        * change
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
        position["entry"],

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

    del state[
        "open_positions"
    ][address]

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

            price = info["price"]

            if price <= 0:

                continue

            position = (
                state["open_positions"]
                .get(address)
            )

            if not position:

                continue

            settings = state["settings"]

            entry = position["entry"]

            tp = (

                entry
                *
                (
                    1
                    +
                    settings["take_profit"]
                    / 100
                )
            )

            sl = (

                entry
                *
                (
                    1
                    -
                    settings["stop_loss"]
                    / 100
                )
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

                    f"💵 Entry: "
                    f"${entry:.10f}\n"

                    f"💵 Exit: "
                    f"${price:.10f}\n"

                    f"💰 PnL: "
                    f"${pnl:+.4f}"
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
# 🦈 SCANNER
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

            opened = False

            if (
                state["settings"]
                ["paper_trading"]
            ):

                opened = paper_buy(

                    info,

                    score
                )

            candidates.append(

                (
                    score,

                    info,

                    opened
                )
            )

        except Exception as e:

            print(
                "Scanner error:",
                e
            )

    candidates.sort(

        key=lambda x: (

            x[0],

            x[1]["buy_pressure"],

            x[1]["m5_volume"]

        ),

        reverse=True
    )

    return candidates[:5]

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
            "Telegram error:",
            e
        )

# =========================================================
# SETTINGS TEXT
# =========================================================

def settings_text():

    s = state["settings"]

    return (

        "⚙️ تنظیمات ربات\n\n"

        f"⭐ حداقل Score: "
        f"{s['min_score']}\n"

        f"🟢 حداقل Buy Pressure: "
        f"{s['min_buy_pressure']}%\n"

        f"💧 حداقل Liquidity: "
        f"${s['min_liquidity']:,.0f}\n"

        f"📊 حداقل M5 Volume: "
        f"${s['min_m5_volume']:,.0f}\n"

        f"🛒 حداقل Transactions: "
        f"{s['min_transactions']}\n\n"

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

    keyboard = (
        types.InlineKeyboardMarkup()
    )

    keyboard.row(

        types.InlineKeyboardButton(
            "➖ Score",
            callback_data="score_minus"
        ),

        types.InlineKeyboardButton(
            "➕ Score",
            callback_data="score_plus"
        )
    )

    keyboard.row(

        types.InlineKeyboardButton(
            "➖ Buy%",
            callback_data="buy_minus"
        ),

        types.InlineKeyboardButton(
            "➕ Buy%",
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
        )
    )

    keyboard.row(

        types.InlineKeyboardButton(
            "🧪 Paper ON/OFF",
            callback_data="paper"
        )
    )

    keyboard.row(

        types.InlineKeyboardButton(
            "🪐 Jupiter Test",
            callback_data="jupiter"
        )
    )

    keyboard.row(

        types.InlineKeyboardButton(
            "💰 Real Trading",
            callback_data="real"
        )
    )

    return keyboard

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

    bot.reply_to(

        message,

        "🦈 MEME HUNTER FINAL\n\n"

        "ربات آماده است.\n"

        "تمام کنترل‌های اصلی از همین منو انجام می‌شود.\n\n"

        "🐸 Meme Scanner فعال\n"

        "🧪 Paper Trading فعال\n"

        "💰 Real Trading قفل است 🔒\n\n"

        "/settings\n"
        "/hunt\n"
        "/paper\n"
        "/status"
    )

# =========================================================
# SETTINGS
# =========================================================

@bot.message_handler(
    commands=["settings"]
)
def settings(message):

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
# CALLBACKS
# =========================================================

@bot.callback_query_handler(
    func=lambda call: True
)
def callbacks(call):

    s = state["settings"]

    data = call.data

    # SCORE
    if data == "score_minus":

        s["min_score"] = max(

            50,

            s["min_score"] - 5
        )

    elif data == "score_plus":

        s["min_score"] = min(

            100,

            s["min_score"] + 5
        )

    # BUY PRESSURE
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

    # LIQUIDITY
    elif data == "liq_minus":

        s["min_liquidity"] = max(

            5000,

            s["min_liquidity"] - 2500
        )

    elif data == "liq_plus":

        s["min_liquidity"] = min(

            50000,

            s["min_liquidity"] + 2500
        )

    # VOLUME
    elif data == "vol_minus":

        s["min_m5_volume"] = max(

            1000,

            s["min_m5_volume"] - 1000
        )

    elif data == "vol_plus":

        s["min_m5_volume"] = min(

            50000,

            s["min_m5_volume"] + 1000
        )

    # SIZE
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

    # TP
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

    # SL
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

    # AUTO
    elif data == "auto":

        s["auto_hunter"] = (
            not s["auto_hunter"]
        )

    # PAPER
    elif data == "paper":

        s["paper_trading"] = (
            not s["paper_trading"]
        )

    # REAL
    elif data == "real":

        bot.answer_callback_query(

            call.id,

            "🔒 Real Trading هنوز قفل است.\n"
            "قبل از معامله واقعی باید "
            "سیستم امضای امن کیف پول اضافه شود.",

            show_alert=True
        )

        return

    # JUPITER
    elif data == "jupiter":

        bot.answer_callback_query(

            call.id,

            "🪐 در حال گرفتن Quote..."
        )

        threading.Thread(

            target=jupiter_test_thread,

            args=(call.message.chat.id,),

            daemon=True

        ).start()

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
            "Edit error:",
            e
        )

# =========================================================
# JUPITER TEST
# =========================================================

def jupiter_test(
    token_address
):

    api_key = os.getenv(
        "JUPITER_API_KEY"
    )

    if not api_key:

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
        str(amount),

        "slippageBps":
        300
    }

    headers = {

        "x-api-key":
        api_key
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
# JUPITER THREAD
# =========================================================

def jupiter_test_thread(
    chat_id
):

    try:

        candidates = scan_market()

        if not candidates:

            bot.send_message(

                chat_id,

                "❌ فعلاً کاندید Meme مناسب پیدا نشد."
            )

            return

        score, info, opened = (
            candidates[0]
        )

        result = jupiter_test(

            info["address"]
        )

        if not result["ok"]:

            bot.send_message(

                chat_id,

                "❌ Jupiter Test Failed\n\n"

                f"{result['error']}"
            )

            return

        data = result["data"]

        bot.send_message(

            chat_id,

            "🪐 JUPITER TEST\n\n"

            f"🪙 {info['name']}\n"

            f"⭐ Score: "
            f"{score}/100\n"

            f"💵 Price: "
            f"${info['price']:.10f}\n"

            f"💧 Liquidity: "
            f"${info['liquidity']:,.2f}\n\n"

            f"📦 Quote received\n"

            f"💰 Output: "
            f"{data.get('outAmount', '?')}\n\n"

            "✅ Quote موفق بود.\n"

            "❌ هیچ معامله واقعی انجام نشد."
        )

    except Exception as e:

        bot.send_message(

            chat_id,

            "❌ Jupiter Error\n\n"

            f"{e}"
        )

# =========================================================
# STATUS
# =========================================================

@bot.message_handler(
    commands=["status"]
)
def status(message):

    state["chat_id"] = (
        message.chat.id
    )

    save_state()

    s = state["settings"]

    bot.reply_to(

        message,

        "🟢 MEME HUNTER ONLINE\n\n"

        f"🐸 Meme Scanner: فعال\n"

        f"🦈 Auto Hunter: "
        f"{'روشن 🟢' if s['auto_hunter'] else 'خاموش 🔴'}\n"

        f"🧪 Paper Trading: "
        f"{'روشن 🟢' if s['paper_trading'] else 'خاموش 🔴'}\n"

        "💰 Real Trading: 🔒 LOCKED\n\n"

        f"💵 Balance: "
        f"${state['balance']:.2f}\n"

        f"📂 Open: "
        f"{len(state['open_positions'])}\n"

        f"🔢 Closed: "
        f"{len(state['trades'])}"
    )

# =========================================================
# HUNT
# =========================================================

@bot.message_handler(
    commands=["hunt"]
)
def hunt(message):

    state["chat_id"] = (
        message.chat.id
    )

    save_state()

    bot.send_message(

        message.chat.id,

        "🦈 در حال شکار Meme Coin های سولانا...\n"
        "⏳ چند ثانیه صبر کن"
    )

    try:

        candidates = scan_market()

        if not candidates:

            bot.send_message(

                message.chat.id,

                "🦈 فعلاً Meme Coin مناسبی "
                "از فیلترهای سخت ما عبور نکرد."
            )

            return

        text = (

            "🦈 TOP MEME HUNTS FINAL\n\n"
        )

        for i, (
            score,
            info,
            opened
        ) in enumerate(

            candidates,

            1
        ):

            if opened:

                status_text = (
                    "🧪 PAPER BUY: OPEN"
                )

            elif score >= state[
                "settings"
            ]["min_score"]:

                status_text = (
                    "🎯 QUALIFIED"
                )

            else:

                status_text = (
                    "👀 WATCHING"
                )

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
                f"{info['buy_pressure']*100:.0f}%\n"

                f"{status_text}\n\n"
            )

        s = state["settings"]

        text += (

            "⚙️ FILTERS\n"

            f"⭐ Min Score: "
            f"{s['min_score']}\n"

            f"🟢 Min Buy Pressure: "
            f"{s['min_buy_pressure']}%\n"

            f"💧 Min Liquidity: "
            f"${s['min_liquidity']:,.0f}\n"

            f"📊 Min M5 Volume: "
            f"${s['min_m5_volume']:,.0f}\n"

            f"🛒 Min Transactions: "
            f"{s['min_transactions']}\n\n"

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

            f"❌ Scanner Error\n\n{e}"
        )

# =========================================================
# PAPER
# =========================================================

@bot.message_handler(
    commands=["paper"]
)
def paper(message):

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

    bot.reply_to(

        message,

        "🧪 PAPER TRADING\n\n"

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
# AUTO HUNTER
# =========================================================

def auto_loop():

    print(
        "🦈 Auto Hunter started"
    )

    while True:

        try:

            if state["settings"][
                "auto_hunter"
            ]:

                monitor_positions()

                candidates = scan_market()

                for (
                    score,
                    info,
                    opened
                ) in candidates:

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

                            f"📊 M5 Volume: "
                            f"${info['m5_volume']:,.2f}\n"

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
    "🦈 MEME HUNTER FINAL RUNNING..."
)

bot.infinity_polling()
