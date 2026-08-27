import os
import time
import json
import threading
from datetime import datetime, timezone

import requests
import telebot
from telebot import types


# ============================================================
# 🦈 SOLANA HUNTER V4
# PAPER TRADING ONLY
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")

bot = telebot.TeleBot(
    BOT_TOKEN,
    parse_mode="HTML"
)

session = requests.Session()
session.headers.update({
    "User-Agent": "SolanaHunterV4/1.0"
})

DEX_API = "https://api.dexscreener.com"

STATE_FILE = "paper_state_v4.json"
CONFIG_FILE = "bot_config_v4.json"

START_BALANCE = 3.5015


# ============================================================
# DEFAULT SETTINGS
# ============================================================

DEFAULT_CONFIG = {
    "min_score": 75,
    "min_buy_pressure": 60.0,
    "min_liquidity": 25000.0,
    "min_m5_volume": 10000.0,

    "min_m5_change": -10.0,
    "max_m5_change": 20.0,

    "take_profit": 0.15,
    "stop_loss": 0.08,

    "trailing_start": 0.08,
    "trailing_distance": 0.05,

    "risk_per_trade": 0.10,

    "max_open_trades": 2,

    "scan_seconds": 15,

    "cooldown_seconds": 600,

    "max_consecutive_losses": 3,

    "loss_pause_seconds": 900,

    "enabled": True
}


config = DEFAULT_CONFIG.copy()


# ============================================================
# STATE
# ============================================================

state = {
    "balance": START_BALANCE,
    "starting_balance": START_BALANCE,

    "open_trades": [],
    "closed_trades": [],

    "wins": 0,
    "losses": 0,

    "total_pnl": 0.0,

    "consecutive_losses": 0,

    "paused_until": 0,

    "cooldowns": {},

    "top_hunts": [],

    "last_scan": None,

    "chat_id": None,

    "dashboard_message_id": None
}


lock = threading.Lock()


# ============================================================
# TIME / FORMAT
# ============================================================

def now_utc():

    return datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


def num(value, default=0.0):

    try:
        return float(value)
    except Exception:
        return default


def money(value):

    return f"${num(value):.4f}"


# ============================================================
# CONFIG SAVE / LOAD
# ============================================================

def save_config():

    try:

        with open(
            CONFIG_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                config,
                f,
                indent=2,
                ensure_ascii=False
            )

    except Exception as e:

        print(
            "CONFIG SAVE ERROR:",
            e
        )


