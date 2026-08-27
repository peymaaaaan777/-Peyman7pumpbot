import os
import time
import json
import threading
from datetime import datetime, timezone

import requests
import telebot
from telebot import types


# ============================================================
# 🦈 SOLANA HUNTER V6
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
    "User-Agent": "SolanaHunterV6/1.0"
})


DEX_API = "https://api.dexscreener.com"

STATE_FILE = "paper_state_v6.json"
CONFIG_FILE = "bot_config_v6.json"

START_BALANCE = 3.5015


# ============================================================
# CONFIG
# ============================================================

DEFAULT_CONFIG = {

    # Entry
    "min_score": 65,
    "min_buy_pressure": 60.0,
    "min_liquidity": 20000.0,
    "min_m5_volume": 10000.0,

    "min_m5_change": -5.0,
    "max_m5_change": 12.0,

    # Exit
    "take_profit": 0.15,
    "stop_loss": 0.08,

    # Profit lock
    "profit_lock_trigger": 0.08,

    # Remaining position
    "trailing_start": 0.10,
    "trailing_distance": 0.05,

    # Risk
    "risk_per_trade": 0.10,

    # Position
    "max_open_trades": 2,

    # Scanner
    "scan_seconds": 15,

    # Re-entry
    "cooldown_seconds": 600,

    # Liquidity protection
    "min_liquidity_ratio": 0.70,

    # Slippage simulation
    "max_slippage": 0.03,

    # Crash
    "crash_m5": -8.0,

    # Loss protection
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

    "locked_profit": 0.0,

    "consecutive_losses": 0,

    "paused_until": 0,

    "cooldowns": {},

    "top_hunts": [],

    "last_scan": None,

    "chat_id": None,

    "dashboard_message_id": None,

    "waiting_setting": None
}


state_lock = threading.Lock()


# ============================================================
# HELPERS
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
# SAVE / LOAD
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


def save_state():

    try:

        with state_lock:

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
# TELEGRAM MENU
# ============================================================

def main_menu():

    menu = types.ReplyKeyboardMarkup(
        resize_keyboard=True
    )

    menu.row(
        types.KeyboardButton(
            "🦈 داشبورد"
        ),
        types.KeyboardButton(
            "🎯 شکارها"
        )
    )

    menu.row(
        types.KeyboardButton(
            "📂 معاملات باز"
        ),
        types.KeyboardButton(
            "📜 تاریخچه"
        )
    )

    menu.row(
        types.KeyboardButton(
            "⚙️ تنظیمات"
        ),
        types.KeyboardButton(
            "⏸️ توقف / ▶️ ادامه"
        )
    )

    menu.row(
        types.KeyboardButton(
            "🔄 ریست Paper"
        ),
        types.KeyboardButton(
            "ℹ️ وضعیت"
        )
    )

    return menu


# ============================================================
# SETTINGS MENU
# ============================================================

