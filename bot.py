import os
import time
import json
import threading
from datetime import datetime, timezone

import requests
import telebot
from telebot import types


# ============================================================
# 🦈 SOLANA HUNTER V3
# PAPER TRADING ONLY
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")

bot = telebot.TeleBot(
    BOT_TOKEN,
    parse_mode="HTML"
)

HTTP = requests.Session()
HTTP.headers.update({
    "User-Agent": "SolanaHunterV3/1.0"
})

DEX_API = "https://api.dexscreener.com"


# ============================================================
# CONFIG
# ============================================================

START_BALANCE = 3.5015

SCAN_SECONDS = 15

MAX_OPEN_TRADES = 2

RISK_PER_TRADE = 0.10

MIN_SCORE = 75
MIN_BUY_PRESSURE = 60.0
MIN_LIQUIDITY = 25000.0
MIN_M5_VOLUME = 10000.0

MIN_M5_CHANGE = -10.0
MAX_M5_CHANGE = 20.0

STOP_LOSS = 0.08
TAKE_PROFIT = 0.15

TRAILING_START = 0.08
TRAILING_DISTANCE = 0.05

COOLDOWN_SECONDS = 10 * 60

MAX_CONSECUTIVE_LOSSES = 3
LOSS_PAUSE_SECONDS = 15 * 60

STATE_FILE = "paper_state_v3.json"


# ============================================================
# STATE
# ============================================================

lock = threading.Lock()

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


# ============================================================
# TIME / FORMAT
# ============================================================

def now_utc():
    return datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


def f(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def money(value):
    return f"${value:.4f}"


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
            ) as fp:

                json.dump(
                    state,
                    fp,
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
        ) as fp:

            old = json.load(fp)

        state.update(old)

        print(
            "V3 state loaded."
        )

    except Exception as e:

        print(
            "STATE LOAD ERROR:",
            e
        )


# ============================================================
# DEXSCREENER
# ============================================================

