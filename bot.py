# ============================================================
# 🦈 SOLANA HUNTER V6 LIVE CORE
# ============================================================

import os
import base64
import requests

from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from solana.rpc.api import Client


# ============================================================
# ENV
# ============================================================

LIVE_TRADING = os.getenv(
    "LIVE_TRADING",
    "0"
).lower() in ("1", "true", "yes")

SOLANA_RPC = os.getenv(
    "SOLANA_RPC",
    "https://api.mainnet-beta.solana.com"
)

JUPITER_API_KEY = os.getenv(
    "JUPITER_API_KEY"
)

BOT_PRIVATE_KEY = os.getenv(
    "BOT_PRIVATE_KEY"
)


# ============================================================
# SAFETY
# ============================================================

if LIVE_TRADING:

    if not BOT_PRIVATE_KEY:
        raise RuntimeError(
            "BOT_PRIVATE_KEY is missing"
        )

    if not JUPITER_API_KEY:
        raise RuntimeError(
            "JUPITER_API_KEY is missing"
        )


# ============================================================
# WALLET
# ============================================================

wallet = None
rpc = Client(SOLANA_RPC)

if BOT_PRIVATE_KEY:

    try:

        # Base58 private key
        from solders.keypair import Keypair

        wallet = Keypair.from_base58_string(
            BOT_PRIVATE_KEY
        )

    except Exception as e:

        raise RuntimeError(
            "Invalid BOT_PRIVATE_KEY"
        ) from e


# ============================================================
# SOL / USDC
# ============================================================

SOL_MINT = (
    "So11111111111111111111111111111111111111112"
)

USDC_MINT = (
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
)


# ============================================================
# JUPITER
# ============================================================

JUPITER_BASE = (
    "https://api.jup.ag"
)


def jupiter_headers():

    headers = {
        "Content-Type":
            "application/json"
    }

    if JUPITER_API_KEY:

        headers[
            "x-api-key"
        ] = JUPITER_API_KEY

    return headers


# ============================================================
# QUOTE
# ============================================================

def get_jupiter_quote(
    input_mint,
    output_mint,
    amount_lamports,
    slippage_bps
):

    url = (
        f"{JUPITER_BASE}"
        "/swap/v1/quote"
    )

    params = {

        "inputMint":
            input_mint,

        "outputMint":
            output_mint,

        "amount":
            str(
                int(
                    amount_lamports
                )
            ),

        "slippageBps":
            str(
                int(
                    slippage_bps
                )
            ),

        "restrictIntermediateTokens":
            "true"
    }

    response = requests.get(

        url,

        params=params,

        headers=jupiter_headers(),

        timeout=15
    )

    response.raise_for_status()

    data = response.json()

    if data.get(
        "error"
    ):

        raise RuntimeError(
            data["error"]
        )

    return data


# ============================================================
# BUILD SWAP
# ============================================================

def build_swap_transaction(
    quote
):

    if not wallet:

        raise RuntimeError(
            "Wallet not loaded"
        )

    url = (
        f"{JUPITER_BASE}"
        "/swap/v1/swap"
    )

    payload = {

        "quoteResponse":
            quote,

        "userPublicKey":
            str(
                wallet.pubkey()
            ),

        "wrapAndUnwrapSol":
            True,

        "dynamicComputeUnitLimit":
            True,

        "prioritizationFeeLamports":
            "auto"
    }

    response = requests.post(

        url,

        json=payload,

        headers=jupiter_headers(),

        timeout=20
    )

    response.raise_for_status()

    data = response.json()

    if not data.get(
        "swapTransaction"
    ):

        raise RuntimeError(
            "Jupiter did not return swapTransaction"
        )

    return data


# ============================================================
# EXECUTE
# ============================================================

def execute_swap(
    input_mint,
    output_mint,
    amount_lamports,
    slippage_bps
):

    if not LIVE_TRADING:

        print(
            "🧪 PAPER MODE: "
            "REAL SWAP BLOCKED"
        )

        return {
            "success": False,
            "paper": True
        }

    if not wallet:

        raise RuntimeError(
            "Wallet unavailable"
        )

    # --------------------------------------------------------
    # QUOTE
    # --------------------------------------------------------

    quote = get_jupiter_quote(

        input_mint,

        output_mint,

        amount_lamports,

        slippage_bps
    )

    # --------------------------------------------------------
    # BUILD
    # --------------------------------------------------------

    swap_data = build_swap_transaction(
        quote
    )

    raw_tx = base64.b64decode(
        swap_data[
            "swapTransaction"
        ]
    )

    # --------------------------------------------------------
    # DESERIALIZE
    # --------------------------------------------------------

    transaction = (
        VersionedTransaction.from_bytes(
            raw_tx
        )
    )

    # --------------------------------------------------------
    # SIGN
    # --------------------------------------------------------

    signed = VersionedTransaction(
        transaction.message,
        [
            wallet.sign_message(
                bytes(
                    transaction.message
                )
            )
        ]
    )

    # --------------------------------------------------------
    # SEND
    # --------------------------------------------------------

    result = rpc.send_raw_transaction(
        bytes(signed)
    )

    signature = str(
        result.value
    )

    print(
        "🟢 LIVE SWAP SENT:",
        signature
    )

    return {

        "success":
            True,

        "signature":
            signature,

        "paper":
            False
    }


# ============================================================
# BUY TOKEN
# ============================================================

def live_buy(
    token_address,
    sol_amount
):

    if not LIVE_TRADING:

        return {
            "success": False,
            "paper": True
        }

    lamports = int(
        float(
            sol_amount
        )
        * 1_000_000_000
    )

    slippage_bps = int(
        config[
            "max_slippage"
        ]
        * 10000
    )

    return execute_swap(

        SOL_MINT,

        token_address,

        lamports,

        slippage_bps
    )


# ============================================================
# SELL TOKEN
# ============================================================

def live_sell(
    token_address,
    token_amount
):

    if not LIVE_TRADING:

        return {
            "success": False,
            "paper": True
        }

    slippage_bps = int(
        config[
            "max_slippage"
        ]
        * 10000
    )

    return execute_swap(

        token_address,

        SOL_MINT,

        int(
            token_amount
        ),

        slippage_bps
    )
