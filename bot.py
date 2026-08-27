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
# PAPER TRADING
# Telegram Dashboard + Scanner + Risk Management
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")


# ============================================================
# CONSTANTS
# ============================================================

DEX_API = "https://api.dexscreener.com"

STATE_FILE = "paper_state_v6.json"
CONFIG_FILE = "bot_config_v6.json"

STARTING_BALANCE = float(
    os.getenv("STARTING_BALANCE", "3.5015")
)


# ============================================================
# TELEGRAM
# ============================================================

bot = telebot.TeleBot(
    BOT_TOKEN,
    parse_mode="HTML"
)

session = requests.Session()

session.headers.update({
    "User-Agent": "SolanaHunterV6/1.0",
    "Accept": "application/json"
})


# ============================================================
# CONFIG
# ============================================================

DEFAULT_CONFIG = {

    "min_score": 60,
    "min_buy_pressure": 60.0,

    "min_liquidity": 30000.0,
    "min_m5_volume": 5000.0,

    "min_m5_change": -5.0,
    "max_m5_change": 15.0,

    "risk_per_trade": 0.10,
    "max_open_trades": 2,

    "take_profit": 0.15,
    "stop_loss": 0.08,

    "profit_lock_trigger": 0.10,
    "profit_lock_percent": 0.50,

    "trailing_start": 0.12,
    "trailing_distance": 0.05,

    "scan_seconds": 30,

    "cooldown_seconds": 600,

    "max_consecutive_losses": 3,
    "loss_pause_seconds": 900,

    "min_trade_sol": 0.005,
    "max_trade_sol": 0.50,

    "enabled": True
}


config = DEFAULT_CONFIG.copy()


# ============================================================
# STATE
# ============================================================

state = {

    "balance_sol": STARTING_BALANCE,

    "starting_balance_sol": STARTING_BALANCE,

    "open_trades": [],

    "closed_trades": [],

    "wins": 0,

    "losses": 0,

    "total_pnl_sol": 0.0,

    "locked_profit_sol": 0.0,

    "consecutive_losses": 0,

    "paused_until": 0,

    "cooldowns": {},

    "top_hunts": [],

    "last_scan": None,

    "chat_id": None
}


lock = threading.Lock()


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

        print("STATE SAVE ERROR:", e)


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

        state.update(saved)

    except Exception as e:

        print("STATE LOAD ERROR:", e)


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

        print("CONFIG SAVE ERROR:", e)


def load_config():

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

        print("CONFIG LOAD ERROR:", e)


# ============================================================
# DEXSCREENER
# ============================================================

def latest_tokens():

    result = {}

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
                    result[address] = item

        except Exception as e:

            print(
                "TOKEN DISCOVERY ERROR:",
                e
            )

    return list(
        result.values()
    )


def get_pairs(address):

    try:

        r = session.get(
            f"{DEX_API}/latest/dex/tokens/{address}",
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
            if p.get("chainId") == "solana"
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

        score = 0

        # Liquidity

        if liquidity >= 100000:
            score += 20

        elif liquidity >= 50000:
            score += 17

        elif liquidity >= 30000:
            score += 14

        # Volume

        if volume >= 100000:
            score += 20

        elif volume >= 50000:
            score += 17

        elif volume >= 25000:
            score += 14

        elif volume >= 15000:
            score += 10

        elif volume >= 5000:
            score += 6

        # Buy pressure

        if pressure >= 80:
            score += 25

        elif pressure >= 70:
            score += 21

        elif pressure >= 60:
            score += 16

        # Transactions

        if total >= 500:
            score += 15

        elif total >= 200:
            score += 13

        elif total >= 100:
            score += 10

        elif total >= 50:
            score += 7

        # Momentum

        if 1 <= m5 <= 8:
            score += 15

        elif 0 <= m5 < 1:
            score += 8

        elif 8 < m5 <= 15:
            score += 10

        if m5 < -5:
            score -= 20

        if m5 > 15:
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
# FILTER
# ============================================================

def valid_entry(t):

    if t["score"] < config["min_score"]:
        return False

    if t["buy_pressure"] < config["min_buy_pressure"]:
        return False

    if t["liquidity"] < config["min_liquidity"]:
        return False

    if t["volume"] < config["min_m5_volume"]:
        return False

    if t["m5"] < config["min_m5_change"]:
        return False

    if t["m5"] > config["max_m5_change"]:
        return False

    if t["price"] <= 0:
        return False

    return True


# ============================================================
# TRADE HELPERS
# ============================================================

def find_trade(address):

    for trade in state["open_trades"]:

        if trade["address"] == address:
            return trade

    return None


def cooldown(address):

    until = num(
        state["cooldowns"].get(
            address,
            0
        )
    )

    return time.time() < until


def set_cooldown(address):

    state["cooldowns"][address] = (
        time.time()
        + config["cooldown_seconds"]
    )


# ============================================================
# PAPER BUY
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
    ) >= config["max_open_trades"]:
        return False

    if find_trade(
        t["address"]
    ):
        return False

    if cooldown(
        t["address"]
    ):
        return False

    if not valid_entry(t):
        return False

    available = max(
        0,
        state["balance_sol"]
    )

    position = (
        available
        * config["risk_per_trade"]
    )

    position = min(
        position,
        config["max_trade_sol"]
    )

    if position < config["min_trade_sol"]:
        return False

    state["balance_sol"] -= position

    trade = {

        "id": str(
            int(
                time.time() * 1000
            )
        ),

        "address": t["address"],

        "symbol": t["symbol"],

        "entry_price": t["price"],

        "current_price": t["price"],

        "highest_price": t["price"],

        "position_sol": position,

        "remaining_percent": 1.0,

        "entry_time": now_utc(),

        "locked": False,

        "locked_profit_sol": 0.0,

        "status": "OPEN"
    }

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

    print(
        f"PAPER BUY: "
        f"{t['symbol']} "
        f"{position:.6f} SOL"
    )

    return True


