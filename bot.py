import os
import time
import json
import math
import threading
from datetime import datetime, timezone

import requests
import telebot
from telebot import types


# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

DEX_API = "https://api.dexscreener.com"

SCAN_INTERVAL = 30

STARTING_BALANCE = float(os.getenv("STARTING_BALANCE", "3.5015"))

MAX_OPEN_TRADES = 3

RISK_PER_TRADE = 0.25

TAKE_PROFIT = 0.15
STOP_LOSS = 0.08

MIN_LIQUIDITY = 5000
MIN_VOLUME = 1000

MIN_SCORE = 62

STATE_FILE = "bot_state.json"


# ============================================================
# GLOBAL STATE
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

    "last_scan": None,

    "top_hunts": [],

    "bot_started": False,

    "chat_id": None,

    "dashboard_message_id": None
}


# ============================================================
# SAVE / LOAD
# ============================================================

def save_state():

    try:

        with state_lock:

            with open(STATE_FILE, "w", encoding="utf-8") as f:

                json.dump(
                    state,
                    f,
                    indent=2,
                    ensure_ascii=False
                )

    except Exception as e:

        print("SAVE ERROR:", e)


def load_state():

    global state

    if not os.path.exists(STATE_FILE):

        save_state()

        return

    try:

        with open(STATE_FILE, "r", encoding="utf-8") as f:

            loaded = json.load(f)

        state.update(loaded)

        print("State loaded.")

    except Exception as e:

        print("LOAD ERROR:", e)


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "Mozilla/5.0 SolanaTradingBot/1.0"
})


# ============================================================
# UTILS
# ============================================================

def now():

    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def safe_float(value, default=0.0):

    try:

        if value is None:
            return default

        return float(value)

    except:

        return default


def format_money(value):

    return f"${value:.4f}"


def shorten_address(address):

    if not address:
        return "?"

    if len(address) <= 12:
        return address

    return address[:6] + "..." + address[-4:]


# ============================================================
# DEXSCREENER
# ============================================================

def get_latest_tokens():

    tokens = {}

    urls = [

        f"{DEX_API}/token-boosts/latest/v1",

        f"{DEX_API}/token-profiles/latest/v1"

    ]

    for url in urls:

        try:

            response = session.get(
                url,
                timeout=15
            )

            if response.status_code != 200:
                continue

            data = response.json()

            if not isinstance(data, list):
                continue

            for item in data:

                chain = item.get("chainId")

                if chain != "solana":
                    continue

                address = item.get("tokenAddress")

                if not address:
                    continue

                tokens[address] = item

        except Exception as e:

            print("DISCOVERY ERROR:", e)

    return list(tokens.values())


def get_token_pairs(address):

    try:

        url = f"{DEX_API}/latest/dex/tokens/{address}"

        response = session.get(
            url,
            timeout=15
        )

        if response.status_code != 200:

            return []

        data = response.json()

        pairs = data.get("pairs", [])

        if not pairs:
            return []

        return [
            p for p in pairs
            if p.get("chainId") == "solana"
        ]

    except Exception as e:

        print("PAIR ERROR:", e)

        return []


# ============================================================
# TOKEN ANALYSIS
# ============================================================

def calculate_score(pair):

    score = 0

    liquidity = safe_float(
        pair.get("liquidity", {}).get("usd")
    )

    volume = safe_float(
        pair.get("volume", {}).get("m5")
    )

    txns = pair.get("txns", {}).get("m5", {})

    buys = int(txns.get("buys", 0) or 0)

    sells = int(txns.get("sells", 0) or 0)

    total = buys + sells

    buy_pressure = 0

    if total > 0:

        buy_pressure = buys / total * 100


    # --------------------------------------------------------
    # LIQUIDITY
    # --------------------------------------------------------

    if liquidity >= 50000:

        score += 20

    elif liquidity >= 20000:

        score += 16

    elif liquidity >= 10000:

        score += 12

    elif liquidity >= MIN_LIQUIDITY:

        score += 7


    # --------------------------------------------------------
    # VOLUME
    # --------------------------------------------------------

    if volume >= 25000:

        score += 20

    elif volume >= 10000:

        score += 16

    elif volume >= 5000:

        score += 12

    elif volume >= MIN_VOLUME:

        score += 7


    # --------------------------------------------------------
    # BUY PRESSURE
    # --------------------------------------------------------

    if buy_pressure >= 75:

        score += 25

    elif buy_pressure >= 65:

        score += 20

    elif buy_pressure >= 58:

        score += 14

    elif buy_pressure >= 52:

        score += 8


    # --------------------------------------------------------
    # TRANSACTION ACTIVITY
    # --------------------------------------------------------

    if total >= 100:

        score += 15

    elif total >= 50:

        score += 12

    elif total >= 20:

        score += 8

    elif total >= 10:

        score += 4


    # --------------------------------------------------------
    # PRICE MOMENTUM
    # --------------------------------------------------------

    change = safe_float(
        pair.get("priceChange", {}).get("m5")
    )

    if 2 <= change <= 15:

        score += 15

    elif 0 <= change < 2:

        score += 8

    elif change > 15:

        score += 5

    elif change < -10:

        score -= 10


    # --------------------------------------------------------
    # PENALTIES
    # --------------------------------------------------------

    if liquidity < MIN_LIQUIDITY:

        score -= 20

    if volume < MIN_VOLUME:

        score -= 15

    if sells > buys * 1.5:

        score -= 15


    return max(0, min(100, score))


