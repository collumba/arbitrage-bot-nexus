"""
╔══════════════════════════════════════════════════════════════╗
║          ARBITRAGE BOT — CONFIGURATION                       ║
║          Modo: PAPER (simulação) / LIVE (real)               ║
╚══════════════════════════════════════════════════════════════╝
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ─── MODO DE OPERAÇÃO ───────────────────────────────────────
TRADING_MODE = os.getenv("TRADING_MODE", "paper")  # "paper" ou "live"
INITIAL_BALANCE_USD = float(os.getenv("INITIAL_BALANCE", "10000"))

# ─── EXCHANGES ──────────────────────────────────────────────
EXCHANGES = {
    "binance": {
        "apiKey": os.getenv("BINANCE_API_KEY", ""),
        "secret": os.getenv("BINANCE_SECRET", ""),
        "sandbox": TRADING_MODE == "paper",
    },
    "bybit": {
        "apiKey": os.getenv("BYBIT_API_KEY", ""),
        "secret": os.getenv("BYBIT_SECRET", ""),
        "sandbox": TRADING_MODE == "paper",
    },
    "okx": {
        "apiKey": os.getenv("OKX_API_KEY", ""),
        "secret": os.getenv("OKX_SECRET", ""),
        "password": os.getenv("OKX_PASSWORD", ""),
        "sandbox": TRADING_MODE == "paper",
    },
    "kucoin": {
        "apiKey": os.getenv("KUCOIN_API_KEY", ""),
        "secret": os.getenv("KUCOIN_SECRET", ""),
        "password": os.getenv("KUCOIN_PASSWORD", ""),
        "sandbox": TRADING_MODE == "paper",
    },
}

# ─── ESTRATÉGIAS ────────────────────────────────────────────
STRATEGIES = {
    "cross_exchange": {
        "enabled": True,
        "pairs": ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "ADA/USDT"],
        "min_spread_pct": 0.15,
        "max_trade_usd": 500,
        "scan_interval_sec": 2,
    },
    "triangular": {
        "enabled": True,
        "exchange": "binance",
        "base_currencies": ["USDT", "BTC", "ETH"],
        "min_profit_pct": 0.08,
        "max_trade_usd": 300,
        "scan_interval_sec": 1,
    },
    "statistical": {
        "enabled": True,
        "pairs": [
            ("BTC/USDT", "ETH/USDT"),
            ("SOL/USDT", "AVAX/USDT"),
            ("LINK/USDT", "DOT/USDT"),
        ],
        "lookback_periods": 100,
        "z_score_entry": 2.0,
        "z_score_exit": 0.5,
        "max_trade_usd": 400,
        "scan_interval_sec": 5,
    },
    "funding_rate": {
        "enabled": True,
        "pairs": ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
        "min_rate_pct": 0.01,
        "max_trade_usd": 1000,
        "scan_interval_sec": 30,
    },
    "dex_cex": {
        "enabled": True,
        "pairs": ["ETH/USDT", "SOL/USDT"],
        "min_spread_pct": 0.3,
        "max_trade_usd": 300,
        "scan_interval_sec": 5,
        "dex_apis": {
            "uniswap_v3": "https://api.thegraph.com/subgraphs/name/uniswap/uniswap-v3",
        },
    },
}

# ─── RISK MANAGEMENT ───────────────────────────────────────
RISK = {
    "max_drawdown_pct": 5.0,
    "max_daily_loss_usd": 200,
    "max_open_positions": 10,
    "stop_loss_pct": 2.0,
    "position_size_pct": 5.0,
}

# ─── SERVER ─────────────────────────────────────────────────
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8888