# ============================================================
# PAPER SELL
# ============================================================

def paper_sell(
    trade,
    percent,
    reason,
    current_price
):

    try:

        entry_price = num(
            trade["entry_price"]
        )

        if entry_price <= 0:
            return False

        change = (
            current_price
            - entry_price
        ) / entry_price

        invested = (
            trade["position_sol"]
            * percent
        )

        returned = (
            invested
            * (1 + change)
        )

        pnl = (
            returned
            - invested
        )

        state[
            "balance_sol"
        ] += returned

        if percent >= 0.999:

            trade[
                "remaining_percent"
            ] = 0

            trade[
                "current_price"
            ] = current_price

            trade[
                "exit_price"
            ] = current_price

            trade[
                "exit_reason"
            ] = reason

            trade[
                "pnl_sol"
            ] = pnl

            trade[
                "return_percent"
            ] = change * 100

            trade[
                "exit_time"
            ] = now_utc()

            trade[
                "status"
            ] = "CLOSED"

            if pnl >= 0:

                state["wins"] += 1

                state[
                    "consecutive_losses"
                ] = 0

            else:

                state["losses"] += 1

                state[
                    "consecutive_losses"
                ] += 1

                set_cooldown(
                    trade["address"]
                )

            state[
                "total_pnl_sol"
            ] += pnl

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
                trade,
                pnl,
                returned,
                reason
            )

        else:

            trade[
                "position_sol"
            ] -= invested

            trade[
                "remaining_percent"
            ] -= percent

            trade[
                "locked"
            ] = True

            trade[
                "locked_profit_sol"
            ] += max(
                0,
                pnl
            )

            state[
                "locked_profit_sol"
            ] += max(
                0,
                pnl
            )

            save_state()

            send_profit_lock(
                trade,
                returned,
                pnl
            )

        return True

    except Exception as e:

        print(
            "SELL ERROR:",
            e
        )

        return False


# ============================================================
# MANAGE TRADES
# ============================================================