def settings_menu():

    markup = types.InlineKeyboardMarkup(
        row_width=2
    )

    buttons = [

        ("⭐ Score", "set_score"),
        ("🟢 Buy Pressure", "set_pressure"),

        ("💧 Liquidity", "set_liquidity"),
        ("📊 M5 Volume", "set_volume"),

        ("🎯 Take Profit", "set_tp"),
        ("🛑 Stop Loss", "set_sl"),

        ("🔒 Profit Lock", "set_profit_lock"),
        ("📈 Trailing", "set_trailing"),

        ("🛡️ Risk", "set_risk"),
        ("📂 Max Trades", "set_max_trades"),

        ("⏱️ Scan", "set_scan"),
        ("🚫 Cooldown", "set_cooldown"),

        ("⚡ Max Slippage", "set_slippage"),
        ("💧 Liquidity Protection", "set_liq_ratio")
    ]

    for i in range(
        0,
        len(buttons),
        2
    ):

        row = []

        for label, callback in buttons[
            i:i + 2
        ]:

            row.append(
                types.InlineKeyboardButton(
                    label,
                    callback_data=callback
                )
            )

        markup.row(
            *row
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
<b>⚙️ SOLANA HUNTER V6</b>

━━━━━━━━━━━━━━━━━━━━

⭐ Min Score:
<b>{config["min_score"]}</b>

🟢 Buy Pressure:
<b>{config["min_buy_pressure"]:.0f}%+</b>

💧 Liquidity:
<b>${config["min_liquidity"]:,.0f}+</b>

📊 M5 Volume:
<b>${config["min_m5_volume"]:,.0f}+</b>

📈 Allowed M5:
<b>{config["min_m5_change"]:.0f}% تا +{config["max_m5_change"]:.0f}%</b>

━━━━━━━━━━━━━━━━━━━━

🎯 Take Profit:
<b>+{config["take_profit"] * 100:.0f}%</b>

🛑 Stop Loss:
<b>-{config["stop_loss"] * 100:.0f}%</b>

🔒 Profit Lock:
<b>+{config["profit_lock_trigger"] * 100:.0f}%</b>

📈 Trailing:
<b>+{config["trailing_start"] * 100:.0f}% / -{config["trailing_distance"] * 100:.0f}%</b>

━━━━━━━━━━━━━━━━━━━━

⚡ Max Slippage:
<b>{config["max_slippage"] * 100:.0f}%</b>

💧 Liquidity Protection:
<b>{config["min_liquidity_ratio"] * 100:.0f}%</b>

🛡️ Risk:
<b>{config["risk_per_trade"] * 100:.0f}%</b>

📂 Max Trades:
<b>{config["max_open_trades"]}</b>

⏱️ Scan:
<b>{config["scan_seconds"]}s</b>

━━━━━━━━━━━━━━━━━━━━

🧪 Mode:
<b>PAPER TRADING</b>

━━━━━━━━━━━━━━━━━━━━
"""


# ============================================================
# DEXSCREENER
# ============================================================

def latest_solana_tokens():

    found = {}

    urls = [

        f"{DEX_API}/token-boosts/latest/v1",

        f"{DEX_API}/token-profiles/latest/v1"
    ]

    for url in urls:

        try:

            r = session.get(
                url,
                timeout=10
            )

            if r.status_code != 200:
                continue

            data = r.json()

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

                    found[
                        address
                    ] = item

        except Exception as e:

            print(
                "TOKEN DISCOVERY:",
                e
            )

    return list(
        found.values()
    )


def get_pairs(address):

    try:

        url = (
            f"{DEX_API}/latest/dex/tokens/"
            f"{address}"
        )

        r = session.get(
            url,
            timeout=10
        )

        if r.status_code != 200:
            return []

        data = r.json()

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
# ANALYSIS
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

        pressure = 0

        if total > 0:

            pressure = (
                buys
                / total
            ) * 100

        m5 = num(
            pair.get(
                "priceChange",
                {}
            ).get(
                "m5"
            )
        )

        # ====================================================
        # SCORE
        # ====================================================

        score = 0

        if liquidity >= 100000:
            score += 20

        elif liquidity >= 50000:
            score += 17

        elif liquidity >= 30000:
            score += 14

        elif liquidity >= 20000:
            score += 10

        if volume >= 100000:
            score += 20

        elif volume >= 50000:
            score += 17

        elif volume >= 25000:
            score += 14

        elif volume >= 10000:
            score += 10

        if pressure >= 85:
            score += 25

        elif pressure >= 75:
            score += 22

        elif pressure >= 65:
            score += 18

        elif pressure >= 60:
            score += 14

        if total >= 500:
            score += 15

        elif total >= 250:
            score += 13

        elif total >= 100:
            score += 10

        elif total >= 50:
            score += 7

        if 0 <= m5 <= 5:
            score += 15

        elif 5 < m5 <= 10:
            score += 12

        elif 10 < m5 <= 12:
            score += 8

        elif -3 <= m5 < 0:
            score += 5

        if m5 < -5:
            score -= 20

        if m5 > 12:
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
            "ANALYSIS ERROR:",
            e
        )

        return None


# ============================================================
# ENTRY FILTER
# ============================================================

def valid_entry(t):

    if t["score"] < config[
        "min_score"
    ]:
        return False

    if t["buy_pressure"] < config[
        "min_buy_pressure"
    ]:
        return False

    if t["liquidity"] < config[
        "min_liquidity"
    ]:
        return False

    if t["volume"] < config[
        "min_m5_volume"
    ]:
        return False

    if t["m5"] < config[
        "min_m5_change"
    ]:
        return False

    if t["m5"] > config[
        "max_m5_change"
    ]:
        return False

    if t["m5"] <= config[
        "crash_m5"
    ]:
        return False

    return True


# ============================================================
# FIND TRADE
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
# COOLDOWN
# ============================================================

def on_cooldown(address):

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
        + config[
            "cooldown_seconds"
        ]
    )


# ============================================================
# PAPER BUY
# ============================================================

def paper_buy(t):

    if not config[
        "enabled"
    ]:
        return False

    if time.time() < num(
        state[
            "paused_until"
        ]
    ):
        return False

    if len(
        state[
            "open_trades"
        ]
    ) >= config[
        "max_open_trades"
    ]:
        return False

    if find_trade(
        t["address"]
    ):
        return False

    if on_cooldown(
        t["address"]
    ):
        return False

    if not valid_entry(t):
        return False

    cash = num(
        state[
            "balance"
        ]
    )

    position = (
        cash
        * config[
            "risk_per_trade"
        ]
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

        "entry_liquidity": t[
            "liquidity"
        ],

        "last_liquidity": t[
            "liquidity"
        ],

        "original_position": position,

        "remaining_position": position,

        "principal_returned": 0,

        "locked_profit": 0,

        "partial_closed": False,

        "entry_time": now_utc(),

        "entry_score": t[
            "score"
        ],

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
# PROFIT LOCK
# ============================================================

def execute_profit_lock(
    trade,
    price
):

    if trade[
        "partial_closed"
    ]:
        return False

    entry = num(
        trade[
            "entry_price"
        ]
    )

    current = num(
        price
    )

    if entry <= 0:
        return False

    change = (
        current
        - entry
    ) / entry

    if change < config[
        "profit_lock_trigger"
    ]:
        return False

    original = num(
        trade[
            "original_position"
        ]
    )

    if original <= 0:
        return False

    # Current value of original position
    current_value = (
        original
        * (
            1
            + change
        )
    )

    # Return original principal
    principal = min(
        original,
        current_value
    )

    profit = max(
        0,
        current_value
        - principal
    )

    remaining = max(
        0,
        current_value
        - principal
    )

    trade[
        "principal_returned"
    ] = principal

    trade[
        "locked_profit"
    ] = profit

    trade[
        "remaining_position"
    ] = remaining

    trade[
        "partial_closed"
    ] = True

    state[
        "balance"
    ] += principal

    state[
        "locked_profit"
    ] += profit

    save_state()

    send_profit_lock(
        trade,
        principal,
        profit,
        price
    )

    return True


# ============================================================
# SELL
# ============================================================

def close_trade(
    trade,
    market_price,
    reason,
    simulated_slippage=0
):

    entry = num(
        trade[
            "entry_price"
        ]
    )

    current = num(
        market_price
    )

    original = num(
        trade[
            "original_position"
        ]
    )

    remaining = num(
        trade[
            "remaining_position"
        ]
    )

    if entry <= 0:
        return

    change = (
        current
        - entry
    ) / entry

    remaining_pnl = (
        remaining
        * change
    )

    final_value = (
        remaining
        + remaining_pnl
    )

    principal = num(
        trade[
            "principal_returned"
        ]
    )

    total_pnl = (
        principal
        + final_value
        - original
    )

    state[
        "balance"
    ] += final_value

    state[
        "total_pnl"
    ] += total_pnl

    if total_pnl >= 0:

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

    trade[
        "exit_price"
    ] = current

    trade[
        "final_value"
    ] = final_value

    trade[
        "pnl"
    ] = total_pnl

    trade[
        "return_percent"
    ] = (

        total_pnl
        / original
        * 100

        if original > 0

        else 0
    )

    trade[
        "exit_reason"
    ] = reason

    trade[
        "slippage"
    ] = simulated_slippage

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

            trade[
                "last_liquidity"
            ] = t[
                "liquidity"
            ]

            entry = num(
                trade[
                    "entry_price"
                ]
            )

            highest = num(
                trade.get(
                    "highest_price",
                    entry
                )
            )

            if current > highest:

                highest = current

                trade[
                    "highest_price"
                ] = highest

            change = (
                current
                - entry
            ) / entry

            # =================================================
            # LIQUIDITY SHOCK
            # =================================================

            entry_liq = num(
                trade[
                    "entry_liquidity"
                ]
            )

            current_liq = num(
                t[
                    "liquidity"
                ]
            )

            if entry_liq > 0:

                liquidity_ratio = (
                    current_liq
                    / entry_liq
                )

                if (
                    liquidity_ratio
                    < config[
                        "min_liquidity_ratio"
                    ]
                ):

                    close_trade(

                        trade,

                        current,

                        "LIQUIDITY SHOCK"

                    )

                    continue

            # =================================================
            # PROFIT LOCK
            # =================================================

            if (
                not trade[
                    "partial_closed"
                ]
                and change
                >= config[
                    "profit_lock_trigger"
                ]
            ):

                execute_profit_lock(
                    trade,
                    current
                )

            # =================================================
            # STOP LOSS
            # =================================================

            if not trade[
                "partial_closed"
            ]:

                stop_price = (

                    entry
                    * (
                        1
                        - config[
                            "stop_loss"
                        ]
                    )
                )

                if current <= stop_price:

                    close_trade(

                        trade,

                        current,

                        "STOP LOSS",

                        0
                    )

                    continue

            # =================================================
            # TAKE PROFIT
            # =================================================

            if (
                not trade[
                    "partial_closed"
                ]
                and change
                >= config[
                    "take_profit"
                ]
            ):

                close_trade(

                    trade,

                    current,

                    "TAKE PROFIT",

                    0
                )

                continue

            # =================================================
            # TRAILING AFTER PROFIT LOCK
            # =================================================

            if (
                trade[
                    "partial_closed"
                ]
                and change
                >= config[
                    "trailing_start"
                ]
            ):

                trail = (

                    highest
                    * (
                        1
                        - config[
                            "trailing_distance"
                        ]
                    )
                )

                if current <= trail:

                    close_trade(

                        trade,

                        current,

                        "TRAILING PROFIT",

                        0
                    )

                    continue

        except Exception as e:

            print(
                "MANAGE ERROR:",
                e
            )


# ============================================================
# MARKET SCANNER
# ============================================================

def scan_market():

    results = []

    tokens = (
        latest_solana_tokens()
    )

    seen = set()

    for item in tokens[:80]:

        address = item.get(
            "tokenAddress"
        )

        if not address:
            continue

        if address in seen:
            continue

        seen.add(
            address
        )

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
            0.08
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
# ENGINE
# ============================================================

def trading_engine():

    print(
        "🟢 V6 ENGINE STARTED"
    )

    while True:

        try:

            manage_trades()

            results = scan_market()

            if (
                config[
                    "enabled"
                ]
                and time.time()
                >= num(
                    state[
                        "paused_until"
                    ]
                )
            ):

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
# EQUITY
# ============================================================

def equity():

    total = num(
        state[
            "balance"
        ]
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

        remaining = num(
            trade.get(
                "remaining_position",
                0
            )
        )

        if entry <= 0:
            continue

        change = (
            current
            - entry
        ) / entry

        total += (
            remaining
            * (
                1
                + change
            )
        )

    return total


def win_rate():

    total = (

        state[
            "wins"
        ]

        +

        state[
            "losses"
        ]
    )

    if total == 0:
        return 0

    return (
        state[
            "wins"
        ]
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
            equity()
            - start
        )
        / start

    ) * 100


# ============================================================
# DASHBOARD
# ============================================================

def dashboard_text():

    eq = equity()

    pnl = (

        eq
        - num(
            state[
                "starting_balance"
            ]
        )
    )

    if not config[
        "enabled"
    ]:

        status = "⏸️ PAUSED"

    elif time.time() < num(
        state[
            "paused_until"
        ]
    ):

        status = "🟡 LOSS PROTECTION"

    else:

        status = "🟢 ONLINE"

    return f"""
<b>🦈 SOLANA HUNTER V6</b>

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

🔒 Locked Profit:
<b>+{state["locked_profit"]:.4f} USD</b>

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

🔒 Lock:
<b>+{config["profit_lock_trigger"] * 100:.0f}%</b>

📈 Trail:
<b>{config["trailing_distance"] * 100:.0f}%</b>

⚡ Max Slippage:
<b>{config["max_slippage"] * 100:.0f}%</b>

━━━━━━━━━━━━━━━━━━━━

🕐 Last Scan:
{state["last_scan"] or "-"}

━━━━━━━━━━━━━━━━━━━━
"""


# ============================================================
# TELEGRAM MESSAGES
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
<b>🚨 PAPER BUY V6</b>

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

🔒 Profit Lock:
+{config["profit_lock_trigger"] * 100:.0f}%

🕐 {now_utc()}
"""
    )