def analyze_pair(pair):

    try:

        address = pair.get("baseToken", {}).get("address")

        symbol = pair.get("baseToken", {}).get(
            "symbol",
            "UNKNOWN"
        )

        name = pair.get("baseToken", {}).get(
            "name",
            symbol
        )

        price = safe_float(
            pair.get("priceUsd")
        )

        liquidity = safe_float(
            pair.get("liquidity", {}).get("usd")
        )

        volume = safe_float(
            pair.get("volume", {}).get("m5")
        )

        txns = pair.get("txns", {}).get(
            "m5",
            {}
        )

        buys = int(
            txns.get("buys", 0) or 0
        )

        sells = int(
            txns.get("sells", 0) or 0
        )

        total = buys + sells

        buy_pressure = 0

        if total:

            buy_pressure = buys / total * 100

        change = safe_float(
            pair.get("priceChange", {}).get("m5")
        )

        score = calculate_score(pair)

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

            "change": change,

            "score": score,

            "pair_address": pair.get(
                "pairAddress"
            ),

            "url": pair.get(
                "url"
            )

        }

    except Exception as e:

        print("ANALYSIS ERROR:", e)

        return None


# ============================================================
# SCANNER
# ============================================================

def scan_market():

    print("\n================================")
    print("SCANNING SOLANA")
    print("================================")

    raw_tokens = get_latest_tokens()

    print(
        "Discovered tokens:",
        len(raw_tokens)
    )

    results = []

    checked = set()

    for token in raw_tokens[:40]:

        address = token.get(
            "tokenAddress"
        )

        if not address:
            continue

        if address in checked:
            continue

        checked.add(address)

        pairs = get_token_pairs(address)

        if not pairs:
            continue

        # Best liquidity pair

        pairs.sort(
            key=lambda x: safe_float(
                x.get("liquidity", {}).get("usd")
            ),
            reverse=True
        )

        pair = pairs[0]

        analysis = analyze_pair(pair)

        if not analysis:
            continue

        if analysis["liquidity"] < MIN_LIQUIDITY:
            continue

        if analysis["volume"] < MIN_VOLUME:
            continue

        results.append(analysis)

        time.sleep(0.15)


    results.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    results = results[:10]

    with state_lock:

        state["top_hunts"] = results

        state["last_scan"] = now()

    save_state()

    print(
        "Qualified tokens:",
        len(results)
    )

    for item in results[:5]:

        print(
            item["symbol"],
            item["score"]
        )

    return results


# ============================================================
# TRADE ENGINE
# ============================================================

def find_open_trade(address):

    for trade in state["open_trades"]:

        if trade["address"] == address:

            return trade

    return None


def calculate_position_size():

    balance = safe_float(
        state["balance"]
    )

    size = balance * RISK_PER_TRADE

    return max(0.01, size)


def paper_buy(token):

    with state_lock:

        if len(state["open_trades"]) >= MAX_OPEN_TRADES:

            return False

        if find_open_trade(token["address"]):

            return False

        if token["score"] < MIN_SCORE:

            return False

        if token["price"] <= 0:

            return False

        position_size = calculate_position_size()

        if position_size > state["balance"]:

            position_size = state["balance"]

        if position_size <= 0:

            return False

        trade = {

            "id": str(
                int(time.time() * 1000)
            ),

            "address": token["address"],

            "symbol": token["symbol"],

            "entry_price": token["price"],

            "current_price": token["price"],

            "amount_usd": position_size,

            "entry_time": now(),

            "score": token["score"],

            "status": "OPEN"

        }

        state["balance"] -= position_size

        state["open_trades"].append(
            trade
        )

    save_state()

    print(
        "PAPER BUY:",
        token["symbol"],
        position_size
    )

    send_trade_message(
        "BUY",
        token
    )

    return True


