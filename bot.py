import os
import time
import json
import base64
import threading
from datetime import datetime, timezone

import requests
import base58
import telebot
from telebot import types

from solders.keypair import Keypair
from solders.transaction import VersionedTransaction


# ============================================================
# 🦈 SOLANA HUNTER V6
# REAL TRADING
# Jupiter V6 + Telegram Dashboard + Risk Management
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
RPC_URL = os.getenv(
    "RPC_URL",
    "https://api.mainnet-beta.solana.com"
)

# MUST be explicitly enabled in GitHub Secrets
LIVE_TRADING = os.getenv(
    "LIVE_TRADING",
    "false"
).lower() == "true"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")

if not PRIVATE_KEY:
    raise RuntimeError("PRIVATE_KEY is missing")

if not LIVE_TRADING:
    raise RuntimeError(
        "LIVE_TRADING must be set to true before real trading starts."
    )


# ============================================================
# CONSTANTS
# ============================================================

SOL_MINT = "So11111111111111111111111111111111111111112"

DEX_API = "https://api.dexscreener.com"

JUP_QUOTE = "https://quote-api.jup.ag/v6/quote"
JUP_SWAP = "https://quote-api.jup.ag/v6/swap"

STATE_FILE = "paper_state_v6.json"
CONFIG_FILE = "bot_config_v6.json"

# Starting value is only used for statistics.
START_BALANCE_SOL = 0.0

LAMPORTS_PER_SOL = 1_000_000_000

# Safety reserve for network fees.
MIN_SOL_RESERVE = 0.01


# ============================================================
# WALLET
# ============================================================

try:
    secret = base58.b58decode(PRIVATE_KEY)

    if len(secret) == 64:
        keypair = Keypair.from_bytes(secret)
    elif len(secret) == 32:
        keypair = Keypair.from_seed(secret)
    else:
        raise ValueError(
            "PRIVATE_KEY must be a base58 32-byte seed or 64-byte keypair."
        )

except Exception as e:
    raise RuntimeError(
        f"PRIVATE_KEY is invalid: {e}"
    )

WALLET = str(keypair.pubkey())


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

    # Discovery
    "min_score": 75,
    "min_buy_pressure": 60.0,
    "min_liquidity": 30000.0,
    "min_m5_volume": 15000.0,

    "min_m5_change": -5.0,
    "max_m5_change": 15.0,

    # Real trading
    "risk_per_trade": 0.10,
    "max_open_trades": 2,

    # Exits
    "take_profit": 0.15,
    "stop_loss": 0.08,

    # Profit lock
    "profit_lock_trigger": 0.10,
    "profit_lock_percent": 0.50,

    # Trailing
    "trailing_start": 0.12,
    "trailing_distance": 0.05,

    # Jupiter
    "slippage_bps": 100,

    # Scan
    "scan_seconds": 20,

    # Protection
    "cooldown_seconds": 600,
    "crash_m5": -8.0,

    "max_consecutive_losses": 3,
    "loss_pause_seconds": 900,

    # Position limits
    "min_trade_sol": 0.005,
    "max_trade_sol": 0.50,

    "enabled": True
}


config = DEFAULT_CONFIG.copy()


# ============================================================
# STATE
# ============================================================

state = {

    "balance_sol": 0.0,

    "starting_balance_sol": 0.0,

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

    "chat_id": None,

    "dashboard_message_id": None,

    "waiting_setting": None
}


lock = threading.Lock()


# ============================================================
# BASIC HELPERS
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


def money_sol(value):
    return f"{num(value):.6f} SOL"


