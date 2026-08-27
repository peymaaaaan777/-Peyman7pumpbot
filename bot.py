import os
import time
import json
import threading
import requests
import telebot
from telebot import types

# =========================================================
# BASIC CONFIG
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
    "min_score": 70,
    "min_buy_pressure": 60,
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
            **result.get("settings", {})
        }

        return result

    except Exception as e:

        print("❌ State load error:", e)

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

        print("❌ Save error:", e)


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
            "❌ Pool error:",
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

    total = (
        info["buys"]
        +
        info["sells"]
    )

    pressure = info["buy_pressure"]

    fdv = info["fdv"]

    # Volume

    if volume >= 10000:

        score += 25

    elif volume >= 5000:

        score += 22

    elif volume >= 1000:

        score += 18

    elif volume >= 500:

        score += 12

    elif volume >= 100:

        score += 7

    # Transactions

    if total >= 500:

        score += 20

    elif total >= 200:

        score += 17

    elif total >= 100:

        score += 14

    elif total >= 50:

        score += 10

    elif total >= 20:

        score += 6

    # Buy pressure

    if pressure >= 0.80:

        score += 35

    elif pressure >= 0.70:

        score += 30

    elif pressure >= 0.65:

        score += 25

    elif pressure >= 0.60:

        score += 18

    elif pressure >= 0.55:

        score += 10

    # FDV

    if fdv >= 10000:

        score += 8

    elif fdv >= 5000:

        score += 5

    return min(
        score,
        100
    )


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

    if info["price"] <= 0:
        return False

    if (
        len(state["open_positions"])
        >=
        settings["max_open"]
    ):
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

            entry = position["entry"]

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
                "❌ Monitor error:",
                e
            )


# =========================================================
# MARKET SCANNER
# =========================================================

def scan_market():

    pools = get_new_pools()

    candidates = []

    for pool in pools:

        try:

            info = parse_pool(
                pool
            )

            name = (
                info["name"]
                .upper()
            )

            blocked = [
                "USDC",
                "USDT",
                "WSOL"
            ]

            if any(
                word in name
                for word in blocked
            ):
                continue

            score = calculate_score(
                info
            )

            if score >= 40:

                opened = False

                if state["settings"][
                    "paper_trading"
                ]:

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
                "❌ Scanner error:",
                e
            )

    candidates.sort(
        key=lambda x: x[0],
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
            "❌ Telegram error:",
            e
        )


# =========================================================
# SETTINGS TEXT
# =========================================================

def settings_text():

    s = state["settings"]

    return (

        "⚙️ MEME HUNTER SETTINGS\n\n"

        f"⭐ Min Score: "
        f"{s['min_score']}\n"

        f"🟢 Buy Pressure: "
        f"{s['min_buy_pressure']}%\n"

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
        f"{'🟢 ON' if s['paper_trading'] else '🔴 OFF'}\n"

        "💰 Real Trading: 🔒 LOCKED\n\n"

        "⚠️ نسخه فعلی فقط Paper Trading دارد."
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

    keyboard = types.InlineKeyboardMarkup()

    keyboard.row(

        types.InlineKeyboardButton(
            "🦈 HUNT",
            callback_data="hunt_button"
        )
    )

    keyboard.row(

        types.InlineKeyboardButton(
            "⚙️ SETTINGS",
            callback_data="settings_button"
        ),

        types.InlineKeyboardButton(
            "📊 PAPER",
            callback_data="paper_button"
        )
    )

    keyboard.row(

        types.InlineKeyboardButton(
            "📡 STATUS",
            callback_data="status_button"
        )
    )

    bot.send_message(

        message.chat.id,

        "🦈 MEME HUNTER\n\n"

        "🟢 ربات فعال است\n\n"

        "از منوی زیر استفاده کن 👇\n\n"

        "🧪 Paper Trading فعال است\n"
        "💰 Real Trading قفل است 🔒",

        reply_markup=keyboard
    )


# =========================================================
# SETTINGS COMMAND
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

    # -----------------------------------------------------
    # MAIN MENU
    # -----------------------------------------------------

    if data == "hunt_button":

        bot.answer_callback_query(
            call.id,
            "🔎 در حال اسکن..."
        )

        run_hunt(
            call.message.chat.id
        )

        return

    if data == "settings_button":

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

    if data == "paper_button":

        bot.answer_callback_query(
            call.id
        )

        send_paper_stats(
            call.message.chat.id
        )

        return

    if data == "status_button":

        bot.answer_callback_query(
            call.id
        )

        send_status(
            call.message.chat.id
        )

        return

    # -----------------------------------------------------
    # SCORE
    # -----------------------------------------------------

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

            5.00,

            round(
                s["trade_size"] + 0.10,
                2
            )
        )

    # -----------------------------------------------------
    # TAKE PROFIT
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
    # STOP LOSS
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
    # AUTO HUNTER
    # -----------------------------------------------------

    elif data == "auto":

        s["auto_hunter"] = (
            not s["auto_hunter"]
        )

    # -----------------------------------------------------
    # PAPER TRADING
    # -----------------------------------------------------

    elif data == "paper":

        s["paper_trading"] = (
            not s["paper_trading"]
        )

    # -----------------------------------------------------
    # REAL TRADING
    # -----------------------------------------------------

    elif data == "real":

        bot.answer_callback_query(

            call.id,

            "🔒 Real Trading فعلاً قفل است.\n\n"
            "برای معامله واقعی باید سیستم "
            "اتصال و امضای امن کیف پول اضافه شود.",

            show_alert=True
        )

        return

    # -----------------------------------------------------
    # SAVE
    # -----------------------------------------------------

    save_state()

    try:

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
            "❌ Edit error:",
            e
        )