def load_config():

    global config

    if not os.path.exists(
        CONFIG_FILE
    ):
        return

    try:

        with open(
            CONFIG_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            saved = json.load(f)

        for key in DEFAULT_CONFIG:

            if key in saved:
                config[key] = saved[key]

    except Exception as e:

        print(
            "CONFIG LOAD ERROR:",
            e
        )


# ============================================================
# STATE SAVE / LOAD
# ============================================================

def save_state():

    try:

        with lock:

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

    except Exception as e:

        print(
            "STATE SAVE ERROR:",
            e
        )


def load_state():

    if not os.path.exists(
        STATE_FILE
    ):
        return

    try:

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            saved = json.load(f)

        state.update(
            saved
        )

    except Exception as e:

        print(
            "STATE LOAD ERROR:",
            e
        )


# ============================================================
# TELEGRAM BOTTOM MENU
# ============================================================

def main_menu():

    markup = types.ReplyKeyboardMarkup(
        resize_keyboard=True,
        row_width=2
    )

    markup.add(
        types.KeyboardButton(
            "🦈 داشبورد"
        ),
        types.KeyboardButton(
            "🎯 شکارها"
        )
    )

    markup.add(
        types.KeyboardButton(
            "📂 معاملات باز"
        ),
        types.KeyboardButton(
            "📜 تاریخچه"
        )
    )

    markup.add(
        types.KeyboardButton(
            "⚙️ تنظیمات"
        ),
        types.KeyboardButton(
            "⏸️ توقف / ▶️ ادامه"
        )
    )

    markup.add(
        types.KeyboardButton(
            "🔄 ریست Paper"
        ),
        types.KeyboardButton(
            "ℹ️ وضعیت"
        )
    )

    return markup


# ============================================================
# SETTINGS MENU
# ============================================================

def settings_menu():

    markup = types.InlineKeyboardMarkup(
        row_width=2
    )

    markup.add(
        types.InlineKeyboardButton(
            "⭐ Score",
            callback_data="set_score"
        ),
        types.InlineKeyboardButton(
            "🟢 Buy Pressure",
            callback_data="set_pressure"
        )
    )

    markup.add(
        types.InlineKeyboardButton(
            "💧 Liquidity",
            callback_data="set_liquidity"
        ),
        types.InlineKeyboardButton(
            "📊 M5 Volume",
            callback_data="set_volume"
        )
    )

    markup.add(
        types.InlineKeyboardButton(
            "🎯 Take Profit",
            callback_data="set_tp"
        ),
        types.InlineKeyboardButton(
            "🛑 Stop Loss",
            callback_data="set_sl"
        )
    )

    markup.add(
        types.InlineKeyboardButton(
            "📈 Trailing",
            callback_data="set_trailing"
        ),
        types.InlineKeyboardButton(
            "🛡️ Risk / Trade",
            callback_data="set_risk"
        )
    )

    markup.add(
        types.InlineKeyboardButton(
            "📂 Max Trades",
            callback_data="set_max_trades"
        ),
        types.InlineKeyboardButton(
            "⏱️ Scan",
            callback_data="set_scan"
        )
    )

    markup.add(
        types.InlineKeyboardButton(
            "🔄 تنظیمات پیش‌فرض",
            callback_data="reset_config"
        )
    )

    return markup


def settings_text():

    return f"""
<b>⚙️ SOLANA HUNTER V4 SETTINGS</b>

━━━━━━━━━━━━━━━━━━━━

⭐ Min Score:
<b>{config["min_score"]}</b>

🟢 Min Buy Pressure:
<b>{config["min_buy_pressure"]:.0f}%</b>

💧 Min Liquidity:
<b>${config["min_liquidity"]:,.0f}</b>

📊 Min M5 Volume:
<b>${config["min_m5_volume"]:,.0f}</b>

━━━━━━━━━━━━━━━━━━━━

🎯 Take Profit:
<b>+{config["take_profit"] * 100:.0f}%</b>

🛑 Stop Loss:
<b>-{config["stop_loss"] * 100:.0f}%</b>

📈 Trailing:
<b>شروع +{config["trailing_start"] * 100:.0f}%</b>
<b>فاصله {config["trailing_distance"] * 100:.0f}%</b>

━━━━━━━━━━━━━━━━━━━━

🛡️ Risk / Trade:
<b>{config["risk_per_trade"] * 100:.0f}%</b>

📂 Max Open:
<b>{config["max_open_trades"]}</b>

⏱️ Scan:
<b>{config["scan_seconds"]}s</b>

🧪 Mode:
<b>PAPER TRADING</b>

━━━━━━━━━━━━━━━━━━━━
"""


# ============================================================
# DEXSCREENER
# ============================================================

def latest_solana_tokens():

    result = {}

    urls = [
        f"{DEX_API}/token-boosts/latest/v1",
        f"{DEX_API}/token-profiles/latest/v1"
    ]

    for url in urls:

        try:

            response = session.get(
                url,
                timeout=10
            )

            if response.status_code != 200:
                continue

            data = response.json()

            if not isinstance(
                data,
                list
            ):
                continue

            for item in data:

                if item.get(
                    "chainId"
                ) != "solana":
                    continue

                address = item.get(
                    "tokenAddress"
                )

                if address:
                    result[address] = item

        except Exception as e:

            print(
                "DISCOVERY ERROR:",
                e
            )

    return list(
        result.values()
    )


def get_pairs(address):

    try:

        url = (
            f"{DEX_API}/latest/dex/tokens/"
            f"{address}"
        )

        response = session.get(
            url,
            timeout=10
        )

        if response.status_code != 200:
            return []

        data = response.json()

        pairs = data.get(
            "pairs",
            []
        )

        return [
            p for p in pairs
            if p.get(
                "chainId"
            ) == "solana"
        ]

    except Exception as e:

        print(
            "PAIR ERROR:",
            e
        )

        return []


# ============================================================
# ANALYZE TOKEN
# ============================================================

def analyze(pair):

    try:

        base = pair.get(
            "baseToken",
            {}
        )

        address = base.get(
            "address"
        )

        if not address:
            return None

        symbol = base.get(
            "symbol",
            "UNKNOWN"
        )

        price = num(
            pair.get(
                "priceUsd"
            )
        )

        liquidity = num(
            pair.get(
                "liquidity",
                {}
            ).get(
                "usd"
            )
        )

        volume = num(
            pair.get(
                "volume",
                {}
            ).get(
                "m5"
            )
        )

        txns = pair.get(
            "txns",
            {}
        ).get(
            "m5",
            {}
        )

        buys = int(
            txns.get(
                "buys",
                0
            ) or 0
        )

        sells = int(
            txns.get(
                "sells",
                0
            ) or 0
        )

        total = buys + sells

        pressure = 0.0

        if total > 0:

            pressure = (
                buys / total
            ) * 100

        m5 = num(
            pair.get(
                "priceChange",
                {}
            ).get(
                "m5"
            )
        )

        # ----------------------------------------------------
        # SCORE
        # ----------------------------------------------------

        score = 0

        if liquidity >= 100000:
            score += 20
        elif liquidity >= 50000:
            score += 17
        elif liquidity >= 25000:
            score += 13

        if volume >= 100000:
            score += 20
        elif volume >= 50000:
            score += 17
        elif volume >= 25000:
            score += 14
        elif volume >= 10000:
            score += 10

        if pressure >= 75:
            score += 25
        elif pressure >= 68:
            score += 21
        elif pressure >= 60:
            score += 16

        if total >= 200:
            score += 15
        elif total >= 100:
            score += 12
        elif total >= 50:
            score += 9
        elif total >= 20:
            score += 5

        if 1 <= m5 <= 10:
            score += 15
        elif 0 <= m5 < 1:
            score += 9
        elif 10 < m5 <= 20:
            score += 7

        if m5 < -5:
            score -= 20

        if m5 > 20:
            score -= 10

        score = max(
            0,
            min(
                100,
                score
            )
        )

        return {
            "address": address,
            "symbol": symbol,
            "price": price,
            "liquidity": liquidity,
            "volume": volume,
            "buys": buys,
            "sells": sells,
            "buy_pressure": pressure,
            "m5": m5,
            "score": score
        }

    except Exception as e:

        print(
            "ANALYZE ERROR:",
            e
        )

        return None


# ============================================================
# ENTRY FILTER
# ============================================================

def check_entry(t):

    if t["score"] < config["min_score"]:
        return False

    if (
        t["buy_pressure"]
        < config["min_buy_pressure"]
    ):
        return False

    if (
        t["liquidity"]
        < config["min_liquidity"]
    ):
        return False

    if (
        t["volume"]
        < config["min_m5_volume"]
    ):
        return False

    if (
        t["m5"]
        < config["min_m5_change"]
    ):
        return False

    if (
        t["m5"]
        > config["max_m5_change"]
    ):
        return False

    return True


# ============================================================
# COOLDOWN
# ============================================================

def is_cooldown(address):

    until = num(
        state[
            "cooldowns"
        ].get(
            address,
            0
        )
    )

    return time.time() < until


def set_cooldown(address):

    state[
        "cooldowns"
    ][address] = (
        time.time()
        + config["cooldown_seconds"]
    )


# ============================================================
# OPEN TRADE
# ============================================================

def find_trade(address):

    for trade in state[
        "open_trades"
    ]:

        if trade[
            "address"
        ] == address:

            return trade

    return None


# ============================================================
# BUY
# ============================================================

def paper_buy(t):

    if not config["enabled"]:
        return False

    if time.time() < num(
        state["paused_until"]
    ):
        return False

    if len(
        state["open_trades"]
    ) >= config[
        "max_open_trades"
    ]:
        return False

    if find_trade(
        t["address"]
    ):
        return False

    if is_cooldown(
        t["address"]
    ):
        return False

    if not check_entry(t):
        return False

    cash = num(
        state["balance"]
    )

    position = (
        cash
        * config["risk_per_trade"]
    )

    if position <= 0:
        return False

    trade = {

        "id": str(
            int(
                time.time()
                * 1000
            )
        ),

        "address": t[
            "address"
        ],

        "symbol": t[
            "symbol"
        ],

        "entry_price": t[
            "price"
        ],

        "current_price": t[
            "price"
        ],

        "highest_price": t[
            "price"
        ],

        "position": position,

        "entry_time": now_utc(),

        "entry_score": t[
            "score"
        ],

        "entry_pressure":
            t["buy_pressure"],

        "entry_liquidity":
            t["liquidity"],

        "entry_volume":
            t["volume"],

        "status": "OPEN"
    }

    state[
        "balance"
    ] -= position

    state[
        "open_trades"
    ].append(
        trade
    )

    save_state()

    send_buy(
        t,
        position
    )

    return True


# ============================================================
# SELL
# ============================================================

def paper_sell(
    trade,
    market_price,
    reason
):

    entry = num(
        trade[
            "entry_price"
        ]
    )

    market_price = num(
        market_price
    )

    if entry <= 0:
        return

    stop_price = None

    execution_price = market_price

    # --------------------------------------------------------
    # STOP LOSS
    # --------------------------------------------------------

    if reason == "STOP LOSS":

        stop_price = (
            entry
            * (
                1
                - config["stop_loss"]
            )
        )

        # Paper execution at intended stop.
        execution_price = stop_price

    # --------------------------------------------------------
    # PNL
    # --------------------------------------------------------

    change = (
        execution_price
        - entry
    ) / entry

    pnl = (
        trade[
            "position"
        ]
        * change
    )

    returned = (
        trade[
            "position"
        ]
        + pnl
    )

    state[
        "balance"
    ] += returned

    state[
        "total_pnl"
    ] += pnl

    if pnl >= 0:

        state[
            "wins"
        ] += 1

        state[
            "consecutive_losses"
        ] = 0

    else:

        state[
            "losses"
        ] += 1

        state[
            "consecutive_losses"
        ] += 1

        set_cooldown(
            trade[
                "address"
            ]
        )

    # --------------------------------------------------------
    # SLIPPAGE
    # --------------------------------------------------------

    slippage = 0.0

    if (
        stop_price is not None
        and stop_price > 0
    ):

        slippage = (
            (
                market_price
                - stop_price
            )
            / stop_price
        ) * 100

    trade[
        "exit_price"
    ] = execution_price

    trade[
        "market_price_at_exit"
    ] = market_price

    trade[
        "stop_price"
    ] = stop_price

    trade[
        "slippage_percent"
    ] = slippage

    trade[
        "pnl"
    ] = pnl

    trade[
        "return_percent"
    ] = change * 100

    trade[
        "exit_reason"
    ] = reason

    trade[
        "exit_time"
    ] = now_utc()

    trade[
        "status"
    ] = "CLOSED"

    if trade in state[
        "open_trades"
    ]:

        state[
            "open_trades"
        ].remove(
            trade
        )

    state[
        "closed_trades"
    ].append(
        trade
    )

    # --------------------------------------------------------
    # LOSS PROTECTION
    # --------------------------------------------------------

    if (
        state[
            "consecutive_losses"
        ]
        >= config[
            "max_consecutive_losses"
        ]
    ):

        state[
            "paused_until"
        ] = (
            time.time()
            + config[
                "loss_pause_seconds"
            ]
        )

    save_state()

    send_sell(
        trade
    )


# ============================================================
# MANAGE OPEN TRADES
# ============================================================

def manage_trades():

    for trade in list(
        state[
            "open_trades"
        ]
    ):

        try:

            pairs = get_pairs(
                trade[
                    "address"
                ]
            )

            if not pairs:
                continue

            pairs.sort(
                key=lambda p:
                num(
                    p.get(
                        "liquidity",
                        {}
                    ).get(
                        "usd"
                    )
                ),
                reverse=True
            )

            t = analyze(
                pairs[0]
            )

            if not t:
                continue

            current = num(
                t["price"]
            )

            if current <= 0:
                continue

            trade[
                "current_price"
            ] = current

            highest = num(
                trade.get(
                    "highest_price",
                    trade[
                        "entry_price"
                    ]
                )
            )

            if current > highest:

                highest = current

                trade[
                    "highest_price"
                ] = highest

            entry = num(
                trade[
                    "entry_price"
                ]
            )

            change = (
                current
                - entry
            ) / entry

            # ------------------------------------------------
            # STOP LOSS
            # ------------------------------------------------

            stop_price = (
                entry
                * (
                    1
                    - config["stop_loss"]
                )
            )

            if current <= stop_price:

                paper_sell(
                    trade,
                    current,
                    "STOP LOSS"
                )

                continue

            # ------------------------------------------------
            # TAKE PROFIT
            # ------------------------------------------------

            tp_price = (
                entry
                * (
                    1
                    + config["take_profit"]
                )
            )

            if current >= tp_price:

                paper_sell(
                    trade,
                    current,
                    "TAKE PROFIT"
                )

                continue

            # ------------------------------------------------
            # TRAILING STOP
            # ------------------------------------------------

            if (
                change
                >= config[
                    "trailing_start"
                ]
            ):

                trailing_price = (
                    highest
                    * (
                        1
                        - config[
                            "trailing_distance"
                        ]
                    )
                )

                if current <= trailing_price:

                    paper_sell(
                        trade,
                        current,
                        "TRAILING STOP"
                    )

                    continue

        except Exception as e:

            print(
                "TRADE MANAGEMENT ERROR:",
                e
            )


# ============================================================
# MARKET SCAN
# ============================================================

def scan_market():

    results = []

    tokens = (
        latest_solana_tokens()
    )

    seen = set()

    for item in tokens[:50]:

        address = item.get(
            "tokenAddress"
        )

        if not address:
            continue

        if address in seen:
            continue

        seen.add(address)

        pairs = get_pairs(
            address
        )

        if not pairs:
            continue

        pairs.sort(
            key=lambda p:
            num(
                p.get(
                    "liquidity",
                    {}
                ).get(
                    "usd"
                )
            ),
            reverse=True
        )

        t = analyze(
            pairs[0]
        )

        if t:
            results.append(
                t
            )

        time.sleep(
            0.1
        )

    results.sort(
        key=lambda x:
        x["score"],
        reverse=True
    )

    state[
        "top_hunts"
    ] = results[:10]

    state[
        "last_scan"
    ] = now_utc()

    save_state()

    return results


# ============================================================
# TRADING ENGINE
# ============================================================

def trading_engine():

    while True:

        try:

            manage_trades()

            results = scan_market()

            if config["enabled"]:

                if time.time() >= num(
                    state[
                        "paused_until"
                    ]
                ):

                    # Only one new trade
                    # per scan cycle.

                    for token in results:

                        if paper_buy(
                            token
                        ):
                            break

            update_dashboard()

        except Exception as e:

            print(
                "ENGINE ERROR:",
                e
            )

        time.sleep(
            max(
                5,
                int(
                    config[
                        "scan_seconds"
                    ]
                )
            )
        )


# ============================================================
# STATS
# ============================================================

def current_equity():

    value = num(
        state["balance"]
    )

    for trade in state[
        "open_trades"
    ]:

        entry = num(
            trade[
                "entry_price"
            ]
        )

        current = num(
            trade.get(
                "current_price",
                entry
            )
        )

        if entry <= 0:
            continue

        change = (
            current
            - entry
        ) / entry

        value += (
            trade[
                "position"
            ]
            * (
                1
                + change
            )
        )

    return value


def win_rate():

    total = (
        state["wins"]
        + state["losses"]
    )

    if total == 0:
        return 0

    return (
        state["wins"]
        / total
        * 100
    )


def drawdown():

    start = num(
        state[
            "starting_balance"
        ]
    )

    if start <= 0:
        return 0

    return (
        (
            current_equity()
            - start
        )
        / start
    ) * 100


# ============================================================
# DASHBOARD
# ============================================================

def dashboard_text():

    eq = current_equity()

    pnl = (
        eq
        - num(
            state[
                "starting_balance"
            ]
        )
    )

    if not config["enabled"]:

        status = "⏸️ PAUSED"

    elif time.time() < num(
        state["paused_until"]
    ):

        status = "🟡 LOSS PROTECTION"

    else:

        status = "🟢 ONLINE"

    return f"""
<b>🦈 SOLANA HUNTER V4</b>

━━━━━━━━━━━━━━━━━━━━

🤖 Status:
<b>{status}</b>

🧪 Mode:
<b>PAPER TRADING</b>

💵 Cash:
<b>{money(state["balance"])}</b>

📊 Equity:
<b>{money(eq)}</b>

💰 Total PnL:
<b>{pnl:+.4f} USD</b>

📉 Drawdown:
<b>{drawdown():+.2f}%</b>

━━━━━━━━━━━━━━━━━━━━

📂 Open:
<b>{len(state["open_trades"])}/{config["max_open_trades"]}</b>

🔢 Closed:
<b>{len(state["closed_trades"])}</b>

✅ Wins:
<b>{state["wins"]}</b>

❌ Losses:
<b>{state["losses"]}</b>

🎯 Win Rate:
<b>{win_rate():.1f}%</b>

🔥 Consecutive Losses:
<b>{state["consecutive_losses"]}</b>

━━━━━━━━━━━━━━━━━━━━

⭐ Min Score:
<b>{config["min_score"]}</b>

🟢 Buy Pressure:
<b>{config["min_buy_pressure"]:.0f}%+</b>

💧 Liquidity:
<b>${config["min_liquidity"]:,.0f}+</b>

📊 M5 Volume:
<b>${config["min_m5_volume"]:,.0f}+</b>

📈 M5:
<b>{config["min_m5_change"]:.0f}% تا +{config["max_m5_change"]:.0f}%</b>

━━━━━━━━━━━━━━━━━━━━

🎯 TP:
<b>+{config["take_profit"] * 100:.0f}%</b>

🛑 SL:
<b>-{config["stop_loss"] * 100:.0f}%</b>

📈 Trailing:
<b>+{config["trailing_start"] * 100:.0f}% / -{config["trailing_distance"] * 100:.0f}%</b>

🛡️ Risk:
<b>{config["risk_per_trade"] * 100:.0f}%</b>

⏱️ Scan:
<b>{config["scan_seconds"]}s</b>

━━━━━━━━━━━━━━━━━━━━

🕐 Last Scan:
{state["last_scan"] or "-"}

━━━━━━━━━━━━━━━━━━━━
"""


# ============================================================
# SEND DASHBOARD
# ============================================================

def send_dashboard(chat_id):

    state[
        "chat_id"
    ] = chat_id

    msg = bot.send_message(
        chat_id,
        dashboard_text(),
        reply_markup=main_menu()
    )

    state[
        "dashboard_message_id"
    ] = msg.message_id

    save_state()


def update_dashboard():

    chat_id = state.get(
        "chat_id"
    )

    message_id = state.get(
        "dashboard_message_id"
    )

    if not chat_id or not message_id:
        return

    try:

        bot.edit_message_text(
            dashboard_text(),
            chat_id,
            message_id
        )

    except Exception:
        pass


# ============================================================
# BUY MESSAGE
# ============================================================

def send_buy(
    t,
    position
):

    chat_id = state.get(
        "chat_id"
    )

    if not chat_id:
        return

    bot.send_message(
        chat_id,
        f"""
<b>🚨 PAPER BUY V4</b>

🪙 <b>{t["symbol"]}</b>

⭐ Score:
<b>{t["score"]}/100</b>

💵 Price:
${t["price"]:.10f}

💧 Liquidity:
${t["liquidity"]:,.0f}

📊 M5 Volume:
${t["volume"]:,.2f}

🟢 Buy Pressure:
{t["buy_pressure"]:.1f}%

📈 M5:
{t["m5"]:+.2f}%

💰 Position:
${position:.4f}

🛡️ Risk:
{config["risk_per_trade"] * 100:.0f}%

🕐 {now_utc()}
"""
    )


# ============================================================
# SELL MESSAGE
# ============================================================

def send_sell(trade):

    chat_id = state.get(
        "chat_id"
    )

    if not chat_id:
        return

    pnl = num(
        trade[
            "pnl"
        ]
    )

    pct = num(
        trade[
            "return_percent"
        ]
    )

    emoji = (
        "🟢"
        if pnl >= 0
        else "🔴"
    )

    extra = ""

    if (
        trade[
            "exit_reason"
        ]
        == "STOP LOSS"
    ):

        extra = f"""
🛑 Stop Price:
${num(trade["stop_price"]):.10f}

📍 Market Price:
${num(trade["market_price_at_exit"]):.10f}

📐 Slippage:
{num(trade["slippage_percent"]):+.2f}%
"""

    bot.send_message(
        chat_id,
        f"""
<b>{emoji} PAPER SELL V4</b>

🪙 <b>{trade["symbol"]}</b>

💰 PnL:
<b>{pnl:+.4f} USD</b>

📊 Return:
<b>{pct:+.2f}%</b>

🎯 Reason:
<b>{trade["exit_reason"]}</b>

💵 Cash:
<b>{state["balance"]:.4f}</b>

📊 Equity:
<b>{current_equity():.4f}</b>
{extra}
🕐 {now_utc()}
"""
    )


# ============================================================
# TOP HUNTS
# ============================================================

def send_top(chat_id):

    hunts = state[
        "top_hunts"
    ]

    if not hunts:

        bot.send_message(
            chat_id,
            "🔎 هنوز شکار جدیدی پیدا نشده.",
            reply_markup=main_menu()
        )

        return

    text = "<b>🦈 TOP HUNTS V4</b>\n\n"

    for i, t in enumerate(
        hunts[:10],
        1
    ):

        valid = check_entry(
            t
        )

        signal = (
            "🟢 VALID"
            if valid
            else "⚪ LOW FILTER"
        )

        text += f"""
<b>#{i} 🪙 {t["symbol"]}</b>

⭐ Score: {t["score"]}/100
💵 Price: ${t["price"]:.10f}
💧 Liquidity: ${t["liquidity"]:,.0f}
📊 M5 Volume: ${t["volume"]:,.2f}

🛒 Buys: {t["buys"]}
📉 Sells: {t["sells"]}

🟢 Buy Pressure:
{t["buy_pressure"]:.1f}%

📈 M5:
{t["m5"]:+.2f}%

🚦 Signal:
<b>{signal}</b>

━━━━━━━━━━━━━━━━━━━━
"""

    bot.send_message(
        chat_id,
        text,
        reply_markup=main_menu()
    )


# ============================================================
# OPEN TRADES
# ============================================================

def send_open(chat_id):

    trades = state[
        "open_trades"
    ]

    if not trades:

        bot.send_message(
            chat_id,
            "📂 هیچ معامله بازی نداریم.",
            reply_markup=main_menu()
        )

        return

    text = "<b>📂 OPEN TRADES V4</b>\n\n"

    for trade in trades:

        entry = num(
            trade[
                "entry_price"
            ]
        )

        current = num(
            trade.get(
                "current_price",
                entry
            )
        )

        pct = (
            (
                current
                - entry
            )
            / entry
        ) * 100

        text += f"""
🪙 <b>{trade["symbol"]}</b>

💵 Entry:
${entry:.10f}

📍 Current:
${current:.10f}

📊 Return:
<b>{pct:+.2f}%</b>

💰 Position:
${num(trade["position"]):.4f}

━━━━━━━━━━━━━━━━━━━━
"""

    bot.send_message(
        chat_id,
        text,
        reply_markup=main_menu()
    )


# ============================================================
# HISTORY
# ============================================================

def send_history(chat_id):

    trades = state[
        "closed_trades"
    ]

    if not trades:

        bot.send_message(
            chat_id,
            "📜 هنوز معامله‌ای بسته نشده.",
            reply_markup=main_menu()
        )

        return

    text = "<b>📜 HISTORY V4</b>\n\n"

    for trade in trades[-15:]:

        pnl = num(
            trade[
                "pnl"
            ]
        )

        pct = num(
            trade[
                "return_percent"
            ]
        )

        emoji = (
            "🟢"
            if pnl >= 0
            else "🔴"
        )

        text += f"""
{emoji} <b>{trade["symbol"]}</b>

💰 PnL:
{pnl:+.4f} USD

📊 Return:
{pct:+.2f}%

🎯 {trade["exit_reason"]}

🕐 {trade["exit_time"]}

━━━━━━━━━━━━━━━━━━━━
"""

    bot.send_message(
        chat_id,
        text,
        reply_markup=main_menu()
    )


# ============================================================
# SETTINGS
# ============================================================

def send_settings(chat_id):

    bot.send_message(
        chat_id,
        settings_text(),
        reply_markup=settings_menu()
    )


# ============================================================
# RESET PAPER
# ============================================================

def reset_paper():

    state["balance"] = START_BALANCE
    state["starting_balance"] = START_BALANCE

    state["open_trades"] = []
    state["closed_trades"] = []

    state["wins"] = 0
    state["losses"] = 0

    state["total_pnl"] = 0.0

    state["consecutive_losses"] = 0
    state["paused_until"] = 0

    state["cooldowns"] = {}

    save_state()


# ============================================================
# TELEGRAM COMMANDS
# ============================================================

@bot.message_handler(
    commands=["start"]
)
def command_start(message):

    state[
        "chat_id"
    ] = message.chat.id

    save_state()

    bot.send_message(
        message.chat.id,
        """
<b>🦈 SOLANA HUNTER V4</b>

ربات با موفقیت وصل شد. 🤖

🧪 حالت:
<b>PAPER TRADING</b>

از منوی پایین صفحه می‌تونی
داشبورد، شکارها، معاملات،
تاریخچه و تنظیمات رو ببینی.
""",
        reply_markup=main_menu()
    )

    send_dashboard(
        message.chat.id
    )


@bot.message_handler(
    commands=["dashboard"]
)
def command_dashboard(message):

    state[
        "chat_id"
    ] = message.chat.id

    save_state()

    send_dashboard(
        message.chat.id
    )


@bot.message_handler(
    commands=["top"]
)
def command_top(message):

    send_top(
        message.chat.id
    )


@bot.message_handler(
    commands=["open"]
)
def command_open(message):

    send_open(
        message.chat.id
    )


@bot.message_handler(
    commands=["history"]
)
def command_history(message):

    send_history(
        message.chat.id
    )


@bot.message_handler(
    commands=["settings"]
)
def command_settings(message):

    send_settings(
        message.chat.id
    )


# ============================================================
# BOTTOM MENU HANDLER
# ============================================================

@bot.message_handler(
    func=lambda message: True
)
def menu_handler(message):

    text = message.text or ""

    state[
        "chat_id"
    ] = message.chat.id

    save_state()

    if text == "🦈 داشبورد":

        send_dashboard(
            message.chat.id
        )

    elif text == "🎯 شکارها":

        send_top(
            message.chat.id
        )

    elif text == "📂 معاملات باز":

        send_open(
            message.chat.id
        )

    elif text == "📜 تاریخچه":

        send_history(
            message.chat.id
        )

    elif text == "⚙️ تنظیمات":

        send_settings(
            message.chat.id
        )

    elif text == "⏸️ توقف / ▶️ ادامه":

        config["enabled"] = (
            not config["enabled"]
        )

        save_config()

        status = (
            "🟢 ربات فعال شد."
            if config["enabled"]
            else "⏸️ ربات متوقف شد."
        )

        bot.send_message(
            message.chat.id,
            status,
            reply_markup=main_menu()
        )

    elif text == "🔄 ریست Paper":

        reset_paper()

        bot.send_message(
            message.chat.id,
            f"""
<b>🔄 PAPER RESET</b>

💵 Balance:
<b>${START_BALANCE:.4f}</b>

📂 Open:
<b>0</b>

🔢 Closed:
<b>0</b>

📊 PnL:
<b>$0.0000</b>
""",
            reply_markup=main_menu()
        )

    elif text == "ℹ️ وضعیت":

        bot.send_message(
            message.chat.id,
            dashboard_text(),
            reply_markup=main_menu()
        )


# ============================================================
# SETTINGS CALLBACKS
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
    call.data.startswith("set_")
    or call.data == "reset_config"
)
def settings_callback(call):

    chat_id = call.message.chat.id

    data = call.data

    if data == "reset_config":

        config.clear()

        config.update(
            DEFAULT_CONFIG
        )

        save_config()

        bot.answer_callback_query(
            call.id,
            "تنظیمات به حالت پیش‌فرض برگشت."
        )

        bot.send_message(
            chat_id,
            settings_text(),
            reply_markup=settings_menu()
        )

        return

    prompts = {

        "set_score":
            "⭐ حداقل Score را بفرست.\nمثلاً: 75",

        "set_pressure":
            "🟢 حداقل Buy Pressure را بفرست.\nمثلاً: 60",

        "set_liquidity":
            "💧 حداقل Liquidity را به دلار بفرست.\nمثلاً: 25000",

        "set_volume":
            "📊 حداقل M5 Volume را به دلار بفرست.\nمثلاً: 10000",

        "set_tp":
            "🎯 Take Profit را به درصد بفرست.\nمثلاً: 15",

        "set_sl":
            "🛑 Stop Loss را به درصد بفرست.\nمثلاً: 8",

        "set_trailing":
            "📈 فاصله Trailing را به درصد بفرست.\nمثلاً: 5",

        "set_risk":
            "🛡️ Risk هر معامله را به درصد بفرست.\nمثلاً: 10",

        "set_max_trades":
            "📂 حداکثر معاملات باز را بفرست.\nمثلاً: 2",

        "set_scan":
            "⏱️ فاصله اسکن را به ثانیه بفرست.\nمثلاً: 15"
    }

    state[
        "waiting_setting"
    ] = data

    save_state()

    bot.answer_callback_query(
        call.id
    )

    bot.send_message(
        chat_id,
        prompts.get(
            data,
            "مقدار جدید را بفرست."
        ),
        reply_markup=main_menu()
    )


