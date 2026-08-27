import os
import time
import json
import threading
import requests
import telebot
from telebot import types

# =========================================================
# 🦈 MEME HUNTER V6
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

JUPITER_API = "https://api.jup.ag/swap/v2/order"

JUPITER_API_KEY = os.getenv("JUPITER_API_KEY")

STATE_FILE = "bot_state.json"

# =========================================================
# BASIC
# =========================================================

START_BALANCE = 5.00
SCAN_INTERVAL = 180

SOL_MINT = "So11111111111111111111111111111111111111112"

# =========================================================
# SETTINGS
# =========================================================

DEFAULT_SETTINGS = {

    "min_score": 70,

    "min_buy_pressure": 60,

    "min_liquidity": 5000,

    "min_volume": 1000,

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

        "settings":
        DEFAULT_SETTINGS.copy()
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
# HELPERS
# =========================================================

def number(value):

    try:

        return float(
            value or 0
        )

    except:

        return 0.0


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

        if total

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

        "buy_pressure":
        pressure
    }


# =========================================================
# SCORE
# =========================================================

def calculate_score(info):

    score = 0

    volume = info["m5_volume"]

    liquidity = info["liquidity"]

    total = (
        info["buys"]
        +
        info["sells"]
    )

    pressure = info["buy_pressure"]

    fdv = info["fdv"]

    # -------------------------
    # VOLUME
    # -------------------------

    if volume >= 50000:

        score += 25

    elif volume >= 10000:

        score += 22

    elif volume >= 5000:

        score += 18

    elif volume >= 1000:

        score += 14

    elif volume >= 500:

        score += 8

    # -------------------------
    # LIQUIDITY
    # -------------------------

    if liquidity >= 50000:

        score += 20

    elif liquidity >= 20000:

        score += 18

    elif liquidity >= 10000:

        score += 15

    elif liquidity >= 5000:

        score += 10

    elif liquidity >= 2500:

        score += 5

    # -------------------------
    # TRANSACTIONS
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
    # BUY PRESSURE
    # -------------------------

    if pressure >= 0.85:

        score += 25

    elif pressure >= 0.75:

        score += 22

    elif pressure >= 0.70:

        score += 18

    elif pressure >= 0.65:

        score += 15

    elif pressure >= 0.60:

        score += 10

    # -------------------------
    # FDV
    # -------------------------

    if 10000 <= fdv <= 500000:

        score += 5

    return min(
        score,
        100
    )


# =========================================================
# SAFETY FILTER
# =========================================================