def send_profit_lock(
    trade,
    principal,
    profit,
    price
):

    chat_id = state.get(
        "chat_id"
    )

    if not chat_id:
        return

    bot.send_message(

        chat_id,

        f"""
<b>🔒 PROFIT LOCK V6</b>

🪙 <b>{trade["symbol"]}</b>

📍 Price:
${price:.10f}

💵 Principal Returned:
<b>+${principal:.4f}</b>

💰 Locked Profit:
<b>+${profit:.4f}</b>

📂 Remaining:
<b>${trade["remaining_position"]:.4f}</b>

🚀 اصل سرمایه آزاد شد.
باقی پوزیشن با سود خودش ادامه دارد.

🕐 {now_utc()}
"""
    )


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

    slippage = num(
        trade.get(
            "slippage",
            0
        )
    )

    bot.send_message(

        chat_id,

        f"""
<b>{emoji} PAPER SELL V6</b>

🪙 <b>{trade["symbol"]}</b>

💰 Total PnL:
<b>{pnl:+.4f} USD</b>

📊 Return:
<b>{pct:+.2f}%</b>

🎯 Reason:
<b>{trade["exit_reason"]}</b>

🔒 Principal Returned:
<b>${num(trade["principal_returned"]):.4f}</b>

💰 Locked Profit:
<b>+${num(trade["locked_profit"]):.4f}</b>

⚡ Slippage:
<b>{slippage * 100:.2f}%</b>

💵 Cash:
<b>${state["balance"]:.4f}</b>

📊 Equity:
<b>${equity():.4f}</b>

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

    text = (
        "<b>🦈 TOP HUNTS V6</b>\n\n"
    )

    for i, t in enumerate(
        hunts[:10],
        1
    ):

        valid = valid_entry(
            t
        )

        signal = (
            "🟢 READY"
            if valid
            else "⚪ FILTERED"
        )

        text += f"""
<b>#{i} 🪙 {t["symbol"]}</b>

⭐ Score:
{t["score"]}/100

💵 Price:
${t["price"]:.10f}

💧 Liquidity:
${t["liquidity"]:,.0f}

📊 M5 Volume:
${t["volume"]:,.2f}

🛒 Buys:
{t["buys"]}

📉 Sells:
{t["sells"]}

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

    text = (
        "<b>📂 OPEN TRADES V6</b>\n\n"
    )

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

        locked = (
            "🔒 YES"
            if trade[
                "partial_closed"
            ]
            else "⏳ NO"
        )

        text += f"""
🪙 <b>{trade["symbol"]}</b>

💵 Entry:
${entry:.10f}

📍 Current:
${current:.10f}

📊 Return:
<b>{pct:+.2f}%</b>

💰 Original:
${num(trade["original_position"]):.4f}

💵 Remaining:
${num(trade["remaining_position"]):.4f}

🔒 Principal:
<b>{locked}</b>

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

    text = (
        "<b>📜 HISTORY V6</b>\n\n"
    )

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

🔒 Locked:
+${num(trade["locked_profit"]):.4f}

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
# DASHBOARD
# ============================================================

def send_dashboard(chat_id):

    state[
        "chat_id"
    ] = chat_id

    save_state()

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
# SETTINGS
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
    call.data.startswith(
        "set_"
    )
    or call.data == "reset_config"
)
def settings_callback(call):

    chat_id = call.message.chat.id

    if call.data == "reset_config":

        config.clear()

        config.update(
            DEFAULT_CONFIG
        )

        save_config()

        bot.answer_callback_query(
            call.id,
            "تنظیمات ریست شد."
        )

        bot.send_message(

            chat_id,

            settings_text(),

            reply_markup=settings_menu()
        )

        return

    prompts = {

        "set_score":
            "⭐ حداقل Score را بفرست.\nمثلاً 65",

        "set_pressure":
            "🟢 Buy Pressure را بفرست.\nمثلاً 60",

        "set_liquidity":
            "💧 حداقل Liquidity را بفرست.\nمثلاً 20000",

        "set_volume":
            "📊 حداقل M5 Volume را بفرست.\nمثلاً 10000",

        "set_tp":
            "🎯 Take Profit درصدی.\nمثلاً 15",

        "set_sl":
            "🛑 Stop Loss درصدی.\nمثلاً 8",

        "set_profit_lock":
            "🔒 Profit Lock درصدی.\nمثلاً 8",

        "set_trailing":
            "📈 Trailing Distance درصدی.\nمثلاً 5",

        "set_risk":
            "🛡️ Risk درصدی.\nمثلاً 10",

        "set_max_trades":
            "📂 حداکثر معاملات باز.\nمثلاً 2",

        "set_scan":
            "⏱️ فاصله اسکن بر حسب ثانیه.\nمثلاً 15",

        "set_cooldown":
            "🚫 Cooldown بر حسب ثانیه.\nمثلاً 600",

        "set_slippage":
            "⚡ Max Slippage درصدی.\nمثلاً 3",

        "set_liq_ratio":
            "💧 حداقل نسبت نقدینگی را درصدی بفرست.\nمثلاً 70"
    }

    state[
        "waiting_setting"
    ] = call.data

    save_state()

    bot.answer_callback_query(
        call.id
    )

    bot.send_message(

        chat_id,

        prompts.get(
            call.data,
            "عدد جدید را بفرست."
        ),

        reply_markup=main_menu()
    )


@bot.message_handler(
    func=lambda message:
    state.get(
        "waiting_setting"
    ) is not None
)
def setting_value(message):

    key = state.get(
        "waiting_setting"
    )

    try:

        value = float(
            (
                message.text
                or ""
            )
            .replace(
                "%",
                ""
            )
            .strip()
        )

        if key == "set_score":

            config[
                "min_score"
            ] = int(
                max(
                    0,
                    min(
                        100,
                        value
                    )
                )
            )

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
                    1,
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

        elif key == "set_profit_lock":

            config[
                "profit_lock_trigger"
            ] = max(
                0.01,
                min(
                    1,
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

        elif key == "set_cooldown":

            config[
                "cooldown_seconds"
            ] = int(
                max(
                    0,
                    min(
                        86400,
                        value
                    )
                )
            )

        elif key == "set_slippage":

            config[
                "max_slippage"
            ] = max(
                0.005,
                min(
                    0.25,
                    value / 100
                )
            )

        elif key == "set_liq_ratio":

            config[
                "min_liquidity_ratio"
            ] = max(
                0.1,
                min(
                    1,
                    value / 100
                )
            )

        else:

            raise ValueError()

        state[
            "waiting_setting"
        ] = None

        save_config()
        save_state()

        bot.send_message(

            message.chat.id,

            "✅ تنظیم ذخیره شد.",

            reply_markup=main_menu()
        )

        send_settings(
            message.chat.id
        )

    except Exception:

        bot.send_message(

            message.chat.id,

            "❌ عدد نامعتبر است. دوباره فقط عدد بفرست.",

            reply_markup=main_menu()
        )


def send_settings(chat_id):

    bot.send_message(

        chat_id,

        settings_text(),

        reply_markup=settings_menu()
    )


# ============================================================
# START
# ============================================================

@bot.message_handler(
    commands=["start"]
)
def start_command(message):

    state[
        "chat_id"
    ] = message.chat.id

    save_state()

    bot.send_message(

        message.chat.id,

        """
<b>🦈 SOLANA HUNTER V6</b>

🤖 ربات با موفقیت متصل شد.

🧪 PAPER TRADING

🔒 Profit Lock
⚡ Slippage Protection
💧 Liquidity Protection
🚫 Cooldown
🛑 Stop Loss
📈 Trailing Profit

همه از منوی پایین قابل کنترل هستند.
""",

        reply_markup=main_menu()
    )

    send_dashboard(
        message.chat.id
    )


# ============================================================
# COMMANDS
# ============================================================

@bot.message_handler(
    commands=["dashboard"]
)
def dashboard_command(message):

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
def top_command(message):

    send_top(
        message.chat.id
    )


@bot.message_handler(
    commands=["open"]
)
def open_command(message):

    send_open(
        message.chat.id
    )


@bot.message_handler(
    commands=["history"]
)
def history_command(message):

    send_history(
        message.chat.id
    )


@bot.message_handler(
    commands=["settings"]
)
def settings_command(message):

    send_settings(
        message.chat.id
    )


# ============================================================
# MENU
# ============================================================

@bot.message_handler(
    func=lambda message:
    True
)
def menu_handler(message):

    text = (
        message.text
        or ""
    )

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

        config[
            "enabled"
        ] = not config[
            "enabled"
        ]

        save_config()

        status = (

            "🟢 ربات فعال شد."

            if config[
                "enabled"
            ]

            else

            "⏸️ ربات متوقف شد."
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

💰 PnL:
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
# RESET
# ============================================================

def reset_paper():

    state[
        "balance"
    ] = START_BALANCE

    state[
        "starting_balance"
    ] = START_BALANCE

    state[
        "open_trades"
    ] = []

    state[
        "closed_trades"
    ] = []

    state[
        "wins"
    ] = 0

    state[
        "losses"
    ] = 0

    state[
        "total_pnl"
    ] = 0

    state[
        "locked_profit"
    ] = 0

    state[
        "consecutive_losses"
    ] = 0

    state[
        "paused_until"
    ] = 0

    state[
        "cooldowns"
    ] = {}

    save_state()


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        """
============================================================
🦈 SOLANA HUNTER V6
============================================================

🧪 PAPER TRADING ONLY

🔒 PROFIT LOCK          🟢
⚡ SLIPPAGE PROTECTION  🟢
💧 LIQUIDITY FILTER     🟢
🚫 COOLDOWN             🟢
📈 TRAILING             🟢
🛑 STOP LOSS            🟢
⚙️ TELEGRAM SETTINGS    🟢

💸 REAL MONEY           🔴 DISABLED

============================================================
"""
    )

    load_config()

    load_state()

    engine = threading.Thread(

        target=trading_engine,

        daemon=True
    )

    engine.start()

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


if __name__ == "__main__":

    main()