# ============================================================
# SETTING VALUE HANDLER
# ============================================================

@bot.message_handler(
    func=lambda message:
    "waiting_setting" in state
)
def setting_value(message):

    key = state.pop(
        "waiting_setting"
    )

    raw = (
        message.text
        or ""
    ).strip()

    try:

        value = float(
            raw.replace(
                "%",
                ""
            )
        )

        if key == "set_score":

            value = int(
                max(
                    0,
                    min(
                        100,
                        value
                    )
                )
            )

            config[
                "min_score"
            ] = value

        elif key == "set_pressure":

            config[
                "min_buy_pressure"
            ] = max(
                0,
                min(
                    100,
                    value
                )
            )

        elif key == "set_liquidity":

            config[
                "min_liquidity"
            ] = max(
                0,
                value
            )

        elif key == "set_volume":

            config[
                "min_m5_volume"
            ] = max(
                0,
                value
            )

        elif key == "set_tp":

            config[
                "take_profit"
            ] = max(
                0.01,
                min(
                    1.0,
                    value / 100
                )
            )

        elif key == "set_sl":

            config[
                "stop_loss"
            ] = max(
                0.01,
                min(
                    0.5,
                    value / 100
                )
            )

        elif key == "set_trailing":

            config[
                "trailing_distance"
            ] = max(
                0.01,
                min(
                    0.5,
                    value / 100
                )
            )

        elif key == "set_risk":

            config[
                "risk_per_trade"
            ] = max(
                0.01,
                min(
                    0.25,
                    value / 100
                )
            )

        elif key == "set_max_trades":

            config[
                "max_open_trades"
            ] = int(
                max(
                    1,
                    min(
                        10,
                        value
                    )
                )
            )

        elif key == "set_scan":

            config[
                "scan_seconds"
            ] = int(
                max(
                    5,
                    min(
                        300,
                        value
                    )
                )
            )

        else:

            raise ValueError(
                "Unknown setting"
            )

        save_config()

        bot.send_message(
            message.chat.id,
            "✅ تنظیمات با موفقیت ذخیره شد.",
            reply_markup=main_menu()
        )

        send_settings(
            message.chat.id
        )

    except Exception:

        bot.send_message(
            message.chat.id,
            """
❌ مقدار نامعتبر است.

یک عدد ساده بفرست.
مثلاً:

75
60
25000
15
8
""",
            reply_markup=main_menu()
        )

        state[
            "waiting_setting"
        ] = key


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        """
============================================================
🦈 SOLANA HUNTER V4
============================================================

🧪 PAPER TRADING ONLY

Telegram:
🟢 ENABLED

Bottom Menu:
🟢 ENABLED

Settings:
🟢 ENABLED

Real Trading:
🔴 DISABLED

============================================================
"""
    )

    load_config()
    load_state()

    # --------------------------------------------------------
    # Trading engine
    # --------------------------------------------------------

    engine_thread = threading.Thread(
        target=trading_engine,
        daemon=True
    )

    engine_thread.start()

    print(
        "🟢 TRADING ENGINE STARTED"
    )

    # --------------------------------------------------------
    # Telegram
    # --------------------------------------------------------

    while True:

        try:

            bot.remove_webhook()

            bot.infinity_polling(
                timeout=30,
                long_polling_timeout=30,
                skip_pending=True
            )

        except Exception as e:

            print(
                "TELEGRAM ERROR:",
                e
            )

            time.sleep(
                10
            )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    main()