def rpc(method, params=None):

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params or []
    }

    response = session.post(
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

    return data.get("result")


# ============================================================
# STATE FILE
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
# CONFIG FILE
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
# SOL BALANCE
# ============================================================

def get_sol_balance():

    result = rpc(
        "getBalance",
        [WALLET]
    )

    lamports = int(
        result["value"]
    )

    return lamports / LAMPORTS_PER_SOL


def update_balance():

    try:

        state["balance_sol"] = (
            get_sol_balance()
        )

        if (
            state["starting_balance_sol"]
            <= 0
        ):

            state[
                "starting_balance_sol"
            ] = state[
                "balance_sol"
            ]

        save_state()

    except Exception as e:

        print(
            "BALANCE ERROR:",
            e
        )


# ============================================================
# TELEGRAM MENU
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
            "ℹ️ وضعیت"
        )
    )

    return markup


# ============================================================
# SETTINGS
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

        ("🛡️ Risk / Trade", "set_risk"),
        ("📂 Max Trades", "set_max_trades"),

        ("⛽ Slippage", "set_slippage"),
        ("⏱️ Scan", "set_scan"),

        ("🚫 Cooldown", "set_cooldown")
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

━━━━━━━━━━━━━━━━━━━━

🎯 Take Profit:
<b>+{config["take_profit"] * 100:.0f}%</b>

🛑 Stop Loss:
<b>-{config["stop_loss"] * 100:.0f}%</b>

🔒 Profit Lock:
<b>+{config["profit_lock_trigger"] * 100:.0f}%</b>

📈 Trailing:
<b>+{config["trailing_start"] * 100:.0f}% /
-{config["trailing_distance"] * 100:.0f}%</b>

━━━━━━━━━━━━━━━━━━━━

🛡️ Risk:
<b>{config["risk_per_trade"] * 100:.0f}%</b>

📂 Max Trades:
<b>{config["max_open_trades"]}</b>

⛽ Slippage:
<b>{config["slippage_bps"] / 100:.2f}%</b>

⏱️ Scan:
<b>{config["scan_seconds"]}s</b>

🚫 Cooldown:
<b>{config["cooldown_seconds"]}s</b>

━━━━━━━━━━━━━━━━━━━━

🔴 MODE:
<b>REAL TRADING</b>

💰 Wallet:
<code>{WALLET}</code>
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
# ENTRY FILTER
# ============================================================

def check_entry(t):

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

    if t["m5"] <= config["crash_m5"]:
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


def is_cooldown(address):

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
# JUPITER QUOTE
# ============================================================

def jupiter_quote(
    input_mint,
    output_mint,
    amount
):

    params = {

        "inputMint": input_mint,

        "outputMint": output_mint,

        "amount": str(
            int(amount)
        ),

        "slippageBps": int(
            config["slippage_bps"]
        ),

        "swapMode": "ExactIn"
    }

    response = session.get(
        JUP_QUOTE,
        params=params,
        timeout=20
    )

    response.raise_for_status()

    data = response.json()

    if not data.get(
        "outAmount"
    ):
        raise RuntimeError(
            "Jupiter returned no route."
        )

    return data


# ============================================================
# JUPITER SWAP
# ============================================================