def paper_sell(trade, price, reason):

    with state_lock:

        entry = safe_float(
            trade["entry_price"]
        )

        current = safe_float(price)

        if entry <= 0:

            return

        pct = (
            current - entry
        ) / entry

        profit = (
            trade["amount_usd"]
            * pct
        )

        returned = (
            trade["amount_usd"]
            + profit
        )

        state["balance"] += returned

        state["total_profit"] += profit

        if profit > 0:

            state["wins"] += 1

        else:

            state["losses"] += 1

        trade["exit_price"] = current

        trade["exit_time"] = now()

        trade["profit"] = profit

        trade["profit_percent"] = pct * 100

        trade["reason"] = reason

        trade["status"] = "CLOSED"

        state["closed_trades"].append(
            trade
        )

        state["open_trades"].remove(
            trade
        )

    save_state()

    send_sell_message(
        trade,
        profit,
        pct * 100,
        reason
    )


def manage_trades():

    open_copy = list(
        state["open_trades"]
    )

    for trade in open_copy:

        pairs = get_token_pairs(
            trade["address"]
        )

        if not pairs:

            continue

        pairs.sort(
            key=lambda p: safe_float(
                p.get(
                    "liquidity",
                    {}
                ).get("usd")
            ),
            reverse=True
        )

        analysis = analyze_pair(
            pairs[0]
        )

        if not analysis:

            continue

        current_price = analysis["price"]

        if current_price <= 0:

            continue

        entry = trade["entry_price"]

        pct = (
            current_price - entry
        ) / entry

        trade["current_price"] = current_price

        # TAKE PROFIT

        if pct >= TAKE_PROFIT:

            paper_sell(
                trade,
                current_price,
                "TAKE PROFIT"
            )

            continue

        # STOP LOSS

        if pct <= -STOP_LOSS:

            paper_sell(
                trade,
                current_price,
                "STOP LOSS"
            )

            continue


# ============================================================
# AUTO TRADING
# ============================================================

def trading_cycle():

    while True:

        try:

            print(
                "\n",
                now(),
                "Starting cycle..."
            )

            manage_trades()

            results = scan_market()

            # Only one new trade per cycle

            for token in results:

                if token["score"] >= MIN_SCORE:

                    if not find_open_trade(
                        token["address"]
                    ):

                        paper_buy(token)

                        break

            update_dashboard()

        except Exception as e:

            print(
                "TRADING CYCLE ERROR:",
                e
            )

        time.sleep(
            SCAN_INTERVAL
        )


# ============================================================
# TELEGRAM DASHBOARD
# ============================================================

def calculate_win_rate():

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


def calculate_equity():

    equity = state["balance"]

    for trade in state["open_trades"]:

        entry = trade["entry_price"]

        current = trade.get(
            "current_price",
            entry
        )

        if entry <= 0:
            continue

        pct = (
            current - entry
        ) / entry

        equity += (
            trade["amount_usd"]
            * (1 + pct)
        )

    return equity


def dashboard_text():

    balance = state["balance"]

    pnl = (
        calculate_equity()
        - state["starting_balance"]
    )

    win_rate = calculate_win_rate()

    open_count = len(
        state["open_trades"]
    )

    closed_count = len(
        state["closed_trades"]
    )

    status = (
        "🟢 ONLINE"
        if state["bot_started"]
        else "🔴 OFFLINE"
    )

    text = f"""
<b>🦈 SOLANA HUNTER BOT</b>

━━━━━━━━━━━━━━━━━━━━

🤖 Status: {status}

🧪 Mode: <b>PAPER TRADING</b>

💵 Balance:
<b>{format_money(balance)}</b>

💰 Total PnL:
<b>{format_money(pnl)}</b>

📊 Equity:
<b>{format_money(calculate_equity())}</b>

━━━━━━━━━━━━━━━━━━━━

📂 Open Trades: <b>{open_count}</b>

🔢 Closed Trades: <b>{closed_count}</b>

✅ Wins: <b>{state["wins"]}</b>

❌ Losses: <b>{state["losses"]}</b>

🎯 Win Rate:
<b>{win_rate:.1f}%</b>

━━━━━━━━━━━━━━━━━━━━

🎯 Take Profit: <b>+{TAKE_PROFIT * 100:.0f}%</b>

🛑 Stop Loss: <b>-{STOP_LOSS * 100:.0f}%</b>

⭐ Minimum Score: <b>{MIN_SCORE}/100</b>

🔄 Scan: <b>{SCAN_INTERVAL}s</b>

━━━━━━━━━━━━━━━━━━━━

🕐 Last Scan:

{state["last_scan"] or "Not yet"}

━━━━━━━━━━━━━━━━━━━━
"""

    return text


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
            "📂 OPEN TRADES",
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

    keyboard.add(

        types.InlineKeyboardButton(
            "📊 STATUS",
            callback_data="status"
        )

    )

    return keyboard


