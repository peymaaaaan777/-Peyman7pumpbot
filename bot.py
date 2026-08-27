import os
import time
import json
import threading
from datetime import datetime, timezone

import requests
import telebot
from telebot import types

from solders.keypair import Keypair
from solders.transaction import VersionedTransaction


# ============================================================
# 🦈 SOLANA HUNTER V6
# JUPITER + TELEGRAM + RISK MANAGEMENT
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
JUPITER_API_KEY = os.getenv("JUPITER_API_KEY")
PRIVATE_KEY = os.getenv("SOLANA_PRIVATE_KEY")

# IMPORTANT:
# Keep this FALSE for the first test.
# Change GitHub Secret LIVE_TRADING to true only after
# Telegram + wallet + Jupiter connection are confirmed.
LIVE_TRADING = os.getenv("LIVE_TRADING", "false").lower() == "true"

RPC_URL = os.getenv(
    "SOLANA_RPC_URL",
    "https://api.mainnet-beta.solana.com"
)

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")

if not JUPITER_API_KEY:
    raise RuntimeError("JUPITER_API_KEY is missing")

if not PRIVATE_KEY:
    raise RuntimeError("SOLANA_PRIVATE_KEY is missing")


# ============================================================
# SETTINGS
# ============================================================

START_BALANCE = 3.5015

MAX_TRADE_SOL = float(
    os.getenv("MAX_TRADE_SOL", "0.02")
)

MAX_OPEN_TRADES = int(
    os.getenv("MAX_OPEN_TRADES", "2")
)

TAKE_PROFIT = float(
    os.getenv("TAKE_PROFIT_PCT", "15")
) / 100

STOP_LOSS = float(
    os.getenv("STOP_LOSS_PCT", "8")
) / 100

TRAILING_START = float(
    os.getenv("TRAILING_START_PCT", "10")
) / 100

TRAILING_DISTANCE = float(
    os.getenv("TRAILING_DISTANCE_PCT", "5")
) / 100

MIN_SCORE = int(
    os.getenv("MIN_SCORE", "75")
)

MIN_BUY_PRESSURE = float(
    os.getenv("MIN_BUY_PRESSURE", "60")
)

MIN_LIQUIDITY = float(
    os.getenv("MIN_LIQUIDITY", "30000")
)

MIN_M5_VOLUME = float(
    os.getenv("MIN_M5_VOLUME", "15000")
)

SCAN_SECONDS = int(
    os.getenv("SCAN_SECONDS", "20")
)

COOLDOWN_SECONDS = int(
    os.getenv("COOLDOWN_SECONDS", "600")
)

MAX_CONSECUTIVE_LOSSES = int(
    os.getenv("MAX_CONSECUTIVE_LOSSES", "3")
)

LOSS_PAUSE_SECONDS = int(
    os.getenv("LOSS_PAUSE_SECONDS", "900")
)

# Jupiter uses basis points for slippage-related settings.
SLIPPAGE_BPS = int(
    os.getenv("SLIPPAGE_BPS", "100")
)


# ============================================================
# API
# ============================================================

DEX_API = "https://api.dexscreener.com"

JUPITER_API = "https://api.jup.ag"

JUPITER_ORDER_URL = (
    f"{JUPITER_API}/ultra/v1/order"
)

JUPITER_EXECUTE_URL = (
    f"{JUPITER_API}/ultra/v1/execute"
)


# ============================================================
# HTTP
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "SolanaHunterV6/1.0",
    "x-api-key": JUPITER_API_KEY
})


# ============================================================
# TELEGRAM
# ============================================================

bot = telebot.TeleBot(
    BOT_TOKEN,
    parse_mode="HTML"
)


# ============================================================
# WALLET
# ============================================================