def latest_tokens():

    urls = [
        f"{DEX_API}/token-boosts/latest/v1",
        f"{DEX_API}/token-profiles/latest/v1"
    ]

    found = {}

    for url in urls:

        try:

            r = HTTP.get(
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
                    found[address] = item

        except Exception as e:

            print(
                "TOKEN DISCOVERY ERROR:",
                e
            )

    return list(
        found.values()
    )


def token_pairs(address):

    try:

        url = (
            f"{DEX_API}/latest/dex/tokens/"
            f"{address}"
        )

        r = HTTP.get(
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
# ANALYZE
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

        symbol = base.get(
            "symbol",
            "UNKNOWN"
        )

        price = f(
            pair.get(
                "priceUsd"
            )
        )

        liquidity = f(
            pair.get(
                "liquidity",
                {}
            ).get(
                "usd"
            )
        )

        volume = f(
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

        buy_pressure = 0

        if total:
            buy_pressure = (
                buys / total
            ) * 100

        m5 = f(
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

        if buy_pressure >= 75:
            score += 25
        elif buy_pressure >= 68:
            score += 21
        elif buy_pressure >= 60:
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
            "buy_pressure": buy_pressure,
            "m5": m5,
            "score": score,
            "pair_address": pair.get(
                "pairAddress"
            )
        }

    except Exception as e:

        print(
            "ANALYSIS ERROR:",
            e
        )

        return None


# ============================================================
# HARD ENTRY FILTER
# ============================================================

def entry_check(t):

    if t["score"] < MIN_SCORE:
        return False, "LOW SCORE"

    if (
        t["buy_pressure"]
        < MIN_BUY_PRESSURE
    ):
        return False, "LOW BUY PRESSURE"

    if (
        t["liquidity"]
        < MIN_LIQUIDITY
    ):
        return False, "LOW LIQUIDITY"

    if (
        t["volume"]
        < MIN_M5_VOLUME
    ):
        return False, "LOW VOLUME"

    if (
        t["m5"]
        < MIN_M5_CHANGE
    ):
        return False, "BAD M5"

    if (
        t["m5"]
        > MAX_M5_CHANGE
    ):
        return False, "PUMP TOO FAST"

    return True, "PASS"


# ============================================================
# COOLDOWN
# ============================================================

def cooldown(address):

    until = f(
        state[
            "cooldowns"
        ].get(
            address,
            0
        )
    )

    if time.time() < until:
        return True

    state[
        "cooldowns"
    ].pop(
        address,
        None
    )

    return False


def set_cooldown(address):

    state[
        "cooldowns"
    ][address] = (
        time.time()
        + COOLDOWN_SECONDS
    )


# ============================================================
# OPEN TRADE
# ============================================================

def get_trade(address):

    for trade in state[
        "open_trades"
    ]:

        if trade[
            "address"
        ] == address:

            return trade

    return None


# ============================================================
# EQUITY
# ============================================================

def equity():

    total = f(
        state["balance"]
    )

    for trade in state[
        "open_trades"
    ]:

        entry = f(
            trade[
                "entry_price"
            ]
        )

        current = f(
            trade.get(
                "current_price",
                entry
            )
        )

        if entry <= 0:
            continue

        change = (
            current - entry
        ) / entry

        value = (
            trade[
                "position"
            ] * (1 + change)
        )

        total += value

    return total


# ============================================================
# BUY
# ============================================================

def paper_buy(t):

    if len(
        state["open_trades"]
    ) >= MAX_OPEN_TRADES:

        return False

    if get_trade(
        t["address"]
    ):
        return False

    if cooldown(
        t["address"]
    ):
        return False

    if time.time() < f(
        state["paused_until"]
    ):
        return False

    passed, reason = (
        entry_check(t)
    )

    if not passed:

        print(
            "REJECT:",
            t["symbol"],
            reason
        )

        return False

    cash = f(
        state["balance"]
    )

    position = (
        cash * RISK_PER_TRADE
    )

    if position < 0.01:
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

        "entry_m5": t[
            "m5"
        ],

        "entry_buy_pressure":
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

    notify_buy(
        t,
        position
    )

    return True


# ============================================================
# SELL
# ============================================================

def paper_sell(
    trade,
    execution_price,
    reason,
    stop_price=None
):

    entry = f(
        trade[
            "entry_price"
        ]
    )

    market_price = f(
        execution_price
    )

    if entry <= 0:
        return

    # --------------------------------------------------------
    # V3 STOP MODEL
    #
    # If stop is triggered, record BOTH:
    #
    # stop_price:
    # expected stop
    #
    # market_price:
    # observed market price
    #
    # execution_price:
    # simulated execution
    # --------------------------------------------------------

    if reason == "STOP LOSS":

        if stop_price is None:

            stop_price = (
                entry
                * (1 - STOP_LOSS)
            )

        # Paper model:
        # execution occurs at stop price,
        # while actual market price is preserved
        # for slippage measurement.
        execution_price = f(
            stop_price
        )

    else:

        execution_price = f(
            execution_price
        )

    change = (
        execution_price - entry
    ) / entry

    pnl = (
        trade[
            "position"
        ] * change
    )

    returned = (
        trade[
            "position"
        ] + pnl
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

    # Slippage from expected stop
    slippage_percent = 0.0

    if (
        stop_price is not None
        and stop_price > 0
    ):

        slippage_percent = (
            (
                market_price
                - stop_price
            )
            / stop_price
            * 100
        )

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
    ] = slippage_percent

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

    # Pause after consecutive losses
    if (
        state[
            "consecutive_losses"
        ]
        >= MAX_CONSECUTIVE_LOSSES
    ):

        state[
            "paused_until"
        ] = (
            time.time()
            + LOSS_PAUSE_SECONDS
        )

    save_state()

    notify_sell(
        trade
    )


# ============================================================
# MANAGE TRADES
# ============================================================

def manage_trades():

    for trade in list(
        state[
            "open_trades"
        ]
    ):

        try:

            pairs = token_pairs(
                trade[
                    "address"
                ]
            )

            if not pairs:
                continue

            pairs.sort(
                key=lambda p:
                f(
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

            current = f(
                t["price"]
            )

            if current <= 0:
                continue

            trade[
                "current_price"
            ] = current

            highest = f(
                trade.get(
                    "highest_price",
                    trade[
                        "entry_price"
                    ]
                )
            )

            if current > highest:

                trade[
                    "highest_price"
                ] = current

                highest = current

            entry = f(
                trade[
                    "entry_price"
                ]
            )

            change = (
                current - entry
            ) / entry

            # ------------------------------------------------
            # STOP LOSS
            # ------------------------------------------------

            stop_price = (
                entry
                * (1 - STOP_LOSS)
            )

            if current <= stop_price:

                paper_sell(
                    trade,
                    current,
                    "STOP LOSS",
                    stop_price
                )

                continue

            # ------------------------------------------------
            # TAKE PROFIT
            # ------------------------------------------------

            tp_price = (
                entry
                * (1 + TAKE_PROFIT)
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

            if change >= TRAILING_START:

                trailing_price = (
                    highest
                    * (
                        1
                        - TRAILING_DISTANCE
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
                "MANAGE ERROR:",
                e
            )


# ============================================================
# SCAN
# ============================================================

def scan():

    results = []

    addresses = latest_tokens()

    seen = set()

    for item in addresses[:50]:

        address = item.get(
            "tokenAddress"
        )

        if not address:
            continue

        if address in seen:
            continue

        seen.add(address)

        pairs = token_pairs(
            address
        )

        if not pairs:
            continue

        pairs.sort(
            key=lambda p:
            f(
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
# ENGINE
# ============================================================

def engine():

    while True:

        try:

            print(
                "\n=============================="
            )

            print(
                "🦈 SOLANA HUNTER V3"
            )

            print(
                now_utc()
            )

            # First manage existing trades
            manage_trades()

            # Then scan
            results = scan()

            # Don't enter while paused
            if time.time() >= f(
                state["paused_until"]
            ):

                # Only ONE new entry per cycle
                for t in results:

                    passed, reason = (
                        entry_check(t)
                    )

                    if not passed:
                        continue

                    if paper_buy(t):
                        break

            update_dashboard()

        except Exception as e:

            print(
                "ENGINE ERROR:",
                e
            )

        time.sleep(
            SCAN_SECONDS
        )


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


def drawdown():

    start = f(
        state[
            "starting_balance"
        ]
    )

    eq = equity()

    if start <= 0:
        return 0

    return (
        (
            eq - start
        )
        / start
        * 100
    )


def dashboard():

    eq = equity()

    pnl = (
        eq
        - state[
            "starting_balance"
        ]
    )

    if time.time() < f(
        state[
            "paused_until"
        ]
    ):

        protection = (
            "🟡 PAUSED "
            f"({int(state['paused_until'] - time.time())}s)"
        )

    else:

        protection = "🟢 READY"

    return f"""
<b>🦈 SOLANA HUNTER V3</b>

━━━━━━━━━━━━━━━━━━━━

🤖 Status:
<b>🟢 ONLINE</b>

🧪 Mode:
<b>PAPER TRADING</b>

💵 Cash:
<b>{money(state["balance"])}</b>

📊 Equity:
<b>{money(eq)}</b>

💰 Total PnL:
<b>{money(pnl)}</b>

📉 Drawdown:
<b>{drawdown():+.2f}%</b>

━━━━━━━━━━━━━━━━━━━━

📂 Open:
<b>{len(state["open_trades"])}/{MAX_OPEN_TRADES}</b>

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
<b>{MIN_SCORE}</b>

🟢 Buy Pressure:
<b>{MIN_BUY_PRESSURE:.0f}%+</b>

💧 Liquidity:
<b>${MIN_LIQUIDITY:,.0f}+</b>

📊 M5 Volume:
<b>${MIN_M5_VOLUME:,.0f}+</b>

📈 M5:
<b>{MIN_M5_CHANGE:.0f}% تا +{MAX_M5_CHANGE:.0f}%</b>

━━━━━━━━━━━━━━━━━━━━

🎯 Take Profit:
<b>+{TAKE_PROFIT * 100:.0f}%</b>

🛑 Stop Loss:
<b>-{STOP_LOSS * 100:.0f}%</b>

📈 Trailing:
<b>+{TRAILING_START * 100:.0f}% / -{TRAILING_DISTANCE * 100:.0f}%</b>

⏱️ Scan:
<b>{SCAN_SECONDS}s</b>

🛡️ Position:
<b>{RISK_PER_TRADE * 100:.0f}%</b>

━━━━━━━━━━━━━━━━━━━━

🚦 Protection:
<b>{protection}</b>

🕐 Last Scan:
{state["last_scan"] or "-"}

━━━━━━━━━━━━━━━━━━━━
"""


# ============================================================
# TELEGRAM DASHBOARD
# ============================================================

def keyboard():

    k = types.InlineKeyboardMarkup(
        row_width=2
    )

    k.add(

        types.InlineKeyboardButton(
            "🦈 TOP",
            callback_data="top"
        ),

        types.InlineKeyboardButton(
            "📂 OPEN",
            callback_data="open"
        )

    )

    k.add(

        types.InlineKeyboardButton(
            "📜 HISTORY",
            callback_data="history"
        ),

        types.InlineKeyboardButton(
            "🔄 REFRESH",
            callback_data="refresh"
        )

    )

    return k


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
            dashboard(),
            chat_id,
            message_id,
            reply_markup=keyboard()
        )

    except Exception as e:

        print(
            "DASHBOARD UPDATE:",
            e
        )


def send_dashboard(chat_id):

    state[
        "chat_id"
    ] = chat_id

    msg = bot.send_message(
        chat_id,
        dashboard(),
        reply_markup=keyboard()
    )

    state[
        "dashboard_message_id"
    ] = msg.message_id

    save_state()


# ============================================================
# BUY NOTIFICATION
# ============================================================

def notify_buy(
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
<b>🚨 PAPER BUY V3</b>

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
{RISK_PER_TRADE * 100:.0f}%

🕐 {now_utc()}
"""
    )


# ============================================================
# SELL NOTIFICATION
# ============================================================

def notify_sell(trade):

    chat_id = state.get(
        "chat_id"
    )

    if not chat_id:
        return

    pnl = f(
        trade[
            "pnl"
        ]
    )

    pct = f(
        trade[
            "return_percent"
        ]
    )

    if pnl >= 0:
        emoji = "🟢"
    else:
        emoji = "🔴"

    extra = ""

    if (
        trade[
            "exit_reason"
        ]
        == "STOP LOSS"
    ):

        extra = f"""
🛑 Stop Price:
${trade["stop_price"]:.10f}

📍 Market Price:
${trade["market_price_at_exit"]:.10f}

📐 Slippage:
{trade["slippage_percent"]:+.2f}%
"""

    bot.send_message(
        chat_id,
        f"""
<b>{emoji} PAPER SELL V3</b>

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
<b>{equity():.4f}</b>
{extra}
🕐 {now_utc()}
"""
    )


# ============================================================
# TELEGRAM COMMANDS
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
<b>🦈 SOLANA HUNTER V3</b>

ربات با موفقیت متصل شد. 🤖

🧪 حالت:
<b>PAPER TRADING</b>

هیچ معامله واقعی انجام نمی‌شود.

📊 /dashboard
🦈 /top
📂 /open
📜 /history
📈 /status
"""
    )

    send_dashboard(
        message.chat.id
    )


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
    commands=["status"]
)
def status(message):

    bot.send_message(
        message.chat.id,
        dashboard()
    )


@bot.message_handler(
    commands=["top"]
)
def top(message):

    hunts = state[
        "top_hunts"
    ]

    if not hunts:

        bot.send_message(
            message.chat.id,
            "🔎 هنوز داده‌ای ثبت نشده."
        )

        return

    text = "<b>🦈 TOP HUNTS V3</b>\n\n"

    for i, t in enumerate(
        hunts[:10],
        1
    ):

        passed, reason = (
            entry_check(t)
        )

        signal = (
            "🟢 VALID"
            if passed
            else f"⚪ {reason}"
        )

        text += f"""
<b>#{i} 🪙 {t["symbol"]}</b>

⭐ Score: {t["score"]}/100
💵 Price: ${t["price"]:.10f}
💧 Liquidity: ${t["liquidity"]:,.0f}
📊 M5 Volume: ${t["volume"]:,.2f}
🟢 Buy Pressure: {t["buy_pressure"]:.1f}%
📈 M5: {t["m5"]:+.2f}%

🚦 <b>{signal}</b>

━━━━━━━━━━━━━━━━━━━━
"""

    bot.send_message(
        message.chat.id,
        text
    )


@bot.message_handler(
    commands=["open"]
)
def open_command(message):

    trades = state[
        "open_trades"
    ]

    if not trades:

        bot.send_message(
            message.chat.id,
            "📂 هیچ معامله بازی نداریم."
        )

        return

    text = "<b>📂 OPEN TRADES V3</b>\n\n"

    for trade in trades:

        entry = f(
            trade[
                "entry_price"
            ]
        )

        current = f(
            trade[
                "current_price"
            ]
        )

        pct = (
            (
                current - entry
            )
            / entry
            * 100
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
${trade["position"]:.4f}

━━━━━━━━━━━━━━━━━━━━
"""

    bot.send_message(
        message.chat.id,
        text
    )


@bot.message_handler(
    commands=["history"]
)
def history(message):

    trades = state[
        "closed_trades"
    ]

    if not trades:

        bot.send_message(
            message.chat.id,
            "📜 هنوز معامله‌ای بسته نشده."
        )

        return

    text = "<b>📜 HISTORY V3</b>\n\n"

    for trade in trades[-15:]:

        pnl = f(
            trade[
                "pnl"
            ]
        )

        pct = f(
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
        message.chat.id,
        text
    )


# ============================================================
# CALLBACKS
# ============================================================

@bot.callback_query_handler(
    func=lambda call: True
)
def callback(call):

    try:

        if call.data == "top":

            top(call.message)

        elif call.data == "open":

            open_command(
                call.message
            )

        elif call.data == "history":

            history(
                call.message
            )

        elif call.data == "refresh":

            update_dashboard()

        bot.answer_callback_query(
            call.id
        )

    except Exception as e:

        print(
            "CALLBACK ERROR:",
            e
        )


# ============================================================
# MAIN
# ============================================================

def main():

    print("""
============================================================
🦈 SOLANA HUNTER V3
============================================================

🧪 PAPER TRADING ONLY

Starting Balance:
$3.5015

Max Open:
2

Risk / Trade:
10%

Min Score:
75

Min Buy Pressure:
60%

Min Liquidity:
$25,000

Min M5 Volume:
$10,000

M5 Range:
-10% تا +20%

Take Profit:
+15%

Stop Loss:
-8%

Trailing:
فعال از +8%
فاصله 5%

Cooldown:
10 minutes

Scan:
15 seconds

============================================================
""")

    load_state()

    # --------------------------------------------------------
    # Trading engine
    # --------------------------------------------------------

    thread = threading.Thread(
        target=engine,
        daemon=True
    )

    thread.start()

    print(
        "🟢 V3 ENGINE STARTED"
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

            time.sleep(10)


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    main()