def manage_trades():

    for trade in list(
        state["open_trades"]
    ):

        try:

            pairs = get_pairs(
                trade["address"]
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

            if current > num(
                trade["highest_price"]
            ):

                trade[
                    "highest_price"
                ] = current

            entry = num(
                trade["entry_price"]
            )

            change = (
                current - entry
            ) / entry

            # PROFIT LOCK

            if (
                not trade["locked"]
                and change
                >= config[
                    "profit_lock_trigger"
                ]
            ):

                paper_sell(
                    trade,
                    config[
                        "profit_lock_percent"
                    ],
                    "PROFIT LOCK",
                    current
                )

                continue

            # STOP LOSS

            if not trade["locked"]:

                stop = (
                    entry
                    * (
                        1
                        - config[
                            "stop_loss"
                        ]
                    )
                )

                if current <= stop:

                    paper_sell(
                        trade,
                        1.0,
                        "STOP LOSS",
                        current
                    )

                    continue

            # TAKE PROFIT

            if (
                not trade["locked"]
                and change
                >= config[
                    "take_profit"
                ]
            ):

                paper_sell(
                    trade,
                    1.0,
                    "TAKE PROFIT",
                    current
                )

                continue

            # TRAILING

            if (
                trade["locked"]
                and change
                >= config[
                    "trailing_start"
                ]
            ):

                trailing = (
                    trade[
                        "highest_price"
                    ]
                    * (
                        1
                        - config[
                            "trailing_distance"
                        ]
                    )
                )

                if current <= trailing:

                    paper_sell(
                        trade,
                        1.0,
                        "TRAILING PROFIT",
                        current
                    )

        except Exception as e:

            print(
                "MANAGE ERROR:",
                e
            )


# ============================================================
# MARKET SCAN
# ============================================================

def scan_market():

    results = []

    try:

        tokens = latest_tokens()

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
                results.append(t)

            time.sleep(0.1)

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

    except Exception as e:

        print(
            "SCAN ERROR:",
            e
        )

        return []


# ============================================================
# DASHBOARD
# ============================================================

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


def dashboard_text():

    balance = num(
        state["balance_sol"]
    )

    starting = num(
        state["starting_balance_sol"]
    )

    pnl = (
        balance
        - starting
    )

    if not config["enabled"]:

        status = "⏸️ PAUSED"

    elif time.time() < num(
        state["paused_until"]
    ):

        status = "🟡 LOSS PROTECTION"

    else:

        status = "🟢 RUNNING"

    return f"""
<b>🦈 SOLANA HUNTER V6</b>

━━━━━━━━━━━━━━━━━━━━

🧪 <b>PAPER TRADING</b>

🤖 Status:
<b>{status}</b>

━━━━━━━━━━━━━━━━━━━━

💰 Balance:
<b>{balance:.6f} SOL</b>

💵 Starting:
<b>{starting:.6f} SOL</b>

📊 PnL:
<b>{pnl:+.6f} SOL</b>

🔒 Locked Profit:
<b>{state["locked_profit_sol"]:+.6f} SOL</b>

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

🔥 Loss Streak:
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

━━━━━━━━━━━━━━━━━━━━

🎯 TP:
<b>+{config["take_profit"] * 100:.0f}%</b>

🛑 SL:
<b>-{config["stop_loss"] * 100:.0f}%</b>

🔒 Lock:
<b>+{config["profit_lock_trigger"] * 100:.0f}%</b>

📈 Trailing:
<b>{config["trailing_distance"] * 100:.0f}%</b>

🛡️ Risk:
<b>{config["risk_per_trade"] * 100:.0f}%</b>

━━━━━━━━━━━━━━━━━━━━

🕐 Last Scan:
{state["last_scan"] or "-"}
"""


# ============================================================
# MENU
# ============================================================

def main_menu():

    markup = types.ReplyKeyboardMarkup(
        resize_keyboard=True,
        row_width=2
    )

    markup.add(
        types.KeyboardButton("🦈 داشبورد"),
        types.KeyboardButton("🎯 شکارها")
    )

    markup.add(
        types.KeyboardButton("📂 معاملات باز"),
        types.KeyboardButton("📜 تاریخچه")
    )

    markup.add(
        types.KeyboardButton("⚙️ تنظیمات"),
        types.KeyboardButton("⏸️ توقف / ▶️ ادامه")
    )

    markup.add(
        types.KeyboardButton("ℹ️ وضعیت")
    )

    return markup


# ============================================================
# TELEGRAM
# ============================================================

def send_dashboard(chat_id):

    state["chat_id"] = chat_id

    bot.send_message(
        chat_id,
        dashboard_text(),
        reply_markup=main_menu()
    )

    save_state()


def send_buy(t, position):

    chat_id = state.get(
        "chat_id"
    )

    if not chat_id:
        return

    bot.send_message(
        chat_id,

        f"""
<b>🟢 PAPER BUY V6</b>

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
<b>{position:.6f} SOL</b>

🕐 {now_utc()}
"""
    )


def send_sell(
    trade,
    pnl,
    returned,
    reason
):

    chat_id = state.get(
        "chat_id"
    )

    if not chat_id:
        return

    emoji = (
        "🟢"
        if pnl >= 0
        else "🔴"
    )

    bot.send_message(
        chat_id,

        f"""
<b>{emoji} PAPER SELL V6</b>

🪙 <b>{trade["symbol"]}</b>

💰 Returned:
<b>{returned:.6f} SOL</b>

📊 PnL:
<b>{pnl:+.6f} SOL</b>

📈 Return:
<b>{trade.get("return_percent", 0):+.2f}%</b>

🎯 Reason:
<b>{reason}</b>

🕐 {now_utc()}
"""
    )


def send_profit_lock(
    trade,
    returned,
    pnl
):

    chat_id = state.get(
        "chat_id"
    )

    if not chat_id:
        return

    bot.send_message(
        chat_id,

        f"""
<b>🔒 PROFIT LOCK</b>

🪙 <b>{trade["symbol"]}</b>

💰 Returned:
<b>{returned:.6f} SOL</b>

📊 Locked PnL:
<b>{pnl:+.6f} SOL</b>

📂 Remaining:
<b>{trade["remaining_percent"] * 100:.0f}%</b>

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

        signal = (
            "🟢 BUY"
            if valid_entry(t)
            else "⚪ FILTERED"
        )

        text += f"""
<b>#{i} 🪙 {t["symbol"]}</b>

⭐ Score: {t["score"]}/100
💵 ${t["price"]:.10f}

💧 ${t["liquidity"]:,.0f}
📊 M5: ${t["volume"]:,.2f}

🛒 Buys: {t["buys"]}
📉 Sells: {t["sells"]}

🟢 Pressure:
{t["buy_pressure"]:.1f}%

📈 M5:
{t["m5"]:+.2f}%

🚦 <b>{signal}</b>

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
        "<b>📂 OPEN PAPER TRADES</b>\n\n"
    )

    for trade in trades:

        entry = num(
            trade["entry_price"]
        )

        current = num(
            trade["current_price"]
        )

        pct = 0

        if entry > 0:

            pct = (
                (
                    current
                    - entry
                )
                / entry
            ) * 100

        locked = (
            "🔒 YES"
            if trade["locked"]
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

💰 Position:
{trade["position_sol"]:.6f} SOL

🔒 Lock:
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
        "<b>📜 PAPER HISTORY</b>\n\n"
    )

    for trade in trades[-15:]:

        pnl = num(
            trade.get(
                "pnl_sol",
                0
            )
        )

        emoji = (
            "🟢"
            if pnl >= 0
            else "🔴"
        )

        text += f"""
{emoji} <b>{trade["symbol"]}</b>

💰 PnL:
<b>{pnl:+.6f} SOL</b>

📊 Return:
{num(trade.get("return_percent")):+.2f}%

🎯 {trade.get("exit_reason", "-")}

🕐 {trade.get("exit_time", "-")}

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

def settings_text():

    return f"""
<b>⚙️ V6 SETTINGS</b>

⭐ Score:
<b>{config["min_score"]}</b>

🟢 Pressure:
<b>{config["min_buy_pressure"]:.0f}%</b>

💧 Liquidity:
<b>${config["min_liquidity"]:,.0f}</b>

📊 M5 Volume:
<b>${config["min_m5_volume"]:,.0f}</b>

🎯 TP:
<b>+{config["take_profit"] * 100:.0f}%</b>

🛑 SL:
<b>-{config["stop_loss"] * 100:.0f}%</b>

🔒 Lock:
<b>+{config["profit_lock_trigger"] * 100:.0f}%</b>

📈 Trailing:
<b>{config["trailing_distance"] * 100:.0f}%</b>

🛡️ Risk:
<b>{config["risk_per_trade"] * 100:.0f}%</b>

📂 Max Open:
<b>{config["max_open_trades"]}</b>

⏱️ Scan:
<b>{config["scan_seconds"]}s</b>

━━━━━━━━━━━━━━━━━━━━

🧪 <b>PAPER TRADING</b>
"""


def settings_menu():

    markup = types.InlineKeyboardMarkup(
        row_width=2
    )

    buttons = [

        ("⭐ Score", "score"),
        ("🟢 Pressure", "pressure"),

        ("💧 Liquidity", "liquidity"),
        ("📊 Volume", "volume"),

        ("🎯 TP", "tp"),
        ("🛑 SL", "sl"),

        ("🛡️ Risk", "risk"),
        ("📂 Max Trades", "max"),

        ("⏱️ Scan", "scan")
    ]

    for i in range(
        0,
        len(buttons),
        2
    ):

        row = []

        for label, data in buttons[
            i:i + 2
        ]:

            row.append(
                types.InlineKeyboardButton(
                    label,
                    callback_data=f"set_{data}"
                )
            )

        markup.row(*row)

    markup.add(
        types.InlineKeyboardButton(
            "🔄 Reset",
            callback_data="reset"
        )
    )

    return markup


@bot.callback_query_handler(
    func=lambda call:
    call.data.startswith("set_")
    or call.data == "reset"
)
def settings_callback(call):

    chat_id = call.message.chat.id

    data = call.data

    if data == "reset":

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

    state[
        "waiting_setting"
    ] = data

    save_state()

    prompts = {

        "set_score":
            "⭐ Score جدید را بفرست:",

        "set_pressure":
            "🟢 Buy Pressure جدید را بفرست:",

        "set_liquidity":
            "💧 Liquidity جدید را بفرست:",

        "set_volume":
            "📊 M5 Volume جدید را بفرست:",

        "set_tp":
            "🎯 Take Profit درصدی:",

        "set_sl":
            "🛑 Stop Loss درصدی:",

        "set_risk":
            "🛡️ Risk درصدی:",

        "set_max":
            "📂 حداکثر معاملات باز:",

        "set_scan":
            "⏱️ فاصله اسکن به ثانیه:"
    }

    bot.answer_callback_query(
        call.id
    )

    bot.send_message(
        chat_id,
        prompts.get(
            data,
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
            message.text.strip()
            .replace("%", "")
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

        elif key == "set_max":

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
                    10,
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

        bot.send_message(
            message.chat.id,
            settings_text(),
            reply_markup=settings_menu()
        )

    except Exception:

        bot.send_message(
            message.chat.id,
            "❌ مقدار نامعتبر.",
            reply_markup=main_menu()
        )


# ============================================================
# START
# ============================================================

@bot.message_handler(
    commands=["start"]
)
def start(message):

    state[
        "chat_id"
    ] = message.chat.id

    save_state()

    bot.send_message(
        message.chat.id,

        """
<b>🦈 SOLANA HUNTER V6</b>

🧪 <b>PAPER TRADING</b>

🔎 Market Scanner
⭐ Token Scoring
📊 Telegram Dashboard
🎯 TP / SL
🔒 Profit Lock
📈 Trailing Stop
🛡️ Risk Management
💾 Persistent State
""",

        reply_markup=main_menu()
    )

    send_dashboard(
        message.chat.id
    )


# ============================================================
# MENU HANDLER
# ============================================================

@bot.message_handler(
    func=lambda message: True
)
def menu_handler(message):

    text = (
        message.text or ""
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

        bot.send_message(
            message.chat.id,
            settings_text(),
            reply_markup=settings_menu()
        )

    elif text == "⏸️ توقف / ▶️ ادامه":

        config[
            "enabled"
        ] = not config[
            "enabled"
        ]

        save_config()

        bot.send_message(
            message.chat.id,

            (
                "🟢 ربات فعال شد."
                if config["enabled"]
                else "⏸️ ربات متوقف شد."
            ),

            reply_markup=main_menu()
        )

    elif text == "ℹ️ وضعیت":

        bot.send_message(
            message.chat.id,
            dashboard_text(),
            reply_markup=main_menu()
        )


# ============================================================
# TRADING ENGINE
# ============================================================

def trading_engine():

    print(
        "🦈 SOLANA HUNTER V6 STARTED"
    )

    while True:

        try:

            manage_trades()

            results = scan_market()

            if (
                config["enabled"]
                and time.time()
                >= num(
                    state["paused_until"]
                )
            ):

                for token in results:

                    if paper_buy(
                        token
                    ):
                        break

        except Exception as e:

            print(
                "ENGINE ERROR:",
                e
            )

        time.sleep(
            max(
                10,
                int(
                    config[
                        "scan_seconds"
                    ]
                )
            )
        )


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "========================================"
    )

    print(
        "🦈 SOLANA HUNTER V6"
    )

    print(
        "🧪 PAPER TRADING"
    )

    print(
        f"💰 START: {STARTING_BALANCE:.6f} SOL"
    )

    print(
        "========================================"
    )

    load_config()

    load_state()

    if state[
        "starting_balance_sol"
    ] <= 0:

        state[
            "starting_balance_sol"
        ] = STARTING_BALANCE

        state[
            "balance_sol"
        ] = STARTING_BALANCE

        save_state()

    thread = threading.Thread(
        target=trading_engine,
        daemon=True
    )

    thread.start()

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

            time.sleep(10)


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
