import os
import time
import json
import threading
import requests
import telebot
from telebot import types

# =========================================================
# MEME HUNTER V5
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

        "settings":
            DEFAULT_SETTINGS.copy()
    }


def load_state():

    if not os.path.exists(
        STATE_FILE
    ):

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
            "Load state error:",
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
            "Save state error:",
            e
        )


# =========================================================
# HTTP
# =========================================================

def get_json(
    url,
    headers=None
):

    response = requests.get(

        url,

        headers=headers,

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

        headers
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

            headers
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
        )
        or 0
    )

    sells = int(

        transactions.get(
            "sells",
            0
        )
        or 0
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
# MEME FILTER
# =========================================================

def meme_filter(info):

    name = (
        info["name"]
        .lower()
        .strip()
    )

    blocked = [

        "usdc",
        "usdt",
        "wsol",
        "usd",
        "wrapped",
        "bitcoin",
        "ethereum",
        "solana"
    ]

    for word in blocked:

        if word in name:

            return False

    # حداقل نقدینگی
    if info["liquidity"] < 3000:

        return False

    # حجم حداقل
    if info["m5_volume"] < 500:

        return False

    # حداقل تراکنش
    total = (

        info["buys"]
        +
        info["sells"]
    )

    if total < 10:

        return False

    return True


# =========================================================
# SCORE V5
# =========================================================

def calculate_score(info):

    score = 0

    volume = info[
        "m5_volume"
    ]

    liquidity = info[
        "liquidity"
    ]

    total = (

        info["buys"]
        +
        info["sells"]
    )

    pressure = info[
        "buy_pressure"
    ]

    fdv = info[
        "fdv"
    ]

    # -----------------------------------------------------
    # VOLUME
    # -----------------------------------------------------

    if volume >= 50000:

        score += 25

    elif volume >= 20000:

        score += 22

    elif volume >= 10000:

        score += 19

    elif volume >= 5000:

        score += 15

    elif volume >= 2000:

        score += 10

    elif volume >= 500:

        score += 5

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

    elif liquidity >= 3000:

        score += 6

    # -----------------------------------------------------
    # TRANSACTIONS
    # -----------------------------------------------------

    if total >= 500:

        score += 15

    elif total >= 250:

        score += 13

    elif total >= 100:

        score += 11

    elif total >= 50:

        score += 8

    elif total >= 20:

        score += 5

    elif total >= 10:

        score += 2

    # -----------------------------------------------------
    # BUY PRESSURE
    # -----------------------------------------------------

    if pressure >= 0.85:

        score += 20

    elif pressure >= 0.75:

        score += 17

    elif pressure >= 0.70:

        score += 14

    elif pressure >= 0.65:

        score += 11

    elif pressure >= 0.60:

        score += 8

    elif pressure >= 0.55:

        score += 4

    # -----------------------------------------------------
    # FDV
    # -----------------------------------------------------

    if 10000 <= fdv <= 500000:

        score += 10

    elif 5000 <= fdv < 10000:

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

    settings = state[
        "settings"
    ]

    address = info[
        "address"
    ]

    if not address:

        return False

    if address in state[
        "open_positions"
    ]:

        return False

    if score < settings[
        "min_score"
    ]:

        return False

    if (
        info["buy_pressure"]
        <
        settings[
            "min_buy_pressure"
        ] / 100
    ):

        return False

    if info[
        "price"
    ] <= 0:

        return False

    if (
        len(
            state[
                "open_positions"
            ]
        )
        >=
        settings[
            "max_open"
        ]
    ):

        return False

    size = min(

        settings[
            "trade_size"
        ],

        state[
            "balance"
        ]
    )

    if size <= 0:

        return False

    state[
        "balance"
    ] -= size

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
# CLOSE POSITION
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

    if reason == "TP":

        change = (

            state[
                "settings"
            ][
                "take_profit"
            ] / 100
        )

    else:

        change = -(
            state[
                "settings"
            ][
                "stop_loss"
            ] / 100
        )

    pnl = (

        position[
            "size"
        ]
        *
        change
    )

    state[
        "balance"
    ] += (

        position[
            "size"
        ]
        +
        pnl
    )

    state[
        "trades"
    ].append({

        "name":
        position[
            "name"
        ],

        "entry":
        position[
            "entry"
        ],

        "exit":
        price,

        "pnl":
        pnl,

        "result":
        reason,

        "score":
        position[
            "score"
        ],

        "closed":
        time.time()
    })

    del positions[
        address
    ]

    save_state()

    return pnl


# =========================================================
# MONITOR
# =========================================================

def monitor_positions():

    for address in list(

        state[
            "open_positions"
        ]
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
                ]
                .get(
                    address
                )
            )

            if not position:

                continue

            entry = position[
                "entry"
            ]

            settings = state[
                "settings"
            ]

            tp = (

                entry
                *
                (
                    1
                    +
                    settings[
                        "take_profit"
                    ] / 100
                )
            )

            sl = (

                entry
                *
                (
                    1
                    -
                    settings[
                        "stop_loss"
                    ] / 100
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

            if not meme_filter(
                info
            ):

                continue

            score = calculate_score(
                info
            )

            opened = False

            if state[
                "settings"
            ][
                "paper_trading"
            ]:

                opened = paper_buy(

                    info,

                    score
                )

            if score >= 40:

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

        "⚙️ تنظیمات V5\n\n"

        f"⭐ حداقل Score: "
        f"{s['min_score']}\n"

        f"🟢 حداقل Buy Pressure: "
        f"{s['min_buy_pressure']}%\n"

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

    state[
        "chat_id"
    ] = message.chat.id

    save_state()

    keyboard = (
        types.InlineKeyboardMarkup()
    )

    keyboard.row(

        types.InlineKeyboardButton(
            "🦈 شکار بازار",
            callback_data="hunt"
        )
    )

    keyboard.row(

        types.InlineKeyboardButton(
            "📊 وضعیت",
            callback_data="status"
        ),

        types.InlineKeyboardButton(
            "🧪 Paper",
            callback_data="paper"
        )
    )

    keyboard.row(

        types.InlineKeyboardButton(
            "⚙️ تنظیمات",
            callback_data="settings"
        )
    )

    keyboard.row(

        types.InlineKeyboardButton(
            "🔄 اسکن فوری",
            callback_data="hunt"
        )
    )

    bot.send_message(

        message.chat.id,

        "🦈 MEME HUNTER V5\n\n"

        "ربات مخصوص شکار توکن‌های تازه "
        "در Solana آماده است.\n\n"

        "🧪 Paper Trading: فعال\n"
        "💰 Real Trading: قفل 🔒",

        reply_markup=keyboard
    )


# =========================================================
# SETTINGS COMMAND
# =========================================================

@bot.message_handler(
    commands=["settings"]
)
def settings(message):

    state[
        "chat_id"
    ] = message.chat.id

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

    data = call.data

    s = state[
        "settings"
    ]

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

    if data == "score_minus":

        s[
            "min_score"
        ] = max(

            50,

            s[
                "min_score"
            ] - 5
        )

    elif data == "score_plus":

        s[
            "min_score"
        ] = min(

            100,

            s[
                "min_score"
            ] + 5
        )

    elif data == "buy_minus":

        s[
            "min_buy_pressure"
        ] = max(

            50,

            s[
                "min_buy_pressure"
            ] - 5
        )

    elif data == "buy_plus":

        s[
            "min_buy_pressure"
        ] = min(

            95,

            s[
                "min_buy_pressure"
            ] + 5
        )

    elif data == "size_minus":

        s[
            "trade_size"
        ] = max(

            0.10,

            round(

                s[
                    "trade_size"
                ] - 0.10,

                2
            )
        )

    elif data == "size_plus":

        s[
            "trade_size"
        ] = min(

            5.0,

            round(

                s[
                    "trade_size"
                ] + 0.10,

                2
            )
        )

    elif data == "tp_minus":

        s[
            "take_profit"
        ] = max(

            5,

            s[
                "take_profit"
            ] - 5
        )

    elif data == "tp_plus":

        s[
            "take_profit"
        ] = min(

            100,

            s[
                "take_profit"
            ] + 5
        )

    elif data == "sl_minus":

        s[
            "stop_loss"
        ] = max(

            5,

            s[
                "stop_loss"
            ] - 5
        )

    elif data == "sl_plus":

        s[
            "stop_loss"
        ] = min(

            50,

            s[
                "stop_loss"
            ] + 5
        )

    elif data == "auto":

        s[
            "auto_hunter"
        ] = not s[
            "auto_hunter"
        ]

    elif data == "paper":

        s[
            "paper_trading"
        ] = not s[
            "paper_trading"
        ]

    elif data == "real":

        bot.answer_callback_query(

            call.id,

            "🔒 Real Trading در V5 عمداً قفل است.",

            show_alert=True
        )

        return

    elif data == "hunt":

        bot.answer_callback_query(

            call.id,

            "🔎 در حال اسکن..."
        )

        try:

            candidates = scan_market()

            if not candidates:

                bot.send_message(

                    call.message.chat.id,

                    "🦈 فعلاً کاندید مناسبی پیدا نشد."
                )

                return

            text = (
                "🦈 TOP MEME HUNTS V5\n\n"
            )

            for i, (
                score,
                info,
                opened
            ) in enumerate(

                candidates,

                1
            ):

                status_text = (

                    "🧪 PAPER BUY: OPEN"

                    if opened

                    else (

                        "🎯 QUALIFIED"

                        if score >= s[
                            "min_score"
                        ]

                        else
                        "👀 WATCHING"
                    )
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

            text += (

                "⚙️ FILTERS\n"

                f"⭐ Min Score: "
                f"{s['min_score']}\n"

                f"🟢 Min Buy Pressure: "
                f"{s['min_buy_pressure']}%\n\n"

                "🧪 Paper Trading: "
                f"{'ON' if s['paper_trading'] else 'OFF'}\n"

                "💰 Real Trading: 🔒 LOCKED"
            )

            bot.send_message(

                call.message.chat.id,

                text
            )

        except Exception as e:

            bot.send_message(

                call.message.chat.id,

                f"❌ خطا در اسکن:\n{e}"
            )

        return

    elif data == "status":

        bot.answer_callback_query(
            call.id
        )

        bot.send_message(

            call.message.chat.id,

            "📡 STATUS\n\n"

            "🟢 Bot: ONLINE\n"

            f"🦈 Auto Hunter: "
            f"{'ON' if s['auto_hunter'] else 'OFF'}\n"

            f"🧪 Paper: "
            f"{'ON' if s['paper_trading'] else 'OFF'}\n"

            "💰 Real: 🔒 LOCKED\n\n"

            f"💵 Balance: "
            f"${state['balance']:.2f}\n"

            f"📂 Open: "
            f"{len(state['open_positions'])}\n"

            f"🔢 Closed: "
            f"{len(state['trades'])}"
        )

        return

    elif data == "paper":

        bot.answer_callback_query(
            call.id
        )

        trades = state[
            "trades"
        ]

        wins = sum(

            1

            for t in trades

            if t[
                "pnl"
            ] > 0
        )

        losses = sum(

            1

            for t in trades

            if t[
                "pnl"
            ] < 0
        )

        total = len(
            trades
        )

        pnl = sum(

            t[
                "pnl"
            ]

            for t in trades
        )

        win_rate = (

            wins / total * 100

            if total

            else 0
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
            f"{win_rate:.1f}%\n"

            f"💰 PnL: "
            f"${pnl:+.4f}"
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
# COMMANDS
# =========================================================

@bot.message_handler(
    commands=["status"]
)
def status_command(message):

    state[
        "chat_id"
    ] = message.chat.id

    save_state()

    s = state[
        "settings"
    ]

    bot.reply_to(

        message,

        "📡 STATUS\n\n"

        "🟢 Bot: ONLINE\n"

        f"🦈 Auto Hunter: "
        f"{'ON' if s['auto_hunter'] else 'OFF'}\n"

        f"🧪 Paper: "
        f"{'ON' if s['paper_trading'] else 'OFF'}\n"

        "💰 Real: 🔒 LOCKED\n\n"

        f"💵 Balance: "
        f"${state['balance']:.2f}\n"

        f"📂 Open: "
        f"{len(state['open_positions'])}\n"

        f"🔢 Closed: "
        f"{len(state['trades'])}"
    )


@bot.message_handler(
    commands=["hunt"]
)
def hunt_command(message):

    state[
        "chat_id"
    ] = message.chat.id

    save_state()

    bot.send_message(

        message.chat.id,

        "🔎 در حال اسکن میم‌کوین‌های جدید سولانا..."
    )

    try:

        candidates = scan_market()

        if not candidates:

            bot.send_message(

                message.chat.id,

                "🦈 فعلاً کاندید مناسبی پیدا نشد."
            )

            return

        text = (
            "🦈 TOP MEME HUNTS V5\n\n"
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

                f"💧 Liquidity: "
                f"${info['liquidity']:,.2f}\n"

                f"🛒 Buys: "
                f"{info['buys']}\n"

                f"📉 Sells: "
                f"{info['sells']}\n"

                f"🟢 Buy pressure: "
                f"{info['buy_pressure']*100:.0f}%\n"

                f"{'🧪 PAPER BUY: OPEN' if opened else ('🎯 QUALIFIED' if score >= state['settings']['min_score'] else '👀 WATCHING')}\n\n"
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


# =========================================================
# AUTO HUNTER
# =========================================================

def auto_loop():

    print(
        "🦈 MEME HUNTER V5 AUTO STARTED"
    )

    while True:

        try:

            if state[
                "settings"
            ][
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

                            f"🟢 Buy pressure: "
                            f"{info['buy_pressure']*100:.0f}%\n\n"

                            "🧪 Paper Trading"
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
    "🦈 MEME HUNTER V5 RUNNING..."
)

bot.infinity_polling()