def jupiter_swap(
    input_mint,
    output_mint,
    amount
):

    quote = jupiter_quote(
        input_mint,
        output_mint,
        amount
    )

    body = {

        "quoteResponse": quote,

        "userPublicKey": WALLET,

        "wrapAndUnwrapSol": True,

        "dynamicComputeUnitLimit": True,

        "prioritizationFeeLamports": "auto"
    }

    response = session.post(
        JUP_SWAP,
        json=body,
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    transaction_b64 = data.get(
        "swapTransaction"
    )

    if not transaction_b64:
        raise RuntimeError(
            f"Jupiter swap error: {data}"
        )

    tx_bytes = base64.b64decode(
        transaction_b64
    )

    transaction = (
        VersionedTransaction.from_bytes(
            tx_bytes
        )
    )

    transaction.sign(
        [keypair]
    )

    raw = bytes(
        transaction
    )

    result = rpc(
        "sendTransaction",
        [
            base64.b64encode(
                raw
            ).decode(),
            {
                "encoding": "base64",
                "skipPreflight": False,
                "maxRetries": 3
            }
        ]
    )

    return str(
        result
    ), quote


# ============================================================
# BUY REAL
# ============================================================

def real_buy(t):

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

    if is_cooldown(
        t["address"]
    ):
        return False

    if not check_entry(t):
        return False

    try:

        sol_balance = get_sol_balance()

        available = max(
            0,
            sol_balance
            - MIN_SOL_RESERVE
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

        lamports = int(
            position
            * LAMPORTS_PER_SOL
        )

        print(
            f"BUY {t['symbol']} "
            f"{position:.6f} SOL"
        )

        txid, quote = jupiter_swap(
            SOL_MINT,
            t["address"],
            lamports
        )

        token_amount = int(
            quote["outAmount"]
        )

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

            "token_amount_raw": token_amount,

            "entry_score": t["score"],

            "entry_pressure": t[
                "buy_pressure"
            ],

            "entry_time": now_utc(),

            "buy_tx": txid,

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
            position,
            txid
        )

        return True

    except Exception as e:

        print(
            "REAL BUY ERROR:",
            e
        )

        send_error(
            f"BUY {t.get('symbol', '?')}",
            str(e)
        )

        return False


# ============================================================
# REAL SELL
# ============================================================

def real_sell(
    trade,
    percent,
    reason,
    current_price
):

    try:

        raw_total = int(
            trade[
                "token_amount_raw"
            ]
        )

        raw_sell = int(
            raw_total
            * percent
        )

        if raw_sell <= 0:
            return False

        txid, quote = jupiter_swap(
            trade["address"],
            SOL_MINT,
            raw_sell
        )

        out_lamports = int(
            quote["outAmount"]
        )

        out_sol = (
            out_lamports
            / LAMPORTS_PER_SOL
        )

        entry_sol = (
            trade["position_sol"]
            * percent
        )

        pnl = (
            out_sol
            - entry_sol
        )

        if percent >= 0.999:

            trade[
                "token_amount_raw"
            ] = 0

            trade[
                "remaining_percent"
            ] = 0

            trade[
                "exit_price"
            ] = current_price

            trade[
                "exit_reason"
            ] = reason

            trade[
                "sell_tx"
            ] = txid

            trade[
                "pnl_sol"
            ] = pnl

            trade[
                "return_percent"
            ] = (
                pnl / entry_sol * 100
                if entry_sol > 0
                else 0
            )

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
                out_sol,
                reason,
                txid
            )

        else:

            trade[
                "token_amount_raw"
            ] = (
                raw_total
                - raw_sell
            )

            trade[
                "remaining_percent"
            ] = (
                trade[
                    "remaining_percent"
                ]
                - percent
            )

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
                out_sol,
                pnl,
                txid
            )

        return True

    except Exception as e:

        print(
            "REAL SELL ERROR:",
            e
        )

        send_error(
            f"SELL {trade.get('symbol', '?')}",
            str(e)
        )

        return False


