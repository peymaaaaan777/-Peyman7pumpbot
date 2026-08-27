import os
import time
import json
import threading
from datetime import datetime, timezone

import requests
import telebot
from telebot import types


# ============================================================
# SOLANA HUNTER BOT V2
# PAPER TRADING ONLY
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")

bot = telebot.TeleBot(
    BOT_TOKEN,
    parse_mode="HTML"
)

# ============================================================
# CONFIG
# ============================================================

STARTING_BALANCE = 3.5015

SCAN_INTERVAL = 15

MAX_OPEN_TRADES = 2

# فقط 10 درصد سرمایه در هر معامله
POSITION_SIZE_PERCENT = 0.10

# فیلترهای اجباری ورود
MIN_SCORE = 75
MIN_BUY_PRESSURE = 60.0
MIN_LIQUIDITY = 25000.0
MIN_M5_VOLUME = 10000.0

# روند قیمت
MIN_M5_CHANGE = -10.0
MAX_M5_CHANGE = 20.0

# خروج
STOP_LOSS = 0.08
TAKE_PROFIT = 0.15

# Trailing
TRAILING_START = 0.08
TRAILING_DISTANCE = 0.05

# بعد از Stop Loss
COOLDOWN_SECONDS = 10 * 60

# بعد از چند ضرر متوالی، ورود جدید متوقف می‌شود
MAX_CONSECUTIVE_LOSSES = 3

# مدت توقف بعد از ضررهای متوالی
LOSS_PAUSE_SECONDS = 15 * 60

DEX_API = "https://api.dexscreener.com"

STATE_FILE = "bot_state_v2.json"


# ============================================================
# HTTP
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "SolanaHunterBot/2.0"
})


# ============================================================
# STATE
# ============================================================

state_lock = threading.Lock()

state = {
    "balance": STARTING_BALANCE,
    "starting_balance": STARTING_BALANCE,

    "open_trades": [],
    "closed_trades": [],

    "wins": 0,
    "losses": 0,

    "total_profit": 0.0,

    "consecutive_losses": 0,

    "paused_until": 0,

    "cooldowns": {},

    "top_hunts": [],

    "last_scan": None,

    "bot_started": False,

    "chat_id": None,

    "dashboard_message_id": None
}


# ============================================================
# UTILS
# ============================================================

def utc_now():
    return datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S UTC")


def safe_float(value, default=0.0):

    try:
        if value is None:
            return default

        return float(value)

    except Exception:
        return default


def money(value):

    return f"${value:.4f}"


def is_paused():

    return time.time() < state["paused_until"]


def remaining_pause():

    seconds = int(
        max(
            0,
            state["paused_until"] - time.time()
        )
    )

    return seconds


# ============================================================
# SAVE / LOAD
# ============================================================

def save_state():

    try:

        with state_lock:

            with open(
                STATE_FILE,
                "w",
                encoding="utf-8"
            ) as file:

                json.dump(
                    state,
                    file,
                    indent=2,
                    ensure_ascii=False
                )

    except Exception as e:

        print(
            "STATE SAVE ERROR:",
            e
        )


def load_state():

    global state

    if not os.path.exists(
        STATE_FILE
    ):

        return

    try:

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            loaded = json.load(file)

        # نسخه جدید همیشه با سرمایه اولیه
        # شروع می‌شود اگر فایل قبلی وجود نداشته باشد.
        state.update(loaded)

        print(
            "State loaded."
        )

    except Exception as e:

        print(
            "STATE LOAD ERROR:",
            e
        )


# ============================================================
# RESET PAPER ACCOUNT
# ============================================================

def reset_paper_account():

    with state_lock:

        state["balance"] = STARTING_BALANCE

        state["starting_balance"] = STARTING_BALANCE

        state["open_trades"] = []

        state["closed_trades"] = []

        state["wins"] = 0

        state["losses"] = 0

        state["total_profit"] = 0.0

        state["consecutive_losses"] = 0

        state["paused_until"] = 0

        state["cooldowns"] = {}

    save_state()


# ============================================================
# DEXSCREENER DISCOVERY
# ============================================================