def is_candidate(info):

    name = info["name"].upper()

    blocked = [

        "USDC",
        "USDT",
        "WSOL",
        "SOL",
        "BTC",
        "ETH"
    ]

    for word in blocked:

        if word == name:

            return False

    if info["price"] <= 0:

        return False

    if info["liquidity"] < 1000:

        return False

    if info["m5_volume"] < 100:

        return False

    if info["buys"] + info["sells"] < 5:

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

    if (
        len(
            state[
                "open_positions"
            ]
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

    if address not in state[
        "open_positions"
    ]:

        return None

    position = (
        state[
            "open_positions"
        ][address]
    )

    if reason == "TP":

        change = (
            state["settings"]
            ["take_profit"]
            / 100
        )

    else:

        change = -(
            state["settings"]
            ["stop_loss"]
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

        "time":
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
                state[
                    "open_positions"
                ].get(address)
            )

            if not position:

                continue

            entry = position[
                "entry"
            ]

            tp = (

                entry
                *
                (
                    1
                    +
                    state["settings"]
                    ["take_profit"]
                    / 100
                )
            )

            sl = (

                entry
                *
                (
                    1
                    -
                    state["settings"]
                    ["stop_loss"]
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
# SCANNER
# =========================================================

def scan_market():

    pools = get_new_pools()

    candidates = []

    for pool in pools:

        try:

            info = parse_pool(
                pool
            )

            if not is_candidate(
                info
            ):

                continue

            score = calculate_score(
                info
            )

            opened = False

            if state[
                "settings"
            ]["paper_trading"]:

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

        key=lambda x: x[0],

        reverse=True
    )

    return candidates[:5]


# =========================================================
# JUPITER QUOTE
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

        state[
            "settings"
        ]["trade_size"]

        * 1_000_000_000
    )

    params = {

        "inputMint":
        SOL_MINT,

        "outputMint":
        token_address,

        "amount":
        str(amount),

        "swapMode":
        "ExactIn",

        "slippageBps":
        300
    }

    headers = {

        "x-api-key":
        JUPITER_API_KEY
    }

    try:

        response = requests.get(

            JUPITER_API,

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

            "error": str(e)
        }


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
# MAIN MENU
# =========================================================

def main_keyboard():

    k = types.InlineKeyboardMarkup()

    k.row(

        types.InlineKeyboardButton(
            "🦈 شکار",
            callback_data="hunt"
        ),

        types.InlineKeyboardButton(
            "📊 Paper",
            callback_data="paper"
        )
    )

    k.row(

        types.InlineKeyboardButton(
            "⚙️ تنظیمات",
            callback_data="settings"
        ),

        types.InlineKeyboardButton(
            "📡 وضعیت",
            callback_data="status"
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
# SETTINGS TEXT
# =========================================================

def settings_text():

    s = state["settings"]

    return (

        "⚙️ تنظیمات MEME HUNTER V6\n\n"

        f"⭐ حداقل Score: "
        f"{s['min_score']}\n"

        f"🟢 Buy Pressure: "
        f"{s['min_buy_pressure']}%\n"

        f"💧 حداقل Liquidity: "
        f"${s['min_liquidity']:,.0f}\n"

        f"📊 حداقل M5 Volume: "
        f"${s['min_volume']:,.0f}\n"

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


# =========================================================
# SETTINGS KEYBOARD
# =========================================================

def settings_keyboard():

    k = types.InlineKeyboardMarkup()

    k.row(

        types.InlineKeyboardButton(
            "⭐ Score -",
            callback_data="score_minus"
        ),

        types.InlineKeyboardButton(
            "⭐ Score +",
            callback_data="score_plus"
        )
    )

    k.row(

        types.InlineKeyboardButton(
            "🟢 Buy% -",
            callback_data="buy_minus"
        ),

        types.InlineKeyboardButton(
            "🟢 Buy% +",
            callback_data="buy_plus"
        )
    )

    k.row(

        types.InlineKeyboardButton(
            "💧 Liquidity -",
            callback_data="liq_minus"
        ),

        types.InlineKeyboardButton(
            "💧 Liquidity +",
            callback_data="liq_plus"
        )
    )

    k.row(

        types.InlineKeyboardButton(
            "📊 Volume -",
            callback_data="vol_minus"
        ),

        types.InlineKeyboardButton(
            "📊 Volume +",
            callback_data="vol_plus"
        )
    )

    k.row(

        types.InlineKeyboardButton(
            "💵 مبلغ -",
            callback_data="size_minus"
        ),

        types.InlineKeyboardButton(
            "💵 مبلغ +",
            callback_data="size_plus"
        )
    )

    k.row(

        types.InlineKeyboardButton(
            "🎯 TP -",
            callback_data="tp_minus"
        ),

        types.InlineKeyboardButton(
            "🎯 TP +",
            callback_data="tp_plus"
        )
    )

    k.row(

        types.InlineKeyboardButton(
            "🛑 SL -",
            callback_data="sl_minus"
        ),

        types.InlineKeyboardButton(
            "🛑 SL +",
            callback_data="sl_plus"
        )
    )

    k.row(

        types.InlineKeyboardButton(
            "🦈 Auto ON/OFF",
            callback_data="auto"
        ),

        types.InlineKeyboardButton(
            "🧪 Paper ON/OFF",
            callback_data="paper"
        )
    )

    k.row(

        types.InlineKeyboardButton(
            "💰 Real Trading 🔒",
            callback_data="real"
        )
    )

    k.row(

        types.InlineKeyboardButton(
            "🔙 منوی اصلی",
            callback_data="menu"
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

        "🦈 MEME HUNTER V6\n\n"

        "ربات آماده است.\n"

        "تمام کنترل‌های اصلی از همین منو انجام می‌شود.\n\n"

        "🧪 Paper Trading فعال است.\n"

        "💰 Real Trading فعلاً قفل است. 🔒",

        reply_markup=
        main_keyboard()
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

    s = state["settings"]

    bot.reply_to(

        message,

        "📡 وضعیت MEME HUNTER V6\n\n"

        f"🦈 Auto Hunter: "
        f"{'🟢 ON' if s['auto_hunter'] else '🔴 OFF'}\n"

        f"🧪 Paper: "
        f"{'🟢 ON' if s['paper_trading'] else '🔴 OFF'}\n"

        "💰 Real: 🔒 LOCKED\n\n"

        f"💵 Balance: "
        f"${state['balance']:.2f}\n"

        f"📂 Open: "
        f"{len(state['open_positions'])}\n"

        f"🔢 Closed: "
        f"{len(state['trades'])}"
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

    bot.send_message(

        message.chat.id,

        "🔎 در حال بررسی میم‌کوین‌های جدید سولانا..."
    )

    try:

        candidates = scan_market()

        if not candidates:

            bot.send_message(

                message.chat.id,

                "🦈 فعلاً کاندید مناسبی پیدا نشد."
            )

            return

        send_hunts(

            message.chat.id,

            candidates
        )

    except Exception as e:

        bot.send_message(

            message.chat.id,

            f"❌ خطای اسکن:\n{e}"
        )


# =========================================================
# HUNT OUTPUT
# =========================================================

def send_hunts(
    chat_id,
    candidates
):

    s = state["settings"]

    text = (

        "🦈 TOP MEME HUNTS V6\n\n"
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

            label = (
                "🧪 PAPER BUY: OPEN"
            )

        elif (

            score >= s["min_score"]

            and

            info["buy_pressure"]
            >=
            s["min_buy_pressure"] / 100

            and

            info["liquidity"]
            >=
            s["min_liquidity"]

            and

            info["m5_volume"]
            >=
            s["min_volume"]
        ):

            label = "🎯 QUALIFIED"

        else:

            label = "👀 WATCHING"

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

            f"{label}\n\n"
        )

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

        chat_id,

        text
    )


# =========================================================
# /PAPER
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
# CALLBACKS
# =========================================================

@bot.callback_query_handler(
    func=lambda call: True
)
def callbacks(call):

    data = call.data

    s = state["settings"]

    if data == "menu":

        bot.edit_message_text(

            "🦈 MEME HUNTER V6\n\n"
            "کنترل پنل اصلی:",

            call.message.chat.id,

            call.message.message_id,

            reply_markup=
            main_keyboard()
        )

        bot.answer_callback_query(
            call.id
        )

        return

    if data == "settings":

        bot.edit_message_text(

            settings_text(),

            call.message.chat.id,

            call.message.message_id,

            reply_markup=
            settings_keyboard()
        )

        bot.answer_callback_query(
            call.id
        )

        return

    if data == "hunt":

        bot.answer_callback_query(

            call.id,

            "🔎 در حال شکار..."
        )

        try:

            candidates = scan_market()

            if candidates:

                send_hunts(

                    call.message.chat.id,

                    candidates
                )

            else:

                bot.send_message(

                    call.message.chat.id,

                    "🦈 فعلاً کاندید مناسبی نیست."
                )

        except Exception as e:

            bot.send_message(

                call.message.chat.id,

                f"❌ خطا:\n{e}"
            )

        return

    if data == "paper":

        trades = state["trades"]

        wins = sum(

            1 for t in trades

            if t["pnl"] > 0
        )

        losses = sum(

            1 for t in trades

            if t["pnl"] < 0
        )

        total = len(trades)

        pnl = sum(

            t["pnl"]

            for t in trades
        )

        rate = (

            wins / total * 100

            if total

            else 0
        )

        bot.answer_callback_query(
            call.id
        )

        bot.send_message(

            call.message.chat.id,

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
            f"{rate:.1f}%\n"

            f"💰 PnL: "
            f"${pnl:+.4f}"
        )

        return

    if data == "status":

        bot.answer_callback_query(
            call.id
        )

        bot.send_message(

            call.message.chat.id,

            f"📡 ONLINE 🟢\n\n"

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

    # =====================================================
    # SCORE
    # =====================================================

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

    # =====================================================
    # BUY PRESSURE
    # =====================================================

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

    # =====================================================
    # LIQUIDITY
    # =====================================================

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

    # =====================================================
    # VOLUME
    # =====================================================

    elif data == "vol_minus":

        s["min_volume"] = max(

            100,

            s["min_volume"] - 500
        )

    elif data == "vol_plus":

        s["min_volume"] = min(

            50000,

            s["min_volume"] + 500
        )

    # =====================================================
    # SIZE
    # =====================================================

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

    # =====================================================
    # TP
    # =====================================================

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

    # =====================================================
    # SL
    # =====================================================

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

    # =====================================================
    # AUTO
    # =====================================================

    elif data == "auto":

        s["auto_hunter"] = not s[
            "auto_hunter"
        ]

    # =====================================================
    # PAPER
    # =====================================================

    elif data == "paper_toggle":

        s["paper_trading"] = not s[
            "paper_trading"
        ]

    # =====================================================
    # REAL
    # =====================================================

    elif data == "real":

        bot.answer_callback_query(

            call.id,

            "🔒 Real Trading در این نسخه قفل است. "
            "هیچ تراکنش واقعی بدون تأیید دستی ارسال نمی‌شود.",

            show_alert=True
        )

        return

    # =====================================================
    # JUPITER
    # =====================================================

    elif data == "jupiter":

        bot.answer_callback_query(

            call.id,

            "🪐 در حال تست Jupiter..."
        )

        try:

            candidates = scan_market()

            if not candidates:

                bot.send_message(

                    call.message.chat.id,

                    "❌ کاندید مناسبی پیدا نشد."
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

                    call.message.chat.id,

                    "❌ Jupiter Test Failed\n\n"

                    f"{result['error']}"
                )

                return

            jdata = result["data"]

            bot.send_message(

                call.message.chat.id,

                "🪐 JUPITER QUOTE\n\n"

                f"🪙 {info['name']}\n"

                f"⭐ Score: "
                f"{score}/100\n"

                f"💧 Liquidity: "
                f"${info['liquidity']:,.2f}\n"

                f"📊 Volume: "
                f"${info['m5_volume']:,.2f}\n\n"

                f"💰 Output USD: "
                f"{jdata.get('outUsdValue', '?')}\n"

                f"📉 Price Impact: "
                f"{jdata.get('priceImpact', '?')}\n\n"

                "✅ Quote دریافت شد.\n"

                "❌ هیچ معامله واقعی انجام نشد."
            )

        except Exception as e:

            bot.send_message(

                call.message.chat.id,

                f"❌ Jupiter Error\n\n{e}"
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
            "Edit error:",
            e
        )


# =========================================================
# AUTO HUNTER
# =========================================================

def auto_loop():

    print(
        "🦈 V6 Auto Hunter started"
    )

    while True:

        try:

            if state[
                "settings"
            ]["auto_hunter"]:

                monitor_positions()

                candidates = (
                    scan_market()
                )

                for (
                    score,
                    info,
                    opened
                ) in candidates:

                    if opened:

                        notify(

                            "🚨 🦈 PAPER BUY\n\n"

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
    "🦈 MEME HUNTER V6 RUNNING..."
)

bot.infinity_polling()