# =========================================================
# STATUS
# =========================================================

def send_status(chat_id):

    s = state["settings"]

    bot.send_message(

        chat_id,

        "📡 MEME HUNTER STATUS\n\n"

        f"🟢 Bot: ONLINE\n"

        f"🦈 Auto Hunter: "
        f"{'فعال' if s['auto_hunter'] else 'خاموش'}\n"

        f"🧪 Paper Trading: "
        f"{'فعال' if s['paper_trading'] else 'خاموش'}\n"

        "💰 Real Trading: 🔒 LOCKED\n\n"

        f"💵 Paper Balance: "
        f"${state['balance']:.2f}\n"

        f"📂 Open Positions: "
        f"{len(state['open_positions'])}\n"

        f"🔢 Closed Trades: "
        f"{len(state['trades'])}"
    )


@bot.message_handler(
    commands=["status"]
)
def status(message):

    state["chat_id"] = (
        message.chat.id
    )

    save_state()

    send_status(
        message.chat.id
    )


# =========================================================
# HUNT FUNCTION
# =========================================================

def run_hunt(chat_id):

    bot.send_message(

        chat_id,

        "🔎 در حال اسکن New Pools سولانا...\n"
        "⏳ چند ثانیه صبر کن..."
    )

    try:

        candidates = scan_market()

        if not candidates:

            bot.send_message(

                chat_id,

                "🔎 فعلاً فرصت مناسبی پیدا نشد."
            )

            return

        text = (
            "🦈 TOP HUNTS\n\n"
        )

        for i, (
            score,
            info,
            opened
        ) in enumerate(
            candidates,
            1
        ):

            text += (

                f"#{i} 🪙 "
                f"{info['name']}\n"

                f"⭐ Score: "
                f"{score}/100\n"

                f"💵 Price: "
                f"${info['price']:.10f}\n"

                f"📊 M5 Volume: "
                f"${info['m5_volume']:,.2f}\n"

                f"🛒 Buys: "
                f"{info['buys']}\n"

                f"📉 Sells: "
                f"{info['sells']}\n"

                f"🟢 Buy pressure: "
                f"{info['buy_pressure'] * 100:.0f}%\n"
            )

            if opened:

                text += (
                    "🧪 PAPER BUY: OPEN\n"
                )

            elif (
                score
                >=
                state["settings"]
                ["min_score"]
            ):

                text += (
                    "🎯 QUALIFIED\n"
                )

            else:

                text += (
                    "👀 WATCHING\n"
                )

            text += "\n"

        text += (

            "🧪 Paper Trading: "
            f"{'ON' if state['settings']['paper_trading'] else 'OFF'}\n"

            f"🎯 Min Score: "
            f"{state['settings']['min_score']}\n"

            f"🟢 Min Buy Pressure: "
            f"{state['settings']['min_buy_pressure']}%\n\n"

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
# HUNT COMMAND
# =========================================================

@bot.message_handler(
    commands=["hunt"]
)
def hunt(message):

    state["chat_id"] = (
        message.chat.id
    )

    save_state()

    run_hunt(
        message.chat.id
    )


# =========================================================
# PAPER STATS
# =========================================================

def send_paper_stats(chat_id):

    trades = state["trades"]

    wins = sum(

        1
        for trade in trades
        if trade["pnl"] > 0
    )

    losses = sum(

        1
        for trade in trades
        if trade["pnl"] < 0
    )

    total = len(trades)

    pnl = sum(

        trade["pnl"]
        for trade in trades
    )

    win_rate = (

        wins / total * 100

        if total

        else 0
    )

    bot.send_message(

        chat_id,

        "📊 PAPER TRADING\n\n"

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


@bot.message_handler(
    commands=["paper"]
)
def paper(message):

    state["chat_id"] = (
        message.chat.id
    )

    save_state()

    send_paper_stats(
        message.chat.id
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

                            "🚨 🦈 AUTO PAPER BUY\n\n"

                            f"🪙 {info['name']}\n"

                            f"⭐ Score: "
                            f"{score}/100\n"

                            f"💵 Price: "
                            f"${info['price']:.10f}\n"

                            f"🟢 Buy pressure: "
                            f"{info['buy_pressure'] * 100:.0f}%\n\n"

                            "🧪 Paper Trading"
                        )

        except Exception as e:

            print(
                "❌ Auto Hunter error:",
                e
            )

        time.sleep(
            SCAN_INTERVAL
        )


# =========================================================
# START BOT
# =========================================================

threading.Thread(
    target=auto_loop,
    daemon=True
).start()

print(
    "🦈 MEME HUNTER FINAL RUNNING..."
)

bot.infinity_polling()