def send_dashboard(chat_id):

    state["chat_id"] = chat_id

    message = bot.send_message(
        chat_id,
        dashboard_text(),
        reply_markup=dashboard_keyboard()
    )

    state["dashboard_message_id"] = (
        message.message_id
    )

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
            message_id,
            reply_markup=dashboard_keyboard()
        )

    except Exception as e:

        print(
            "DASHBOARD UPDATE:",
            e
        )


# ============================================================
# TELEGRAM COMMANDS
# ============================================================

@bot.message_handler(
    commands=["start"]
)
def start_command(message):

    state["chat_id"] = message.chat.id

    state["bot_started"] = True

    save_state()

    bot.send_message(
        message.chat.id,
        """
<b>🦈 SOLANA HUNTER</b>

ربات با موفقیت متصل شد. 🤖

حالت فعلی:

🧪 Paper Trading

یعنی فعلاً هیچ پول واقعی جابه‌جا نمی‌شود.

برای مشاهده داشبورد:

/dashboard

برای مشاهده شکارهای برتر:

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

    state["chat_id"] = message.chat.id

    state["bot_started"] = True

    save_state()

    send_dashboard(
        message.chat.id
    )


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

    send_top_hunts(
        message.chat.id
    )


@bot.message_handler(
    commands=["open"]
)
def open_command(message):

    send_open_trades(
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
# TELEGRAM PAGES
# ============================================================

def send_top_hunts(chat_id):

    hunts = state["top_hunts"]

    if not hunts:

        bot.send_message(
            chat_id,
            "🔎 هنوز داده‌ای برای TOP HUNTS نداریم."
        )

        return

    text = "<b>🦈 TOP HUNTS</b>\n\n"

    for i, token in enumerate(
        hunts[:10],
        1
    ):

        text += f"""
<b>#{i} 🪙 {token["symbol"]}</b>

⭐ Score: <b>{token["score"]}/100</b>

💵 Price: ${token["price"]:.10f}

💧 Liquidity: ${token["liquidity"]:,.0f}

📊 M5 Volume: ${token["volume"]:,.2f}

🛒 Buys: {token["buys"]}

📉 Sells: {token["sells"]}

🟢 Buy pressure: {token["buy_pressure"]:.1f}%

📈 M5 Change: {token["change"]:+.2f}%

━━━━━━━━━━━━━━━━
"""

    bot.send_message(
        chat_id,
        text,
        disable_web_page_preview=True
    )


def send_open_trades(chat_id):

    trades = state["open_trades"]

    if not trades:

        bot.send_message(
            chat_id,
            "📂 هیچ معامله بازی وجود ندارد."
        )

        return

    text = "<b>📂 OPEN TRADES</b>\n\n"

    for trade in trades:

        entry = trade["entry_price"]

        current = trade.get(
            "current_price",
            entry
        )

        if entry:

            pct = (
                current - entry
            ) / entry * 100

        else:

            pct = 0

        text += f"""
🪙 <b>{trade["symbol"]}</b>

💵 Entry: ${entry:.10f}

📍 Current: ${current:.10f}

📊 PnL: <b>{pct:+.2f}%</b>

💰 Position: ${trade["amount_usd"]:.4f}

⭐ Score: {trade["score"]}

🕐 {trade["entry_time"]}

━━━━━━━━━━━━━━━━
"""

    bot.send_message(
        chat_id,
        text
    )


def send_history(chat_id):

    trades = state["closed_trades"]

    if not trades:

        bot.send_message(
            chat_id,
            "📜 هنوز معامله بسته‌شده‌ای نداریم."
        )

        return

    text = "<b>📜 TRADE HISTORY</b>\n\n"

    for trade in trades[-10:]:

        profit = trade.get(
            "profit",
            0
        )

        pct = trade.get(
            "profit_percent",
            0
        )

        emoji = (
            "🟢"
            if profit >= 0
            else "🔴"
        )

        text += f"""
{emoji} <b>{trade["symbol"]}</b>

💰 PnL: {profit:+.4f}

📊 Return: {pct:+.2f}%

🎯 Reason: {trade.get("reason", "-")}

🕐 {trade.get("exit_time", "-")}

━━━━━━━━━━━━━━━━
"""

    bot.send_message(
        chat_id,
        text
    )


# ============================================================
# CALLBACKS
# ============================================================

@bot.callback_query_handler(
    func=lambda call: True
)
def callback_handler(call):

    try:

        if call.data == "top":

            send_top_hunts(
                call.message.chat.id
            )

        elif call.data == "open":

            send_open_trades(
                call.message.chat.id
            )

        elif call.data == "history":

            send_history(
                call.message.chat.id
            )

        elif call.data == "status":

            bot.send_message(
                call.message.chat.id,
                dashboard_text()
            )

        elif call.data == "refresh":

            update_dashboard()

            bot.answer_callback_query(
                call.id,
                "🔄 Dashboard updated"
            )

            return

        bot.answer_callback_query(
            call.id
        )

    except Exception as e:

        print(
            "CALLBACK ERROR:",
            e
        )


# ============================================================
# TRADE TELEGRAM NOTIFICATIONS
# ============================================================

def send_trade_message(
    action,
    token
):

    chat_id = state.get(
        "chat_id"
    )

    if not chat_id:
        return

    text = f"""
<b>🚨 PAPER {action}</b>

🪙 <b>{token["symbol"]}</b>

⭐ Score: <b>{token["score"]}/100</b>

💵 Price:
${token["price"]:.10f}

💧 Liquidity:
${token["liquidity"]:,.0f}

📊 M5 Volume:
${token["volume"]:,.2f}

🟢 Buy Pressure:
{token["buy_pressure"]:.1f}%

📈 M5:
{token["change"]:+.2f}%

🕐 {now()}
"""

    try:

        bot.send_message(
            chat_id,
            text
        )

    except Exception as e:

        print(
            "TRADE MESSAGE ERROR:",
            e
        )


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
<b>{emoji} PAPER SELL</b>

🪙 <b>{trade["symbol"]}</b>

💰 PnL:
<b>{profit:+.4f} USD</b>

📊 Return:
<b>{percent:+.2f}%</b>

🎯 Reason:
<b>{reason}</b>

💵 Balance:
<b>{state["balance"]:.4f}</b>

🕐 {now()}
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
# TELEGRAM WATCHDOG
# ============================================================

def telegram_watchdog():

    while True:

        try:

            bot.get_me()

            print(
                "Telegram connection OK"
            )

        except Exception as e:

            print(
                "Telegram connection ERROR:",
                e
            )

        time.sleep(60)


# ============================================================
# MAIN
# ============================================================

def main():

    print("""
====================================================
🦈 SOLANA HUNTER BOT
====================================================
Mode: PAPER TRADING
Starting Balance: $%.4f
Max Open Trades: %s
Take Profit: %.1f%%
Stop Loss: %.1f%%
Minimum Score: %s
Scan Interval: %ss
====================================================
""" % (
        STARTING_BALANCE,
        MAX_OPEN_TRADES,
        TAKE_PROFIT * 100,
        STOP_LOSS * 100,
        MIN_SCORE,
        SCAN_INTERVAL
    ))

    load_state()

    state["bot_started"] = True

    save_state()

    # Trading thread

    trading_thread = threading.Thread(
        target=trading_cycle,
        daemon=True
    )

    trading_thread.start()

    # Telegram watchdog

    watchdog_thread = threading.Thread(
        target=telegram_watchdog,
        daemon=True
    )

    watchdog_thread.start()

    print(
        "🟢 BOT IS ONLINE"
    )

    print(
        "📲 Send /start to Telegram"
    )

    while True:

        try:

            bot.infinity_polling(
                timeout=30,
                long_polling_timeout=30,
                skip_pending=True
            )

        except Exception as e:

            print(
                "POLLING ERROR:",
                e
            )

            time.sleep(10)


if __name__ == "__main__":

    main()