def load_keypair():

    raw = PRIVATE_KEY.strip()

    # JSON array:
    # [12,34,56,...]
    if raw.startswith("["):

        data = json.loads(raw)

        return Keypair.from_bytes(
            bytes(data)
        )

    # Base58 private key
    try:

        return Keypair.from_base58_string(
            raw
        )

    except Exception:

        raise RuntimeError(
            "SOLANA_PRIVATE_KEY format is invalid"
        )


wallet = load_keypair()

WALLET_ADDRESS = str(
    wallet.pubkey()
)


# ============================================================
# STATE
# ============================================================

STATE_FILE = "state_v6.json"

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

    "dashboard_message_id": None,

    "enabled": True,

    "wallet": WALLET_ADDRESS
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


def money(value):

    return f"${num(value):.4f}"


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

        state.update(saved)

    except Exception as e:

        print(
            "STATE LOAD ERROR:",
            e
        )


# ============================================================
# SOLANA RPC
# ============================================================

def rpc(method, params=None):

    payload = {

        "jsonrpc": "2.0",

        "id": 1,

        "method": method,

        "params": params or []
    }

    response = requests.post(

        RPC_URL,

        json=payload,

        timeout=20
    )

    response.raise_for_status()

    data = response.json()

    if "error" in data:

        raise RuntimeError(
            str(data["error"])
        )

    return data.get(
        "result"
    )


def get_sol_balance():

    result = rpc(
        "getBalance",
        [
            WALLET_ADDRESS,
            {
                "commitment": "confirmed"
            }
        ]
    )

    lamports = result[
        "value"
    ]

    return lamports / 1_000_000_000