def get_latest_tokens():

    discovered = {}

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

                    discovered[
                        address
                    ] = item

        except Exception as e:

            print(
                "DISCOVERY ERROR:",
                e
            )

    return list(
        discovered.values()
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
            pair
            for pair in pairs
            if pair.get(
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

def analyze_pair(pair):

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

        name = base.get(
            "name",
            symbol
        )

        price = safe_float(
            pair.get(
                "priceUsd"
            )
        )

        liquidity = safe_float(
            pair.get(
                "liquidity",
                {}
            ).get(
                "usd"
            )
        )

        volume = safe_float(
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

        total_txns = (
            buys + sells
        )

        buy_pressure = 0.0

        if total_txns > 0:

            buy_pressure = (
                buys
                / total_txns
                * 100
            )

        m5_change = safe_float(
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

        # Liquidity
        if liquidity >= 100000:
            score += 20

        elif liquidity >= 50000:
            score += 17

        elif liquidity >= 25000:
            score += 13

        # Volume
        if volume >= 100000:
            score += 20

        elif volume >= 50000:
            score += 17

        elif volume >= 25000:
            score += 14

        elif volume >= 10000:
            score += 10

        # Buy pressure
        if buy_pressure >= 75:
            score += 25

        elif buy_pressure >= 68:
            score += 21

        elif buy_pressure >= 60:
            score += 16

        # Transaction activity
        if total_txns >= 200:
            score += 15

        elif total_txns >= 100:
            score += 12

        elif total_txns >= 50:
            score += 9

        elif total_txns >= 20:
            score += 5

        # Healthy momentum
        if 1 <= m5_change <= 10:
            score += 15

        elif 0 <= m5_change < 1:
            score += 9

        elif 10 < m5_change <= 20:
            score += 7

        # Bad momentum penalty
        if m5_change < -5:
            score -= 20

        if m5_change > 20:
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

            "name": name,

            "price": price,

            "liquidity": liquidity,

            "volume": volume,

            "buys": buys,

            "sells": sells,

            "buy_pressure": buy_pressure,

            "m5_change": m5_change,

            "score": score,

            "pair_address": pair.get(
                "pairAddress"
            ),

            "url": pair.get(
                "url"
            )
        }

    except Exception as e:

        print(
            "ANALYZE ERROR:",
            e
        )

        return None


# ============================================================
# HARD ENTRY FILTER
# ============================================================

def passes_entry_filter(token):

    if token["score"] < MIN_SCORE:
        return False, "LOW SCORE"

    if (
        token["buy_pressure"]
        < MIN_BUY_PRESSURE
    ):
        return False, "LOW BUY PRESSURE"

    if (
        token["liquidity"]
        < MIN_LIQUIDITY
    ):
        return False, "LOW LIQUIDITY"

    if (
        token["volume"]
        < MIN_M5_VOLUME
    ):
        return False, "LOW VOLUME"

    if (
        token["m5_change"]
        < MIN_M5_CHANGE
    ):
        return False, "BAD M5 TREND"

    if (
        token["m5_change"]
        > MAX_M5_CHANGE
    ):
        return False, "PUMP TOO FAST"

    return True, "PASS"


# ============================================================
# COOLDOWN
# ============================================================

def is_on_cooldown(address):

    until = safe_float(
        state["cooldowns"].get(
            address,
            0
        )
    )

    if time.time() < until:

        return True

    if address in state["cooldowns"]:

        del state["cooldowns"][
            address
        ]

        save_state()

    return False


def set_cooldown(address):

    state["cooldowns"][
        address
    ] = (
        time.time()
        + COOLDOWN_SECONDS
    )


# ============================================================
# OPEN TRADE SEARCH
# ============================================================

def find_open_trade(address):

    for trade in state["open_trades"]:

        if (
            trade["address"]
            == address
        ):

            return trade

    return None


# ============================================================
# EQUITY
# ============================================================

def calculate_equity():

    equity = state["balance"]

    for trade in state["open_trades"]:

        entry = safe_float(
            trade["entry_price"]
        )

        current = safe_float(
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

        equity += (
            trade["amount_usd"]
            * (1 + change)
        )

    return equity


# ============================================================
# PAPER BUY
# ============================================================

def paper_buy(token):

    if is_paused():

        print(
            "ENTRY PAUSED:",
            remaining_pause(),
            "seconds"
        )

        return False

    if len(
        state["open_trades"]
    ) >= MAX_OPEN_TRADES:

        return False

    if find_open_trade(
        token["address"]
    ):

        return False

    if is_on_cooldown(
        token["address"]
    ):

        return False

    passed, reason = (
        passes_entry_filter(
            token
        )
    )

    if not passed:

        print(
            "FILTER:",
            token["symbol"],
            reason
        )

        return False

    balance = safe_float(
        state["balance"]
    )

    position_size = (
        balance
        * POSITION_SIZE_PERCENT
    )

    if position_size < 0.01:

        return False

    if position_size > balance:

        position_size = balance

    trade = {

        "id": str(
            int(
                time.time()
                * 1000
            )
        ),

        "address": token[
            "address"
        ],

        "symbol": token[
            "symbol"
        ],

        "entry_price": token[
            "price"
        ],

        "current_price": token[
            "price"
        ],

        "amount_usd": position_size,

        "entry_time": utc_now(),

        "score": token[
            "score"
        ],

        "highest_price": token[
            "price"
        ],

        "status": "OPEN"
    }

    state["balance"] -= (
        position_size
    )

    state["open_trades"].append(
        trade
    )

    save_state()

    send_buy_message(
        token,
        position_size
    )

    print(
        "PAPER BUY:",
        token["symbol"],
        position_size
    )

    return True


# ============================================================
# PAPER SELL
# ============================================================

def paper_sell(
    trade,
    price,
    reason
):

    entry = safe_float(
        trade["entry_price"]
    )

    current = safe_float(
        price
    )

    if entry <= 0:
        return

    change = (
        current - entry
    ) / entry

    profit = (
        trade["amount_usd"]
        * change
    )

    returned = (
        trade["amount_usd"]
        + profit
    )

    state["balance"] += returned

    state["total_profit"] += profit

    if profit >= 0:

        state["wins"] += 1

        state[
            "consecutive_losses"
        ] = 0

    else:

        state["losses"] += 1

        state[
            "consecutive_losses"
        ] += 1

        # Cooldown بعد از ضرر
        set_cooldown(
            trade["address"]
        )

    trade["exit_price"] = current

    trade["exit_time"] = utc_now()

    trade["profit"] = profit

    trade["return_percent"] = (
        change * 100
    )

    trade["reason"] = reason

    trade["status"] = "CLOSED"

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

    # توقف پس از ضررهای متوالی
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

        print(
            "ENTRY PAUSED AFTER "
            "CONSECUTIVE LOSSES"
        )

    save_state()

    send_sell_message(
        trade,
        profit,
        change * 100,
        reason
    )


# ============================================================
# MANAGE OPEN TRADES
# ============================================================

def manage_trades():

    trades = list(
        state["open_trades"]
    )

    for trade in trades:

        try:

            pairs = get_pairs(
                trade["address"]
            )

            if not pairs:
                continue

            pairs.sort(
                key=lambda p:
                safe_float(
                    p.get(
                        "liquidity",
                        {}
                    ).get(
                        "usd"
                    )
                ),
                reverse=True
            )

            analysis = analyze_pair(
                pairs[0]
            )

            if not analysis:
                continue

            current = analysis[
                "price"
            ]

            if current <= 0:
                continue

            trade[
                "current_price"
            ] = current

            highest = safe_float(
                trade.get(
                    "highest_price",
                    trade["entry_price"]
                )
            )

            if current > highest:

                trade[
                    "highest_price"
                ] = current

                highest = current

            entry = safe_float(
                trade["entry_price"]
            )

            change = (
                current - entry
            ) / entry

            # ------------------------------------------------
            # STOP LOSS
            # ------------------------------------------------

            if change <= -STOP_LOSS:

                paper_sell(
                    trade,
                    current,
                    "STOP LOSS"
                )

                continue

            # ------------------------------------------------
            # TAKE PROFIT
            # ------------------------------------------------

            if change >= TAKE_PROFIT:

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

                drawdown_from_high = (
                    current - highest
                ) / highest

                if (
                    drawdown_from_high
                    <= -TRAILING_DISTANCE
                ):

                    paper_sell(
                        trade,
                        current,
                        "TRAILING STOP"
                    )

                    continue

        except Exception as e:

            print(
                "TRADE MANAGER ERROR:",
                e
            )


# ============================================================
# MARKET SCANNER
# ============================================================

def scan_market():

    results = []

    raw_tokens = (
        get_latest_tokens()
    )

    checked = set()

    for item in raw_tokens[:50]:

        address = item.get(
            "tokenAddress"
        )

        if not address:
            continue

        if address in checked:
            continue

        checked.add(address)

        try:

            pairs = get_pairs(
                address
            )

            if not pairs:
                continue

            pairs.sort(
                key=lambda p:
                safe_float(
                    p.get(
                        "liquidity",
                        {}
                    ).get(
                        "usd"
                    )
                ),
                reverse=True
            )

            token = analyze_pair(
                pairs[0]
            )

            if not token:
                continue

            # TOP HUNTS می‌تواند اطلاعات
            # بیشتری نشان دهد، اما برای خرید
            # حتماً hard filter اجرا می‌شود.
            results.append(
                token
            )

            time.sleep(
                0.10
            )

        except Exception as e:

            print(
                "SCAN TOKEN ERROR:",
                e
            )

    results.sort(
        key=lambda x:
        x["score"],
        reverse=True
    )

    results = results[:10]

    state[
        "top_hunts"
    ] = results

    state[
        "last_scan"
    ] = utc_now()

    save_state()

    return results


# ============================================================
# TRADING LOOP
# ============================================================

def trading_loop():

    while True:

        try:

            print(
                "\n=========================="
            )

            print(
                "🦈 NEW MARKET CYCLE"
            )

            print(
                utc_now()
            )

            manage_trades()

            results = scan_market()

            # اگر در حالت توقف هستیم
            if is_paused():

                print(
                    "ENTRY PAUSED FOR:",
                    remaining_pause(),
                    "SECONDS"
                )

                update_dashboard()

                time.sleep(
                    SCAN_INTERVAL
                )

                continue

            # فقط اولین سیگنال معتبر
            # در هر چرخه
            for token in results:

                passed, reason = (
                    passes_entry_filter(
                        token
                    )
                )

                if not passed:

                    continue

                if paper_buy(
                    token
                ):

                    break

            update_dashboard()

        except Exception as e:

            print(
                "TRADING LOOP ERROR:",
                e
            )

        time.sleep(
            SCAN_INTERVAL
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


def drawdown_percent():

    starting = safe_float(
        state["starting_balance"]
    )

    equity = calculate_equity()

    if starting <= 0:
        return 0

    return (
        (
            equity - starting
        )
        / starting
        * 100
    )


def dashboard_text():

    equity = calculate_equity()

    pnl = (
        equity
        - state["starting_balance"]
    )

    pause_text = "🟢 READY"

    if is_paused():

        pause_text = (
            "🟡 PAUSED "
            f"({remaining_pause()}s)"
        )

    return f"""
<b>🦈 SOLANA HUNTER V2</b>

━━━━━━━━━━━━━━━━━━━━

🤖 Status:
<b>🟢 ONLINE</b>

🧪 Mode:
<b>PAPER TRADING</b>

💵 Cash:
<b>{money(state["balance"])}</b>

📊 Equity:
<b>{money(equity)}</b>

💰 Total PnL:
<b>{money(pnl)}</b>

📉 Drawdown:
<b>{drawdown_percent():+.2f}%</b>

━━━━━━━━━━━━━━━━━━━━

📂 Open Trades:
<b>{len(state["open_trades"])}/{MAX_OPEN_TRADES}</b>

🔢 Closed Trades:
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
<b>{MIN_SCORE}/100</b>

🟢 Min Buy Pressure:
<b>{MIN_BUY_PRESSURE:.0f}%</b>

💧 Min Liquidity:
<b>${MIN_LIQUIDITY:,.0f}</b>

📊 Min M5 Volume:
<b>${MIN_M5_VOLUME:,.0f}</b>

📈 Allowed M5:
<b>{MIN_M5_CHANGE:.0f}% تا +{MAX_M5_CHANGE:.0f}%</b>

━━━━━━━━━━━━━━━━━━━━

🎯 Take Profit:
<b>+{TAKE_PROFIT * 100:.0f}%</b>

🛑 Stop Loss:
<b>-{STOP_LOSS * 100:.0f}%</b>

📈 Trailing:
<b>{TRAILING_DISTANCE * 100:.0f}%</b>

⏱️ Scan:
<b>{SCAN_INTERVAL}s</b>

🛡️ Risk/Trade:
<b>{POSITION_SIZE_PERCENT * 100:.0f}%</b>

━━━━━━━━━━━━━━━━━━━━

🚦 Entry Protection:
<b>{pause_text}</b>

🕐 Last Scan:

{state["last_scan"] or "Not yet"}

━━━━━━━━━━━━━━━━━━━━
"""


def dashboard_keyboard():

    keyboard = types.InlineKeyboardMarkup(
        row_width=2
    )

    keyboard.add(

        types.InlineKeyboardButton(
            "🦈 TOP HUNTS",
            callback_data="top"
        ),

        types.InlineKeyboardButton(
            "📂 OPEN",
            callback_data="open"
        )

    )

    keyboard.add(

        types.InlineKeyboardButton(
            "📜 HISTORY",
            callback_data="history"
        ),

        types.InlineKeyboardButton(
            "🔄 REFRESH",
            callback_data="refresh"
        )

    )

    return keyboard


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
            message_id,
            reply_markup=dashboard_keyboard()
        )

    except Exception as e:

        print(
            "DASHBOARD ERROR:",
            e
        )


# ============================================================
# TELEGRAM
# ============================================================

@bot.message_handler(
    commands=["start"]
)
def start_command(message):

    state["chat_id"] = (
        message.chat.id
    )

    state["bot_started"] = True

    save_state()

    bot.send_message(
        message.chat.id,
        """
<b>🦈 SOLANA HUNTER V2</b>

ربات با موفقیت آنلاین شد. 🤖

🧪 Paper Trading فعال است.

💰 هیچ معامله واقعی انجام نمی‌شود.

برای داشبورد:

/dashboard

برای شکارهای برتر:

/top

برای معاملات باز:

/open

برای تاریخچه:

/history

برای وضعیت:

/status
"""
    )

    send_dashboard(
        message.chat.id
    )


@bot.message_handler(
    commands=["dashboard"]
)
def dashboard_command(message):

    state["chat_id"] = (
        message.chat.id
    )

    state["bot_started"] = True

    save_state()

    send_dashboard(
        message.chat.id
    )


def send_dashboard(chat_id):

    state["chat_id"] = chat_id

    sent = bot.send_message(
        chat_id,
        dashboard_text(),
        reply_markup=dashboard_keyboard()
    )

    state[
        "dashboard_message_id"
    ] = sent.message_id

    save_state()


@bot.message_handler(
    commands=["status"]
)
def status_command(message):

    bot.send_message(
        message.chat.id,
        dashboard_text()
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
            "🔎 هنوز داده‌ای نداریم."
        )

        return

    text = (
        "<b>🦈 TOP HUNTS</b>\n\n"
    )

    for index, token in enumerate(
        hunts[:10],
        1
    ):

        passed, reason = (
            passes_entry_filter(
                token
            )
        )

        signal = (
            "🟢 BUY CANDIDATE"
            if passed
            else f"⚪ {reason}"
        )

        text += f"""
<b>#{index} 🪙 {token["symbol"]}</b>

⭐ Score: <b>{token["score"]}/100</b>

💵 Price:
${token["price"]:.10f}

💧 Liquidity:
${token["liquidity"]:,.0f}

📊 M5 Volume:
${token["volume"]:,.2f}

🛒 Buys:
{token["buys"]}

📉 Sells:
{token["sells"]}

🟢 Buy Pressure:
{token["buy_pressure"]:.1f}%

📈 M5:
{token["m5_change"]:+.2f}%

🚦 Signal:
<b>{signal}</b>

━━━━━━━━━━━━━━━━━━━━
"""

    bot.send_message(
        chat_id,
        text,
        disable_web_page_preview=True
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
            "📂 هیچ معامله بازی نداریم."
        )

        return

    text = (
        "<b>📂 OPEN TRADES</b>\n\n"
    )

    for trade in trades:

        entry = safe_float(
            trade["entry_price"]
        )

        current = safe_float(
            trade.get(
                "current_price",
                entry
            )
        )

        pct = 0

        if entry > 0:

            pct = (
                current - entry
            ) / entry * 100

        text += f"""
🪙 <b>{trade["symbol"]}</b>

💵 Entry:
${entry:.10f}

📍 Current:
${current:.10f}

📊 PnL:
<b>{pct:+.2f}%</b>

💰 Position:
${trade["amount_usd"]:.4f}

⭐ Score:
{trade["score"]}

━━━━━━━━━━━━━━━━━━━━
"""

    bot.send_message(
        chat_id,
        text
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
            "📜 هنوز معامله بسته‌شده‌ای نداریم."
        )

        return

    text = (
        "<b>📜 HISTORY</b>\n\n"
    )

    for trade in trades[-15:]:

        profit = safe_float(
            trade.get(
                "profit"
            )
        )

        pct = safe_float(
            trade.get(
                "return_percent"
            )
        )

        emoji = (
            "🟢"
            if profit >= 0
            else "🔴"
        )

        text += f"""
{emoji} <b>{trade["symbol"]}</b>

💰 PnL:
{profit:+.4f} USD

📊 Return:
{pct:+.2f}%

🎯 Reason:
{trade.get("reason", "-")}

🕐 Exit:
{trade.get("exit_time", "-")}

━━━━━━━━━━━━━━━━━━━━
"""

    bot.send_message(
        chat_id,
        text
    )


# ============================================================
# BUY MESSAGE
# ============================================================

def send_buy_message(
    token,
    position_size
):

    chat_id = state.get(
        "chat_id"
    )

    if not chat_id:
        return

    text = f"""
<b>🚨 PAPER BUY V2</b>

🪙 <b>{token["symbol"]}</b>

⭐ Score:
<b>{token["score"]}/100</b>

💵 Price:
${token["price"]:.10f}

💧 Liquidity:
${token["liquidity"]:,.0f}

📊 M5 Volume:
${token["volume"]:,.2f}

🟢 Buy Pressure:
{token["buy_pressure"]:.1f}%

📈 M5:
{token["m5_change"]:+.2f}%

💰 Position:
${position_size:.4f}

🛡️ Risk:
{POSITION_SIZE_PERCENT * 100:.0f}%

🕐 {utc_now()}
"""

    try:

        bot.send_message(
            chat_id,
            text
        )

    except Exception as e:

        print(
            "BUY MESSAGE ERROR:",
            e
        )


# ============================================================
# SELL MESSAGE
# ============================================================

def send_sell_message(
    trade,
    profit,
    percent,
    reason
):

    chat_id = state.get(
        "chat_id"
    )

    if not chat_id:
        return

    emoji = (
        "🟢"
        if profit >= 0
        else "🔴"
    )

    text = f"""
<b>{emoji} PAPER SELL V2</b>

🪙 <b>{trade["symbol"]}</b>

💰 PnL:
<b>{profit:+.4f} USD</b>

📊 Return:
<b>{percent:+.2f}%</b>

🎯 Reason:
<b>{reason}</b>

💵 Cash:
<b>{state["balance"]:.4f}</b>

📊 Equity:
<b>{calculate_equity():.4f}</b>

🕐 {utc_now()}
"""

    try:

        bot.send_message(
            chat_id,
            text
        )

    except Exception as e:

        print(
            "SELL MESSAGE ERROR:",
            e
        )


# ============================================================
# CALLBACK BUTTONS
# ============================================================

@bot.callback_query_handler(
    func=lambda call: True
)
def callback_handler(call):

    try:

        if call.data == "top":

            send_top(
                call.message.chat.id
            )

        elif call.data == "open":

            send_open(
                call.message.chat.id
            )

        elif call.data == "history":

            send_history(
                call.message.chat.id
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
🦈 SOLANA HUNTER V2
============================================================

MODE:
PAPER TRADING

STARTING BALANCE:
$3.5015

MAX OPEN TRADES:
2

POSITION SIZE:
10%

MIN SCORE:
75

MIN BUY PRESSURE:
60%

MIN LIQUIDITY:
$25,000

MIN M5 VOLUME:
$10,000

M5 RANGE:
-10% TO +20%

TAKE PROFIT:
15%

STOP LOSS:
8%

TRAILING STOP:
5%

SCAN:
15 SECONDS

COOLDOWN:
10 MINUTES

============================================================
""")

    load_state()

    state[
        "bot_started"
    ] = True

    save_state()

    # --------------------------------------------------------
    # Trading thread
    # --------------------------------------------------------

    trading_thread = threading.Thread(
        target=trading_loop,
        daemon=True
    )

    trading_thread.start()

    print(
        "🟢 TRADING ENGINE STARTED"
    )

    print(
        "📡 TELEGRAM STARTING..."
    )

    # --------------------------------------------------------
    # Telegram polling
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