# ============================================================
# MANAGE OPEN TRADES
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

            highest = num(
                trade[
                    "highest_price"
                ]
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

            if entry <= 0:
                continue

            change = (
                current - entry
            ) / entry

            # ================================================
            # PROFIT LOCK
            # ================================================

            if (
                not trade["locked"]
                and change
                >= config[
                    "profit_lock_trigger"
                ]
            ):

                real_sell(
                    trade,
                    config[
                        "profit_lock_percent"
                    ],
                    "PROFIT LOCK",
                    current
                )

                continue

            # ================================================
            # STOP LOSS
            # ================================================

            if not trade["locked"]:

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

                    real_sell(
                        trade,
                        1.0,
                        "STOP LOSS",
                        current
                    )

                    continue

            # ================================================
            # TAKE PROFIT
            # ================================================

            if (
                not trade["locked"]
                and change
                >= config[
                    "take_profit"
                ]
            ):

                real_sell(
                    trade,
                    1.0,
                    "TAKE PROFIT",
                    current
                )

                continue

            # ================================================
            # TRAILING
            # ================================================

            if (
                trade["locked"]
                and change
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

                    real_sell(
                        trade,
                        1.0,
                        "TRAILING PROFIT",
                        current
                    )

                    continue

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
                results.append(t)

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

    except Exception as e:

        print(
            "SCAN ERROR:",
            e
        )

        return []


# ============================================================
# EQUITY
# ============================================================

def estimated_equity():

    try:

        balance = get_sol_balance()

    except Exception:

        balance = state[
            "balance_sol"
        ]

    return balance


def pnl_sol():

    current = estimated_equity()

    start = num(
        state[
            "starting_balance_sol"
        ]
    )

    if start <= 0:
        return 0.0

    return current - start


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


# ============================================================
# DASHBOARD
# ============================================================

def dashboard_text():

    try:

        balance = get_sol_balance()

        state[
            "balance_sol"
        ] = balance

    except Exception:

        balance = state[
            "balance_sol"
        ]

    if (
        state[
            "starting_balance_sol"
        ] <= 0
    ):

        state[
            "starting_balance_sol"
        ] = balance

    pnl = (
        balance
        - state[
            "starting_balance_sol"
        ]
    )

    if not config["enabled"]:

        status = "⏸️ PAUSED"

    elif time.time() < num(
        state["paused_until"]
    ):

        status = "🟡 LOSS PROTECTION"

    else:

        status = "🟢 LIVE"

    return f"""
<b>🦈 SOLANA HUNTER V6</b>

━━━━━━━━━━━━━━━━━━━━

🔴 <b>REAL TRADING</b>

🤖 Status:
<b>{status}</b>

💼 Wallet:
<code>{WALLET}</code>

━━━━━━━━━━━━━━━━━━━━

💰 SOL Balance:
<b>{balance:.6f} SOL</b>

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

⛽ Slippage:
<b>{config["slippage_bps"] / 100:.2f}%</b>

━━━━━━━━━━━━━━━━━━━━

🕐 Last Scan:
{state["last_scan"] or "-"}
"""


# ============================================================
# DASHBOARD SEND
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
# TELEGRAM ALERTS
# ============================================================

def send_buy(
    t,
    position,
    txid
):

    chat_id = state.get(
        "chat_id"
    )

    if not chat_id:
        return

    bot.send_message(
        chat_id,

        f"""
<b>🟢 REAL BUY V6</b>

🪙 <b>{t["symbol"]}</b>

⭐ Score:
<b>{t["score"]}/100</b>

💵 Price:
${t["price"]:.10f}

💧 Liquidity:
${t["liquidity"]:,.0f}

🟢 Buy Pressure:
{t["buy_pressure"]:.1f}%

📈 M5:
{t["m5"]:+.2f}%

💰 Position:
<b>{position:.6f} SOL</b>

🛡️ Risk:
{config["risk_per_trade"] * 100:.0f}%

🔗 TX:
<code>{txid}</code>

🕐 {now_utc()}
"""
    )


def send_profit_lock(
    trade,
    out_sol,
    pnl,
    txid
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

💰 Received:
<b>+{out_sol:.6f} SOL</b>

📈 Locked PnL:
<b>{pnl:+.6f} SOL</b>

📂 Remaining:
<b>{trade["remaining_percent"] * 100:.0f}%</b>

🔗 TX:
<code>{txid}</code>

🕐 {now_utc()}
"""
    )


def send_sell(
    trade,
    pnl,
    out_sol,
    reason,
    txid
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
<b>{emoji} REAL SELL V6</b>

🪙 <b>{trade["symbol"]}</b>

💰 Received:
<b>{out_sol:.6f} SOL</b>

📊 PnL:
<b>{pnl:+.6f} SOL</b>

🎯 Reason:
<b>{reason}</b>

📈 Return:
<b>{trade.get("return_percent", 0):+.2f}%</b>

🔗 TX:
<code>{txid}</code>

🕐 {now_utc()}
"""
    )


def send_error(
    title,
    error
):

    chat_id = state.get(
        "chat_id"
    )

    if not chat_id:
        return

    bot.send_message(
        chat_id,

        f"""
<b>⚠️ V6 ERROR</b>

<b>{title}</b>

<code>{str(error)[:2500]}</code>

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

        valid = check_entry(
            t
        )

        signal = (
            "🟢 BUY"
            if valid
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
        "<b>📂 OPEN REAL TRADES</b>\n\n"
    )

    for trade in trades:

        entry = num(
            trade[
                "entry_price"
            ]
        )

        current = num(
            trade[
                "current_price"
            ]
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
        "<b>📜 REAL TRADE HISTORY</b>\n\n"
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
# SETTINGS CALLBACK
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
            "⭐ حداقل Score؟",

        "set_pressure":
            "🟢 حداقل Buy Pressure؟",

        "set_liquidity":
            "💧 حداقل Liquidity به دلار؟",

        "set_volume":
            "📊 حداقل M5 Volume؟",

        "set_tp":
            "🎯 Take Profit به درصد؟",

        "set_sl":
            "🛑 Stop Loss به درصد؟",

        "set_profit_lock":
            "🔒 Profit Lock به درصد؟",

        "set_trailing":
            "📈 Trailing Distance به درصد؟",

        "set_risk":
            "🛡️ Risk هر معامله به درصد؟",

        "set_max_trades":
            "📂 حداکثر معاملات باز؟",

        "set_slippage":
            "⛽ Slippage به درصد؟ مثلاً 1",

        "set_scan":
            "⏱️ Scan چند ثانیه؟",

        "set_cooldown":
            "🚫 Cooldown چند ثانیه؟"
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
            "عدد جدید را بفرست."
        ),
        reply_markup=main_menu()
    )


# ============================================================
# SETTING VALUE
# ============================================================

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

    raw = (
        message.text or ""
    ).strip()

    try:

        value = float(
            raw.replace(
                "%",
                ""
            )
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

        elif key == "set_slippage":

            config[
                "slippage_bps"
            ] = int(
                max(
                    10,
                    min(
                        500,
                        value * 100
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

        send_settings(
            message.chat.id
        )

    except Exception:

        bot.send_message(
            message.chat.id,

            "❌ مقدار نامعتبر. فقط عدد بفرست.",

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
def command_start(message):

    state[
        "chat_id"
    ] = message.chat.id

    save_state()

    bot.send_message(
        message.chat.id,

        f"""
<b>🦈 SOLANA HUNTER V6</b>

🟢 <b>REAL TRADING ENABLED</b>

⚡ Jupiter V6
💰 Real Buy / Sell
🛡️ Risk Management
🎯 TP / SL
🔒 Profit Lock
📈 Trailing
🚫 Cooldown
📊 Telegram Dashboard

💼 Wallet:
<code>{WALLET}</code>

⚠️ معاملات با پول واقعی انجام می‌شوند.
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
# BOTTOM MENU
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
            if config["enabled"]
            else "⏸️ ربات متوقف شد."
        )

        bot.send_message(
            message.chat.id,
            status,
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

            update_balance()

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

                    if real_buy(
                        token
                    ):
                        break

            update_dashboard()

        except Exception as e:

            print(
                "ENGINE ERROR:",
                e
            )

            send_error(
                "ENGINE",
                str(e)
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
        """
============================================================
🦈 SOLANA HUNTER V6
============================================================

🔴 REAL TRADING: ENABLED
⚡ Jupiter V6
💰 REAL BUY / SELL
🛡️ RISK MANAGEMENT
🎯 TP / SL
🔒 PROFIT LOCK
📈 TRAILING
🚫 COOLDOWN
📊 TELEGRAM DASHBOARD

Wallet:
""" + WALLET + """

============================================================
"""
    )

    load_config()

    load_state()

    try:

        update_balance()

    except Exception as e:

        print(
            "INITIAL BALANCE ERROR:",
            e
        )

    engine = threading.Thread(
        target=trading_engine,
        daemon=True
    )

    engine.start()

    print(
        "🟢 TRADING ENGINE STARTED"
    )

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