# ============================================================
# TELEGRAM MENUS
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
            "💰 کیف پول"
        ),

        types.KeyboardButton(
            "⚙️ تنظیمات"
        )
    )

    markup.add(

        types.KeyboardButton(
            "⏸️ توقف / ▶️ ادامه"
        ),

        types.KeyboardButton(
            "ℹ️ وضعیت"
        )
    )

    return markup


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

                    result[
                        address
                    ] = item

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

        response = session.get(

            f"{DEX_API}/latest/dex/tokens/{address}",

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

        if total:

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

        if liquidity >= 100000:
            score += 20

        elif liquidity >= 50000:
            score += 17

        elif liquidity >= 30000:
            score += 14

        if volume >= 100000:
            score += 20

        elif volume >= 50000:
            score += 17

        elif volume >= 25000:
            score += 14

        elif volume >= 15000:
            score += 10

        if pressure >= 80:
            score += 25

        elif pressure >= 70:
            score += 21

        elif pressure >= 60:
            score += 16

        if total >= 500:
            score += 15

        elif total >= 200:
            score += 13

        elif total >= 100:
            score += 10

        elif total >= 50:
            score += 7

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

def check_entry(t):

    if t["score"] < MIN_SCORE:
        return False

    if t["buy_pressure"] < MIN_BUY_PRESSURE:
        return False

    if t["liquidity"] < MIN_LIQUIDITY:
        return False

    if t["volume"] < MIN_M5_VOLUME:
        return False

    if t["m5"] < -5:
        return False

    if t["m5"] > 15:
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
        + COOLDOWN_SECONDS
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
# JUPITER ORDER
# ============================================================

def jupiter_order(

    input_mint,

    output_mint,

    amount,

    taker=WALLET_ADDRESS

):

    params = {

        "inputMint": input_mint,

        "outputMint": output_mint,

        "amount": str(amount),

        "taker": taker
    }

    response = session.get(

        JUPITER_ORDER_URL,

        params=params,

        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    if data.get(
        "errorCode"
    ):

        raise RuntimeError(
            data.get(
                "errorMessage",
                "Jupiter order error"
            )
        )

    return data


# ============================================================
# JUPITER EXECUTE
# ============================================================

def jupiter_execute(

    signed_transaction,

    request_id

):

    payload = {

        "signedTransaction":
            signed_transaction,

        "requestId":
            request_id
    }

    response = session.post(

        JUPITER_EXECUTE_URL,

        json=payload,

        timeout=60
    )

    response.raise_for_status()

    return response.json()


# ============================================================
# REAL BUY
# ============================================================

def real_buy(

    token_address,

    symbol

):

    if not LIVE_TRADING:

        return {

            "success": False,

            "test": True,

            "message":
                "LIVE_TRADING=false"
        }

    sol_balance = get_sol_balance()

    amount_sol = min(

        MAX_TRADE_SOL,

        max(
            0,
            sol_balance - 0.005
        )
    )

    if amount_sol <= 0:

        raise RuntimeError(
            "Not enough SOL for trade + fees"
        )

    lamports = int(
        amount_sol
        * 1_000_000_000
    )

    order = jupiter_order(

        input_mint=
            "So11111111111111111111111111111111111111112",

        output_mint=
            token_address,

        amount=
            lamports
    )

    transaction = order.get(
        "transaction"
    )

    request_id = order.get(
        "requestId"
    )

    if not transaction:
        raise RuntimeError(
            "Jupiter did not return transaction"
        )

    if not request_id:
        raise RuntimeError(
            "Jupiter did not return requestId"
        )

    raw_transaction = bytes.fromhex(
        transaction
    )

    tx = VersionedTransaction.from_bytes(
        raw_transaction
    )

    signed_tx = VersionedTransaction(
        tx.message,
        [wallet]
    )

    signed_hex = bytes(
        signed_tx
    ).hex()

    result = jupiter_execute(

        signed_hex,

        request_id
    )

    status = str(
        result.get(
            "status",
            ""
        )
    ).upper()

    signature = (

        result.get(
            "signature"
        )

        or result.get(
            "txid"
        )

        or ""
    )

    success = (

        status == "SUCCESS"

        or bool(
            signature
        )
    )

    return {

        "success": success,

        "signature": signature,

        "amount_sol":
            amount_sol,

        "jupiter":
            result
    }


# ============================================================
# REAL SELL
# ============================================================

def real_sell(

    token_address,

    token_amount

):

    if not LIVE_TRADING:

        return {

            "success": False,

            "test": True,

            "message":
                "LIVE_TRADING=false"
        }

    amount = int(
        token_amount
    )

    if amount <= 0:

        raise RuntimeError(
            "Invalid token amount"
        )

    order = jupiter_order(

        input_mint=
            token_address,

        output_mint=
            "So11111111111111111111111111111111111111112",

        amount=
            amount
    )

    transaction = order.get(
        "transaction"
    )

    request_id = order.get(
        "requestId"
    )

    if not transaction:
        raise RuntimeError(
            "Jupiter did not return transaction"
        )

    if not request_id:
        raise RuntimeError(
            "Jupiter did not return requestId"
        )

    raw_transaction = bytes.fromhex(
        transaction
    )

    tx = VersionedTransaction.from_bytes(
        raw_transaction
    )

    signed_tx = VersionedTransaction(
        tx.message,
        [wallet]
    )

    signed_hex = bytes(
        signed_tx
    ).hex()

    result = jupiter_execute(

        signed_hex,

        request_id
    )

    status = str(
        result.get(
            "status",
            ""
        )
    ).upper()

    signature = (

        result.get(
            "signature"
        )

        or result.get(
            "txid"
        )

        or ""
    )

    success = (

        status == "SUCCESS"

        or bool(
            signature
        )
    )

    return {

        "success": success,

        "signature": signature,

        "jupiter":
            result
    }


# ============================================================
# TELEGRAM MESSAGES
# ============================================================

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
            "TELEGRAM SEND ERROR:",
            e
        )


# ============================================================
# DASHBOARD
# ============================================================

def current_equity():

    value = num(
        state[
            "balance"
        ]
    )

    return value


def win_rate():

    total = (

        state["wins"]
        +
        state["losses"]
    )

    if total == 0:
        return 0

    return (

        state["wins"]
        / total
        * 100
    )


def dashboard_text():

    try:

        wallet_sol = get_sol_balance()

    except Exception:

        wallet_sol = 0

    mode = (

        "🔴 LIVE TRADING"

        if LIVE_TRADING

        else

        "🧪 SAFE TEST MODE"
    )

    status = (

        "⏸️ PAUSED"

        if not state["enabled"]

        else

        "🟢 ONLINE"
    )

    return f"""
<b>🦈 SOLANA HUNTER V6</b>

━━━━━━━━━━━━━━━━━━━━

🤖 Status:
<b>{status}</b>

⚡ Mode:
<b>{mode}</b>

👛 Wallet:
<code>{WALLET_ADDRESS}</code>

💎 SOL:
<b>{wallet_sol:.6f}</b>

━━━━━━━━━━━━━━━━━━━━

💵 Paper Cash:
<b>${state["balance"]:.4f}</b>

💰 Total PnL:
<b>{state["total_pnl"]:+.4f} USD</b>

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

🎯 Take Profit:
<b>+{TAKE_PROFIT * 100:.1f}%</b>

🛑 Stop Loss:
<b>-{STOP_LOSS * 100:.1f}%</b>

📈 Trailing:
<b>+{TRAILING_START * 100:.1f}% / -{TRAILING_DISTANCE * 100:.1f}%</b>

💸 Max Trade:
<b>{MAX_TRADE_SOL:.4f} SOL</b>

📂 Max Open:
<b>{MAX_OPEN_TRADES}</b>

⭐ Min Score:
<b>{MIN_SCORE}</b>

━━━━━━━━━━━━━━━━━━━━

🕐 Last Scan:
{state["last_scan"] or "-"}

━━━━━━━━━━━━━━━━━━━━
"""


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
# BUY LOG
# ============================================================

def notify_buy(

    token,

    result

):

    if result.get(
        "test"
    ):

        notify(
            f"""
<b>🧪 V6 BUY TEST</b>

🪙 {token["symbol"]}

⭐ Score:
<b>{token["score"]}/100</b>

💰 Planned:
<b>{MAX_TRADE_SOL:.4f} SOL</b>

⚠️ LIVE_TRADING=false

هیچ معامله واقعی انجام نشد.
"""
        )

        return

    signature = result.get(
        "signature",
        "-"
    )

    notify(
        f"""
<b>🟢 REAL BUY V6</b>

🪙 <b>{token["symbol"]}</b>

⭐ Score:
<b>{token["score"]}/100</b>

💰 Amount:
<b>{result.get("amount_sol", 0):.6f} SOL</b>

🔗 Signature:
<code>{signature}</code>

🕐 {now_utc()}
"""
    )


# ============================================================
# SELL LOG
# ============================================================

def notify_sell(

    trade,

    result,

    reason

):

    signature = result.get(
        "signature",
        "-"
    )

    notify(
        f"""
<b>🔴 REAL SELL V6</b>

🪙 <b>{trade["symbol"]}</b>

🎯 Reason:
<b>{reason}</b>

📈 Return:
<b>{trade.get("return_percent", 0):+.2f}%</b>

💰 PnL:
<b>{trade.get("pnl", 0):+.6f}</b>

🔗 Signature:
<code>{signature}</code>

🕐 {now_utc()}
"""
    )


# ============================================================
# BUY
# ============================================================

def execute_buy(token):

    if not state["enabled"]:
        return False

    if time.time() < num(
        state["paused_until"]
    ):
        return False

    if len(
        state["open_trades"]
    ) >= MAX_OPEN_TRADES:
        return False

    if find_trade(
        token["address"]
    ):
        return False

    if is_cooldown(
        token["address"]
    ):
        return False

    if not check_entry(
        token
    ):
        return False

    result = real_buy(

        token["address"],

        token["symbol"]
    )

    if LIVE_TRADING and not result.get(
        "success"
    ):

        notify(
            f"""
❌ <b>BUY FAILED</b>

🪙 {token["symbol"]}

Jupiter معامله را تأیید نکرد.
"""
        )

        return False

    trade = {

        "id": str(
            int(
                time.time()
                * 1000
            )
        ),

        "address":
            token["address"],

        "symbol":
            token["symbol"],

        "entry_price":
            token["price"],

        "current_price":
            token["price"],

        "highest_price":
            token["price"],

        "amount_sol":
            result.get(
                "amount_sol",
                MAX_TRADE_SOL
            ),

        "entry_time":
            now_utc(),

        "entry_score":
            token["score"],

        "status":
            "OPEN",

        "buy_signature":
            result.get(
                "signature",
                ""
            )
    }

    state[
        "open_trades"
    ].append(
        trade
    )

    save_state()

    notify_buy(
        token,
        result
    )

    return True


# ============================================================
# SELL
# ============================================================

def close_trade(

    trade,

    current_price,

    reason

):

    entry = num(
        trade[
            "entry_price"
        ]
    )

    if entry <= 0:
        return

    change = (

        current_price
        - entry
    ) / entry

    trade[
        "return_percent"
    ] = change * 100

    trade[
        "pnl"
    ] = (
        trade[
            "amount_sol"
        ]
        * change
    )

    # V6 requires the actual token amount
    # to be known before a real sell.
    #
    # The amount is obtained from the wallet
    # token account in the next production step.
    #
    # Therefore we do NOT invent a token amount.

    if LIVE_TRADING:

        notify(
            f"""
⚠️ <b>SELL SAFETY STOP</b>

🪙 {trade["symbol"]}

🎯 Signal:
<b>{reason}</b>

📈 Change:
<b>{change * 100:+.2f}%</b>

ربات از فروش با مقدار حدسی جلوگیری کرد.
مقدار واقعی توکن باید از موجودی کیف پول خوانده شود.
"""
        )

        return

    state[
        "balance"
    ] += (
        trade["amount_sol"]
        + trade["pnl"]
    )

    state[
        "total_pnl"
    ] += trade["pnl"]

    if trade["pnl"] >= 0:

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

    trade[
        "exit_price"
    ] = current_price

    trade[
        "exit_reason"
    ] = reason

    trade[
        "exit_time"
    ] = now_utc()

    trade[
        "status"
    ] = "CLOSED"

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

    save_state()


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

            token = analyze(
                pairs[0]
            )

            if not token:
                continue

            current = num(
                token["price"]
            )

            if current <= 0:
                continue

            trade[
                "current_price"
            ] = current

            highest = num(
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

            entry = num(
                trade[
                    "entry_price"
                ]
            )

            change = (

                current
                - entry
            ) / entry

            # STOP LOSS

            if change <= -STOP_LOSS:

                close_trade(

                    trade,

                    current,

                    "STOP LOSS"
                )

                continue

            # TAKE PROFIT

            if change >= TAKE_PROFIT:

                close_trade(

                    trade,

                    current,

                    "TAKE PROFIT"
                )

                continue

            # TRAILING

            if change >= TRAILING_START:

                trailing_price = (

                    highest
                    * (
                        1
                        - TRAILING_DISTANCE
                    )
                )

                if current <= trailing_price:

                    close_trade(

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

def scan_market():

    results = []

    tokens = latest_solana_tokens()

    seen = set()

    for item in tokens[:60]:

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

        token = analyze(
            pairs[0]
        )

        if token:

            results.append(
                token
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

def trading_engine():

    print(
        "🦈 V6 ENGINE STARTED"
    )

    print(
        "Wallet:",
        WALLET_ADDRESS
    )

    print(
        "LIVE_TRADING:",
        LIVE_TRADING
    )

    while True:

        try:

            manage_trades()

            results = scan_market()

            if state["enabled"]:

                if time.time() >= num(
                    state["paused_until"]
                ):

                    for token in results:

                        if execute_buy(
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
                10,
                SCAN_SECONDS
            )
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

            "🔎 هنوز شکار پیدا نشده.",

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

        valid = check_entry(
            t
        )

        signal = (

            "🟢 BUY CANDIDATE"

            if valid

            else

            "⚪ FILTERED"
        )

        text += f"""
<b>#{i} 🪙 {t["symbol"]}</b>

⭐ Score:
<b>{t["score"]}/100</b>

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

            "📂 معامله بازی نداریم.",

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

💰 Amount:
<b>{trade["amount_sol"]:.6f} SOL</b>

🔗 Buy:
<code>{trade.get("buy_signature", "-")}</code>

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
            trade.get(
                "pnl"
            )
        )

        text += f"""
🪙 <b>{trade["symbol"]}</b>

💰 PnL:
<b>{pnl:+.6f}</b>

📊 Return:
<b>{trade.get("return_percent", 0):+.2f}%</b>

🎯 Reason:
{trade.get("exit_reason", "-")}

🕐 {trade.get("exit_time", "-")}

━━━━━━━━━━━━━━━━━━━━
"""

    bot.send_message(

        chat_id,

        text,

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

        f"""
<b>🦈 SOLANA HUNTER V6</b>

🤖 ربات متصل شد.

⚡ Mode:
<b>{"LIVE TRADING" if LIVE_TRADING else "SAFE TEST MODE"}</b>

👛 Wallet:
<code>{WALLET_ADDRESS}</code>

💎 SOL:
<b>{get_sol_balance():.6f}</b>

🛡️ Max Trade:
<b>{MAX_TRADE_SOL:.4f} SOL</b>
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
def dashboard(message):

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
def top(message):

    send_top(
        message.chat.id
    )


@bot.message_handler(
    commands=["open"]
)
def opened(message):

    send_open(
        message.chat.id
    )


@bot.message_handler(
    commands=["history"]
)
def history(message):

    send_history(
        message.chat.id
    )


@bot.message_handler(
    commands=["wallet"]
)
def wallet_command(message):

    try:

        balance = get_sol_balance()

        bot.send_message(

            message.chat.id,

            f"""
<b>👛 WALLET</b>

Address:
<code>{WALLET_ADDRESS}</code>

💎 SOL:
<b>{balance:.6f}</b>

⚡ Mode:
<b>{"LIVE" if LIVE_TRADING else "TEST"}</b>
""",

            reply_markup=main_menu()
        )

    except Exception as e:

        bot.send_message(

            message.chat.id,

            f"❌ Wallet RPC error:\n<code>{e}</code>"
        )


# ============================================================
# MENU
# ============================================================

@bot.message_handler(
    func=lambda message: True
)
def menu(message):

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

    elif text == "💰 کیف پول":

        wallet_command(
            message
        )

    elif text == "⏸️ توقف / ▶️ ادامه":

        state[
            "enabled"
        ] = not state[
            "enabled"
        ]

        save_state()

        bot.send_message(

            message.chat.id,

            (
                "🟢 ربات فعال شد."
                if state["enabled"]
                else
                "⏸️ ربات متوقف شد."
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
# MAIN
# ============================================================

def main():

    load_state()

    print(
        "=================================================="
    )

    print(
        "🦈 SOLANA HUNTER V6"
    )

    print(
        "Wallet:",
        WALLET_ADDRESS
    )

    print(
        "LIVE_TRADING:",
        LIVE_TRADING
    )

    print(
        "RPC:",
        RPC_URL
    )

    print(
        "=================================================="
    )

    # Wallet/RPC connectivity test

    try:

        balance = get_sol_balance()

        print(
            f"💎 Wallet SOL: {balance:.6f}"
        )

    except Exception as e:

        print(
            "❌ RPC ERROR:",
            e
        )

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


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    main()
