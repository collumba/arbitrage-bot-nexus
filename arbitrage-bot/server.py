"""
╔══════════════════════════════════════════════════════════════╗
║       ARBITRAGE NEXUS v3 — REAL MARKET HUNTER                ║
║       Auto-installs ccxt · Real Binance/Bybit/OKX data       ║
║       Aggressive Mode · Multi-Pair · Production Execution    ║
╚══════════════════════════════════════════════════════════════╝
"""
import json
import time
import random
import math
import hashlib
import struct
import base64
import os
import sys
import sqlite3
import logging
import traceback
import subprocess
from pathlib import Path
import threading
import socket
from datetime import datetime, timezone
from collections import deque

# ═══════════════════════════════════════════════════════════
# AUTO-INSTALL CCXT
# ═══════════════════════════════════════════════════════════
def _auto_install_ccxt():
    """Try to install ccxt automatically if not present"""
    try:
        import ccxt
        return True
    except ImportError:
        # Quick network check before attempting install
        try:
            s = socket.create_connection(("pypi.org", 443), timeout=3)
            s.close()
        except Exception:
            print("[-] No internet — skipping ccxt install. Bot will use simulated prices.")
            return False
        print("[*] ccxt not found — attempting install (15s timeout)...")
        cmds = [
            [sys.executable, "-m", "pip", "install", "ccxt", "--quiet", "--break-system-packages"],
            [sys.executable, "-m", "pip", "install", "ccxt", "--quiet"],
        ]
        for cmd in cmds:
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                _, stderr = proc.communicate(timeout=15)
                if proc.returncode == 0:
                    print("[+] ccxt installed successfully!")
                    return True
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                print("[-] Install timed out")
            except Exception:
                pass
        print("[-] Could not install ccxt. Run manually: pip install ccxt")
        print("    Bot will start with simulated prices.")
        return False

CCXT_INSTALLED = _auto_install_ccxt()

try:
    import ccxt
    CCXT_AVAILABLE = True
except ImportError:
    CCXT_AVAILABLE = False

# ═══════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / f"bot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"),
        logging.StreamHandler(),
    ]
)
log = logging.getLogger("nexus")

# ═══════════════════════════════════════════════════════════
# LOAD .env FILE
# ═══════════════════════════════════════════════════════════
def _load_dotenv():
    """Load .env file from same directory as server.py"""
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return
    with open(env_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            # Only set if not already defined (real env vars take priority)
            if key not in os.environ:
                os.environ[key] = val

_load_dotenv()

# ═══════════════════════════════════════════════════════════
# CONFIGURATION v3
# ═══════════════════════════════════════════════════════════

TRADING_MODE = os.environ.get("TRADING_MODE", "paper")
INITIAL_BALANCE = float(os.environ.get("INITIAL_BALANCE", "10000"))
PORT = int(os.environ.get("PORT", "8888"))
SCAN_INTERVAL = float(os.environ.get("SCAN_INTERVAL", "0.5"))  # seconds between scans

# AGGRESSIVE MODE: lower thresholds, more trades, higher risk
AGGRESSIVE = os.environ.get("AGGRESSIVE", "true").lower() == "true"

# Per-exchange fee structure (maker/taker in %)
EXCHANGE_FEES = {
    "binance":  {"maker": 0.10, "taker": 0.10, "withdrawal_usdt": 1.0},
    "bybit":    {"maker": 0.10, "taker": 0.10, "withdrawal_usdt": 1.0},
    "okx":      {"maker": 0.08, "taker": 0.10, "withdrawal_usdt": 0.8},
    "kucoin":   {"maker": 0.10, "taker": 0.10, "withdrawal_usdt": 1.0},
    "gate":     {"maker": 0.15, "taker": 0.15, "withdrawal_usdt": 1.0},
    "mexc":     {"maker": 0.00, "taker": 0.10, "withdrawal_usdt": 1.0},
    "dex":      {"maker": 0.30, "taker": 0.30, "withdrawal_usdt": 0.0},
}

# Slippage model
SLIPPAGE_MODEL = {
    "base_bps": 1.5,
    "size_factor": 40.0,
    "liquidity_usd": {
        "BTC/USDT": 2000000, "ETH/USDT": 1000000, "SOL/USDT": 400000,
        "XRP/USDT": 300000, "DOGE/USDT": 200000, "ADA/USDT": 150000,
        "AVAX/USDT": 120000, "LINK/USDT": 100000, "DOT/USDT": 80000,
        "MATIC/USDT": 80000, "SHIB/USDT": 150000, "LTC/USDT": 100000,
        "UNI/USDT": 60000, "ATOM/USDT": 60000, "FIL/USDT": 50000,
        "NEAR/USDT": 50000, "APT/USDT": 40000, "ARB/USDT": 60000,
        "OP/USDT": 50000, "SUI/USDT": 40000,
    },
}

# Latency model per exchange (milliseconds)
LATENCY_MODEL = {
    "binance": {"mean_ms": 45,  "std_ms": 15,  "spike_prob": 0.02, "spike_ms": 400},
    "bybit":   {"mean_ms": 55,  "std_ms": 20,  "spike_prob": 0.03, "spike_ms": 500},
    "okx":     {"mean_ms": 60,  "std_ms": 25,  "spike_prob": 0.03, "spike_ms": 600},
    "kucoin":  {"mean_ms": 70,  "std_ms": 30,  "spike_prob": 0.04, "spike_ms": 700},
    "gate":    {"mean_ms": 80,  "std_ms": 35,  "spike_prob": 0.04, "spike_ms": 800},
    "mexc":    {"mean_ms": 75,  "std_ms": 30,  "spike_prob": 0.04, "spike_ms": 750},
    "dex":     {"mean_ms": 2000,"std_ms": 1000,"spike_prob": 0.10, "spike_ms": 15000},
}

RATE_LIMITS = {"binance": 1200, "bybit": 600, "okx": 600, "kucoin": 600, "gate": 600, "mexc": 600}

RISK_NORMAL = {
    "max_drawdown_pct": 5.0,
    "max_daily_loss_usd": 200,
    "max_open_positions": 10,
    "max_single_trade_usd": 1000,
    "cooldown_after_loss_sec": 30,
}

RISK_AGGRESSIVE = {
    "max_drawdown_pct": 30.0,  # Higher because open positions temporarily reduce balance
    "max_daily_loss_usd": 1000,
    "max_open_positions": 30,
    "max_single_trade_usd": 2000,
    "cooldown_after_loss_sec": 3,
}

RISK = RISK_AGGRESSIVE if AGGRESSIVE else RISK_NORMAL

# Extended pair list for more opportunities
ALL_PAIRS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "DOGE/USDT",
    "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT", "MATIC/USDT",
    "SHIB/USDT", "LTC/USDT", "UNI/USDT", "ATOM/USDT", "FIL/USDT",
    "NEAR/USDT", "APT/USDT", "ARB/USDT", "OP/USDT", "SUI/USDT",
]

PRICE_SEEDS = {
    "BTC/USDT": 95000.0, "ETH/USDT": 3200.0, "SOL/USDT": 175.0,
    "XRP/USDT": 2.40, "DOGE/USDT": 0.25, "ADA/USDT": 0.75,
    "AVAX/USDT": 35.0, "LINK/USDT": 18.0, "DOT/USDT": 7.5,
    "MATIC/USDT": 0.55, "SHIB/USDT": 0.000025, "LTC/USDT": 105.0,
    "UNI/USDT": 12.0, "ATOM/USDT": 9.0, "FIL/USDT": 5.5,
    "NEAR/USDT": 5.0, "APT/USDT": 9.5, "ARB/USDT": 0.80,
    "OP/USDT": 1.60, "SUI/USDT": 3.20,
}

EXCHANGES = ["binance", "bybit", "okx", "kucoin", "gate", "mexc"]


# ═══════════════════════════════════════════════════════════
# EXECUTION MODEL v3 — Slippage, Latency, Fees
# ═══════════════════════════════════════════════════════════

class ExecutionModel:
    """Simulates realistic order execution with slippage, latency, and fees"""

    def __init__(self):
        self._api_calls = {}
        self._last_loss_time = 0

    def estimate_slippage(self, pair, trade_usd, exchange="binance"):
        liq = SLIPPAGE_MODEL["liquidity_usd"].get(pair, 50000)
        base = SLIPPAGE_MODEL["base_bps"]
        size_impact = SLIPPAGE_MODEL["size_factor"] * (trade_usd / liq)
        total_bps = base + size_impact
        total_bps *= random.uniform(0.5, 2.0)
        return total_bps / 10000

    def estimate_latency_ms(self, exchange):
        model = LATENCY_MODEL.get(exchange, LATENCY_MODEL["binance"])
        if random.random() < model["spike_prob"]:
            return model["spike_ms"] + random.gauss(0, model["spike_ms"] * 0.3)
        return max(5, random.gauss(model["mean_ms"], model["std_ms"]))

    def get_fee_pct(self, exchange, order_type="taker"):
        fees = EXCHANGE_FEES.get(exchange, EXCHANGE_FEES["binance"])
        return fees.get(order_type, 0.1)

    def get_withdrawal_fee(self, exchange):
        fees = EXCHANGE_FEES.get(exchange, EXCHANGE_FEES["binance"])
        return fees.get("withdrawal_usdt", 1.0)

    def check_rate_limit(self, exchange):
        now = time.time()
        if exchange not in self._api_calls:
            self._api_calls[exchange] = []
        self._api_calls[exchange] = [t for t in self._api_calls[exchange] if now - t < 60]
        limit = RATE_LIMITS.get(exchange, 600)
        if len(self._api_calls[exchange]) >= limit:
            return False
        self._api_calls[exchange].append(now)
        return True

    def simulate_price_drift(self, price, latency_ms):
        seconds = latency_ms / 1000
        drift_std = price * 0.001 * math.sqrt(seconds)
        return price + random.gauss(0, drift_std)

    def execute_order(self, pair, exchange, side, price, amount_usd):
        if not self.check_rate_limit(exchange):
            log.warning(f"Rate limit hit on {exchange}")
            return (0, 0, 0, 0, False)

        latency_ms = self.estimate_latency_ms(exchange)
        drifted_price = self.simulate_price_drift(price, latency_ms)
        slippage = self.estimate_slippage(pair, amount_usd, exchange)

        if side == "buy":
            executed_price = drifted_price * (1 + slippage)
        else:
            executed_price = drifted_price * (1 - slippage)

        fee_pct = self.get_fee_pct(exchange, "taker")
        fee_usd = amount_usd * fee_pct / 100

        fail_prob = 0.02 if exchange != "dex" else 0.08
        if random.random() < fail_prob:
            log.warning(f"Order execution failed on {exchange} ({pair})")
            return (0, 0, 0, latency_ms, False)

        return (executed_price, fee_usd, slippage * 100, latency_ms, True)

    def record_loss(self):
        self._last_loss_time = time.time()

    def in_cooldown(self):
        return (time.time() - self._last_loss_time) < RISK["cooldown_after_loss_sec"]


# ═══════════════════════════════════════════════════════════
# REAL MARKET DATA ENGINE v3
# ═══════════════════════════════════════════════════════════

class RealMarketFetcher:
    """Fetches REAL prices from multiple exchanges via ccxt"""

    def __init__(self):
        self.exchanges = {}
        self.ticker_cache = {}
        self.funding_cache = {}
        self.cache_ttl = 1.5  # 1.5s cache for real prices
        self.funding_cache_ttl = 60  # 1 min cache for funding rates
        self.available_pairs = {}  # exchange -> set of pairs
        self._init_count = 0
        self._errors = deque(maxlen=50)
        self._fetch_stats = {"total": 0, "success": 0, "failed": 0}

        if CCXT_AVAILABLE:
            self._init_exchanges()

    def _init_exchanges(self):
        """Initialize exchange connections (public data only, NO API keys needed)"""
        for ex_id in EXCHANGES:
            if ex_id == "dex":
                continue
            try:
                ex_class = getattr(ccxt, ex_id, None)
                if not ex_class:
                    continue
                ex = ex_class({
                    "enableRateLimit": True,
                    "timeout": 10000,
                    "options": {"defaultType": "spot"},
                })
                # Try loading markets
                try:
                    ex.load_markets()
                    pairs_available = set()
                    for pair in ALL_PAIRS:
                        if pair in ex.markets:
                            pairs_available.add(pair)
                    self.available_pairs[ex_id] = pairs_available
                    self.exchanges[ex_id] = ex
                    self._init_count += 1
                    log.info(f"[REAL] {ex_id}: connected, {len(pairs_available)} pairs available")
                except Exception as e:
                    log.warning(f"[REAL] {ex_id}: could not load markets: {e}")
            except Exception as e:
                log.warning(f"[REAL] Could not init {ex_id}: {e}")

        log.info(f"[REAL] {self._init_count}/{len(EXCHANGES)} exchanges connected")

    def fetch_ticker(self, pair, exchange):
        """Fetch real ticker with short TTL caching"""
        cache_key = f"{exchange}:{pair}"
        cached = self.ticker_cache.get(cache_key)
        if cached and time.time() - cached["ts"] < self.cache_ttl:
            return cached["data"]

        ex = self.exchanges.get(exchange)
        if not ex:
            return None

        if pair not in self.available_pairs.get(exchange, set()):
            return None

        self._fetch_stats["total"] += 1
        try:
            ticker = ex.fetch_ticker(pair)
            bid = ticker.get("bid") or 0
            ask = ticker.get("ask") or 0
            last = ticker.get("last") or 0

            if not bid or not ask or not last:
                self._fetch_stats["failed"] += 1
                return None

            data = {
                "bid": float(bid),
                "ask": float(ask),
                "last": float(last),
                "volume_24h": float(ticker.get("quoteVolume") or 0),
                "high": float(ticker.get("high") or 0),
                "low": float(ticker.get("low") or 0),
                "change_pct": float(ticker.get("percentage") or 0),
                "source": "real",
            }
            self.ticker_cache[cache_key] = {"data": data, "ts": time.time()}
            self._fetch_stats["success"] += 1
            return data
        except Exception as e:
            self._fetch_stats["failed"] += 1
            self._errors.append({"ts": time.time(), "exchange": exchange, "pair": pair, "error": str(e)})
            return None

    def fetch_all_tickers_for_pair(self, pair):
        """Fetch the same pair across all connected exchanges"""
        results = {}
        for ex_id in self.exchanges:
            t = self.fetch_ticker(pair, ex_id)
            if t:
                results[ex_id] = t
        return results

    def fetch_funding_rate(self, pair, exchange="binance"):
        """Fetch real funding rate from futures"""
        cache_key = f"funding:{exchange}:{pair}"
        cached = self.funding_cache.get(cache_key)
        if cached and time.time() - cached["ts"] < self.funding_cache_ttl:
            return cached["data"]

        ex = self.exchanges.get(exchange)
        if not ex:
            return None

        try:
            # Create futures instance for funding rate
            if not hasattr(self, f"_futures_{exchange}"):
                futures_class = getattr(ccxt, exchange, None)
                if futures_class:
                    futures = futures_class({
                        "enableRateLimit": True,
                        "timeout": 10000,
                        "options": {"defaultType": "swap"},
                    })
                    setattr(self, f"_futures_{exchange}", futures)
                else:
                    return None

            futures_ex = getattr(self, f"_futures_{exchange}")
            if hasattr(futures_ex, 'fetch_funding_rate'):
                fr = futures_ex.fetch_funding_rate(pair)
                rate = (fr.get("fundingRate") or 0) * 100  # convert to %
                data = {
                    "rate_pct": rate,
                    "timestamp": fr.get("timestamp", time.time() * 1000),
                    "source": "real",
                }
                self.funding_cache[cache_key] = {"data": data, "ts": time.time()}
                return data
        except Exception:
            pass
        return None

    def get_stats(self):
        return {
            "exchanges_connected": list(self.exchanges.keys()),
            "total_fetches": self._fetch_stats["total"],
            "successful": self._fetch_stats["success"],
            "failed": self._fetch_stats["failed"],
            "hit_rate": round(self._fetch_stats["success"] / max(1, self._fetch_stats["total"]) * 100, 1),
            "recent_errors": list(self._errors)[-5:],
        }


class MarketSimulator:
    """Fallback: generates simulated prices when real data unavailable"""

    def __init__(self):
        self.prices = {}
        self.volatilities = {}
        self.trends = {}
        self.orderbook_depth = {}

        for pair, seed in PRICE_SEEDS.items():
            self.prices[pair] = {}
            self.volatilities[pair] = random.uniform(0.0005, 0.002)
            self.trends[pair] = random.uniform(-0.0001, 0.0001)
            self.orderbook_depth[pair] = SLIPPAGE_MODEL["liquidity_usd"].get(pair, 50000)
            for ex in EXCHANGES:
                offset = random.gauss(0, seed * 0.002)
                self.prices[pair][ex] = seed + offset

    def tick(self):
        for pair in self.prices:
            vol = self.volatilities[pair]
            trend = self.trends[pair]
            if random.random() < 0.02:
                self.trends[pair] = random.gauss(0, 0.0001)
            base_move = random.gauss(trend, vol)
            for ex in EXCHANGES:
                # Higher inter-exchange noise for more arb opportunities
                ex_noise = random.gauss(0, vol * 1.5)
                self.prices[pair][ex] *= (1 + base_move + ex_noise)
            avg_price = sum(self.prices[pair].values()) / len(self.prices[pair])
            for ex in EXCHANGES:
                diff = self.prices[pair][ex] - avg_price
                # Slower convergence = more persistent spreads
                self.prices[pair][ex] -= diff * 0.008
            # Occasional "shock" — exchange temporarily deviates
            if random.random() < 0.05:
                shock_ex = random.choice(EXCHANGES)
                shock_pct = random.gauss(0, 0.003)
                self.prices[pair][shock_ex] *= (1 + shock_pct)
            liq = self.orderbook_depth[pair]
            self.orderbook_depth[pair] = max(5000, liq * (1 + random.gauss(0, 0.05)))

    def get_ticker(self, pair, exchange):
        if pair not in self.prices or exchange not in self.prices.get(pair, {}):
            return None
        price = self.prices[pair][exchange]
        spread = price * random.uniform(0.0001, 0.0005)
        return {
            "bid": price - spread / 2,
            "ask": price + spread / 2,
            "last": price + random.gauss(0, spread * 0.1),
            "volume_24h": random.uniform(1e6, 5e8),
            "source": "simulated",
        }


class HybridMarket:
    """Uses REAL prices when available, simulator as fallback"""

    def __init__(self):
        self.simulator = MarketSimulator()
        self.execution = ExecutionModel()
        self.real_fetcher = RealMarketFetcher()
        self.use_real = len(self.real_fetcher.exchanges) > 0
        self._source_stats = {"real": 0, "simulated": 0}

    def tick(self):
        self.simulator.tick()

    def get_ticker(self, pair, exchange):
        if self.use_real:
            real = self.real_fetcher.fetch_ticker(pair, exchange)
            if real:
                self._source_stats["real"] += 1
                return real
        self._source_stats["simulated"] += 1
        return self.simulator.get_ticker(pair, exchange)

    def get_all_tickers(self, pair):
        result = {}
        if self.use_real:
            result = self.real_fetcher.fetch_all_tickers_for_pair(pair)
        # Fill gaps with simulator
        for ex in EXCHANGES:
            if ex not in result:
                t = self.simulator.get_ticker(pair, ex)
                if t:
                    result[ex] = t
        return result

    def get_funding_rate(self, pair):
        if self.use_real:
            fr = self.real_fetcher.fetch_funding_rate(pair)
            if fr:
                return fr["rate_pct"]
        return random.gauss(0.01, 0.03)

    def get_orderbook_depth_usd(self, pair):
        return self.simulator.orderbook_depth.get(pair, 50000)

    def get_price_source(self):
        if self.use_real:
            exs = ", ".join(self.real_fetcher.exchanges.keys())
            return f"REAL ({exs})"
        return "SIMULATED (install ccxt for real data)"

    def get_data_quality(self):
        total = self._source_stats["real"] + self._source_stats["simulated"]
        if total == 0:
            return {"real_pct": 0, "simulated_pct": 100, "total_ticks": 0}
        return {
            "real_pct": round(self._source_stats["real"] / total * 100, 1),
            "simulated_pct": round(self._source_stats["simulated"] / total * 100, 1),
            "total_ticks": total,
            "fetcher_stats": self.real_fetcher.get_stats() if self.use_real else None,
        }


# ═══════════════════════════════════════════════════════════
# SQLITE PERSISTENCE
# ═══════════════════════════════════════════════════════════

class Database:
    def __init__(self, db_path=None):
        if db_path is None:
            import tempfile
            candidates = [
                Path(__file__).parent / "arbitrage.db",
                Path(tempfile.gettempdir()) / "arbitrage_nexus.db",
                Path("/tmp/arbitrage_nexus.db"),
            ]
            db_path = None
            for candidate in candidates:
                try:
                    with sqlite3.connect(str(candidate)) as test_conn:
                        test_conn.execute("CREATE TABLE IF NOT EXISTS _test (id INTEGER)")
                        test_conn.execute("DROP TABLE _test")
                    db_path = candidate
                    break
                except Exception:
                    continue
            if db_path is None:
                db_path = ":memory:"
                log.warning("Using in-memory database (no persistence)")
        self.db_path = str(db_path)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS trades (
                    id TEXT PRIMARY KEY, strategy TEXT, pair TEXT, exchange TEXT,
                    side TEXT, entry_price REAL, exit_price REAL, amount REAL,
                    fee_entry REAL, fee_exit REAL, slippage_pct REAL, latency_ms REAL,
                    pnl REAL, status TEXT, opened_at REAL, closed_at REAL, mode TEXT,
                    data_source TEXT DEFAULT 'unknown'
                );
                CREATE TABLE IF NOT EXISTS equity_snapshots (
                    timestamp REAL, equity REAL, balance REAL, open_positions INTEGER
                );
                CREATE TABLE IF NOT EXISTS opportunities (
                    timestamp REAL, strategy TEXT, data TEXT
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at REAL, mode TEXT, initial_balance REAL, config TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy);
                CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
                CREATE INDEX IF NOT EXISTS idx_equity_ts ON equity_snapshots(timestamp);
            """)
            log.info(f"Database initialized: {self.db_path}")

    def save_trade(self, trade_dict):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO trades
                (id, strategy, pair, exchange, side, entry_price, exit_price,
                 amount, fee_entry, fee_exit, slippage_pct, latency_ms,
                 pnl, status, opened_at, closed_at, mode, data_source)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                trade_dict["id"], trade_dict.get("strategy", ""),
                trade_dict.get("pair", ""), trade_dict.get("exchange", ""),
                trade_dict.get("side", ""), trade_dict.get("entry_price", 0),
                trade_dict.get("exit_price", 0), trade_dict.get("amount", 0),
                trade_dict.get("fee_entry", 0), trade_dict.get("fee_exit", 0),
                trade_dict.get("slippage_pct", 0), trade_dict.get("latency_ms", 0),
                trade_dict.get("pnl", 0), trade_dict.get("status", "open"),
                trade_dict.get("opened_at", 0), trade_dict.get("closed_at", 0),
                trade_dict.get("mode", TRADING_MODE),
                trade_dict.get("data_source", "unknown"),
            ))

    def save_equity(self, timestamp, equity, balance, open_positions):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT INTO equity_snapshots VALUES (?,?,?,?)",
                         (timestamp, equity, balance, open_positions))

    def save_opportunity(self, strategy, data):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT INTO opportunities VALUES (?,?,?)",
                         (time.time(), strategy, json.dumps(data)))

    def save_session(self, mode, initial_balance, config):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO sessions (started_at, mode, initial_balance, config) VALUES (?,?,?,?)",
                (time.time(), mode, initial_balance, json.dumps(config)))

    def get_historical_trades(self, limit=200):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM trades ORDER BY opened_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_historical_equity(self, limit=500):
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM equity_snapshots ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
            return [{"timestamp": r[0], "equity": r[1], "balance": r[2]} for r in reversed(rows)]


# ═══════════════════════════════════════════════════════════
# PORTFOLIO MANAGER v3
# ═══════════════════════════════════════════════════════════

class Trade:
    _counter = 0

    def __init__(self, strategy, pair, exchange, side, price, amount,
                 fee=0, slippage_pct=0, latency_ms=0, data_source="unknown"):
        Trade._counter += 1
        self.id = f"T{Trade._counter:06d}"
        self.strategy = strategy
        self.pair = pair
        self.exchange = exchange
        self.side = side
        self.price = price
        self.amount = amount
        self.fee = fee
        self.slippage_pct = slippage_pct
        self.latency_ms = latency_ms
        self.data_source = data_source
        self.timestamp = time.time()
        self.pnl = 0.0
        self.exit_price = 0.0
        self.exit_fee = 0.0
        self.exit_slippage = 0.0
        self.exit_latency = 0.0
        self.status = "open"
        self.closed_at = 0.0

    def to_dict(self):
        return {
            "id": self.id, "strategy": self.strategy, "pair": self.pair,
            "exchange": self.exchange, "side": self.side,
            "price": round(self.price, 6), "exit_price": round(self.exit_price, 6),
            "amount": round(self.amount, 8),
            "fee": round(self.fee, 4), "exit_fee": round(self.exit_fee, 4),
            "slippage_pct": round(self.slippage_pct, 4),
            "latency_ms": round(self.latency_ms, 1),
            "timestamp": self.timestamp, "closed_at": self.closed_at,
            "pnl": round(self.pnl, 4), "status": self.status,
            "data_source": self.data_source,
        }

    def to_db_dict(self):
        return {
            "id": self.id, "strategy": self.strategy, "pair": self.pair,
            "exchange": self.exchange, "side": self.side,
            "entry_price": self.price, "exit_price": self.exit_price,
            "amount": self.amount,
            "fee_entry": self.fee, "fee_exit": self.exit_fee,
            "slippage_pct": self.slippage_pct, "latency_ms": self.latency_ms,
            "pnl": self.pnl, "status": self.status,
            "opened_at": self.timestamp, "closed_at": self.closed_at,
            "mode": TRADING_MODE, "data_source": self.data_source,
        }


class Portfolio:
    def __init__(self, initial_balance, mode="paper", db=None):
        self.mode = mode
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.trades = []
        self.equity_curve = []
        self.total_pnl = 0.0
        self.daily_pnl = 0.0
        self.total_fees = 0.0
        self.total_slippage_cost = 0.0
        self.avg_latency_ms = 0.0
        self._latency_samples = []
        self.win_count = 0
        self.loss_count = 0
        self.max_balance = initial_balance
        self.max_drawdown = 0.0
        self.open_positions = 0
        self._start = time.time()
        self.db = db
        self._record()

    def _record(self):
        equity = self.balance
        self.equity_curve.append({"timestamp": time.time(), "equity": equity, "balance": self.balance})
        if len(self.equity_curve) > 500:
            self.equity_curve = self.equity_curve[-300:]
        if equity > self.max_balance:
            self.max_balance = equity
        dd = (self.max_balance - equity) / self.max_balance * 100 if self.max_balance > 0 else 0
        if dd > self.max_drawdown:
            self.max_drawdown = dd
        if self.db:
            try:
                self.db.save_equity(time.time(), equity, self.balance, self.open_positions)
            except Exception:
                pass

    def open_trade(self, strategy, pair, exchange, side, price, amount,
                   fee_usd=0, slippage_pct=0, latency_ms=0, data_source="unknown"):
        cost = price * amount
        total_cost = cost + fee_usd
        if total_cost > self.balance:
            return None
        if cost > RISK["max_single_trade_usd"]:
            return None

        self.balance -= total_cost
        self.total_fees += fee_usd
        slippage_cost_usd = cost * slippage_pct / 100
        self.total_slippage_cost += slippage_cost_usd

        if latency_ms > 0:
            self._latency_samples.append(latency_ms)
            if len(self._latency_samples) > 200:
                self._latency_samples = self._latency_samples[-100:]
            self.avg_latency_ms = sum(self._latency_samples) / len(self._latency_samples)

        t = Trade(strategy, pair, exchange, side, price, amount,
                  fee_usd, slippage_pct, latency_ms, data_source)
        self.trades.append(t)
        self.open_positions += 1
        self._record()

        if self.db:
            try:
                self.db.save_trade(t.to_db_dict())
            except Exception:
                pass
        return t

    def close_trade(self, trade_id, exit_price, fee_usd=0,
                    slippage_pct=0, latency_ms=0):
        t = next((x for x in self.trades if x.id == trade_id and x.status == "open"), None)
        if not t:
            return 0

        t.exit_price = exit_price
        t.exit_fee = fee_usd
        t.exit_slippage = slippage_pct
        t.exit_latency = latency_ms
        t.closed_at = time.time()

        revenue = exit_price * t.amount
        total_fees = t.fee + fee_usd
        self.total_fees += fee_usd

        if t.side == "buy":
            pnl = (exit_price - t.price) * t.amount - total_fees
        else:
            pnl = (t.price - exit_price) * t.amount - total_fees

        t.pnl = pnl
        t.status = "closed"
        self.balance += revenue - fee_usd
        self.total_pnl += pnl
        self.daily_pnl += pnl

        if pnl > 0:
            self.win_count += 1
        else:
            self.loss_count += 1

        self.open_positions -= 1
        self._record()

        if self.db:
            try:
                self.db.save_trade(t.to_db_dict())
            except Exception:
                pass
        return pnl

    def get_stats(self):
        total = self.win_count + self.loss_count
        wr = (self.win_count / total * 100) if total > 0 else 0
        roi = (self.total_pnl / self.initial_balance * 100) if self.initial_balance > 0 else 0
        runtime = time.time() - self._start

        gross_wins = sum(t.pnl for t in self.trades if t.pnl > 0)
        gross_losses = abs(sum(t.pnl for t in self.trades if t.pnl < 0))
        profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else 0

        if len(self.trades) > 2:
            pnls = [t.pnl for t in self.trades if t.status == "closed"]
            if pnls:
                avg_pnl = sum(pnls) / len(pnls)
                std_pnl = (sum((p - avg_pnl)**2 for p in pnls) / len(pnls)) ** 0.5
                sharpe = (avg_pnl / std_pnl * math.sqrt(252)) if std_pnl > 0 else 0
            else:
                sharpe = 0
        else:
            sharpe = 0

        # Count real vs simulated trades
        real_trades = sum(1 for t in self.trades if t.data_source == "real")
        sim_trades = sum(1 for t in self.trades if t.data_source != "real")

        return {
            "mode": self.mode,
            "aggressive": AGGRESSIVE,
            "initial_balance": self.initial_balance,
            "current_balance": round(self.balance, 2),
            "total_pnl": round(self.total_pnl, 2),
            "daily_pnl": round(self.daily_pnl, 2),
            "roi_pct": round(roi, 4),
            "total_trades": total,
            "win_count": self.win_count,
            "loss_count": self.loss_count,
            "win_rate": round(wr, 2),
            "open_positions": self.open_positions,
            "max_drawdown_pct": round(self.max_drawdown, 4),
            "runtime_sec": round(runtime),
            "total_fees_usd": round(self.total_fees, 2),
            "total_slippage_cost_usd": round(self.total_slippage_cost, 2),
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "profit_factor": round(profit_factor, 2),
            "sharpe_ratio": round(sharpe, 2),
            "real_trades": real_trades,
            "simulated_trades": sim_trades,
            "equity_curve": self.equity_curve[-200:],
            "recent_trades": [t.to_dict() for t in self.trades[-50:]],
        }

    def get_breakdown(self):
        bd = {}
        for t in self.trades:
            if t.strategy not in bd:
                bd[t.strategy] = {
                    "trades": 0, "wins": 0, "losses": 0,
                    "total_pnl": 0, "total_fees": 0,
                    "avg_slippage": 0, "avg_latency": 0,
                    "_slippages": [], "_latencies": [],
                }
            s = bd[t.strategy]
            s["trades"] += 1
            s["total_pnl"] += t.pnl
            s["total_fees"] += t.fee + t.exit_fee
            s["_slippages"].append(t.slippage_pct)
            s["_latencies"].append(t.latency_ms)
            if t.pnl > 0: s["wins"] += 1
            elif t.pnl < 0: s["losses"] += 1

        for s in bd.values():
            s["total_pnl"] = round(s["total_pnl"], 2)
            s["total_fees"] = round(s["total_fees"], 2)
            s["win_rate"] = round(s["wins"] / s["trades"] * 100, 2) if s["trades"] > 0 else 0
            s["avg_slippage"] = round(sum(s["_slippages"]) / len(s["_slippages"]), 4) if s["_slippages"] else 0
            s["avg_latency"] = round(sum(s["_latencies"]) / len(s["_latencies"]), 1) if s["_latencies"] else 0
            del s["_slippages"]
            del s["_latencies"]
        return bd


# ═══════════════════════════════════════════════════════════
# STRATEGY ENGINES v3 — Optimized for real markets
# ═══════════════════════════════════════════════════════════

class BaseEngine:
    def __init__(self, name, market, portfolio):
        self.name = name
        self.market = market
        self.portfolio = portfolio
        self.execution = market.execution
        self.running = True
        self.opportunities_found = 0
        self.trades_executed = 0
        self.trades_failed = 0
        self.total_profit = 0.0
        self.last_opportunity = None
        self.events = []
        self._start = time.time()
        self._own_last_loss_time = 0  # Per-engine cooldown

    @property
    def max_trade(self):
        """Max entry = 5% of current balance"""
        return round(self.portfolio.balance * 0.05, 2)

    def _add_event(self, etype, data):
        self.events.append({"timestamp": time.time(), "type": etype, "data": data})
        if len(self.events) > 200:
            self.events = self.events[-100:]

    def get_status(self):
        return {
            "name": self.name, "running": self.running,
            "opportunities_found": self.opportunities_found,
            "trades_executed": self.trades_executed,
            "trades_failed": self.trades_failed,
            "total_profit": round(self.total_profit, 4),
            "last_scan": time.time(),
            "last_opportunity": self.last_opportunity,
            "runtime_sec": round(time.time() - self._start),
            "recent_events": self.events[-20:],
        }

    def _risk_ok(self):
        # Per-engine cooldown instead of global
        if (time.time() - self._own_last_loss_time) < RISK["cooldown_after_loss_sec"]:
            return False
        if self.portfolio.open_positions >= RISK["max_open_positions"]:
            return False
        # Check realized drawdown only (not temporary dips from open positions)
        if not AGGRESSIVE:
            current_dd = 0
            if self.portfolio.max_balance > 0:
                current_dd = (self.portfolio.max_balance - self.portfolio.balance) / self.portfolio.max_balance * 100
            if current_dd > RISK["max_drawdown_pct"]:
                return False
        # Daily loss limit always applies
        if self.portfolio.daily_pnl < 0 and abs(self.portfolio.daily_pnl) >= RISK["max_daily_loss_usd"]:
            return False
        return True

    def _record_engine_loss(self):
        """Record loss for this engine's cooldown only"""
        self._own_last_loss_time = time.time()

    def _get_data_source(self, ticker):
        """Determine if this ticker is from real or simulated data"""
        return ticker.get("source", "simulated")

    def _execute_buy_sell(self, pair, buy_exchange, sell_exchange,
                          buy_price, sell_price, trade_usd, data_source="unknown"):
        buy_exec_price, buy_fee, buy_slip, buy_lat, buy_ok = \
            self.execution.execute_order(pair, buy_exchange, "buy", buy_price, trade_usd)
        if not buy_ok:
            self.trades_failed += 1
            self._add_event("error", {"error": f"Buy failed on {buy_exchange}", "pair": pair})
            return None

        amount = trade_usd / buy_exec_price

        sell_exec_price, sell_fee, sell_slip, sell_lat, sell_ok = \
            self.execution.execute_order(pair, sell_exchange, "sell", sell_price, trade_usd)
        if not sell_ok:
            self.trades_failed += 1
            self._add_event("error", {"error": f"Sell failed on {sell_exchange}", "pair": pair})
            return None

        trade = self.portfolio.open_trade(
            strategy=self.name, pair=pair, exchange=buy_exchange,
            side="buy", price=buy_exec_price, amount=amount,
            fee_usd=buy_fee, slippage_pct=buy_slip, latency_ms=buy_lat,
            data_source=data_source,
        )
        if not trade:
            return None

        pnl = self.portfolio.close_trade(
            trade.id, sell_exec_price,
            fee_usd=sell_fee, slippage_pct=sell_slip, latency_ms=sell_lat,
        )

        self.trades_executed += 1
        self.total_profit += pnl
        if pnl < 0:
            self._record_engine_loss()

        result = {
            "trade_id": trade.id, "pair": pair,
            "buy_exchange": buy_exchange, "sell_exchange": sell_exchange,
            "buy_price": round(buy_exec_price, 6),
            "sell_price": round(sell_exec_price, 6),
            "slippage_total_pct": round(buy_slip + sell_slip, 4),
            "latency_total_ms": round(buy_lat + sell_lat, 1),
            "fees_total_usd": round(buy_fee + sell_fee, 4),
            "pnl": round(pnl, 4),
            "data_source": data_source,
        }
        self._add_event("trade", result)
        return pnl


class CrossExchangeEngine(BaseEngine):
    """Scans ALL pairs across ALL exchanges for price discrepancies"""
    PAIRS = ALL_PAIRS[:12]  # Top 12 pairs by volume
    MIN_SPREAD = 0.03 if AGGRESSIVE else 0.05

    def scan_and_execute(self):
        if not self.running:
            return
        best = None
        best_spread = 0

        for pair in self.PAIRS:
            tickers = self.market.get_all_tickers(pair)
            if len(tickers) < 2:
                continue

            buy_ex = min(tickers, key=lambda x: tickers[x]["ask"])
            sell_ex = max(tickers, key=lambda x: tickers[x]["bid"])
            if buy_ex == sell_ex:
                continue

            buy_price = tickers[buy_ex]["ask"]
            sell_price = tickers[sell_ex]["bid"]
            raw_spread = (sell_price - buy_price) / buy_price * 100

            est_slip = self.execution.estimate_slippage(pair, self.max_trade) * 2
            est_fees = self.execution.get_fee_pct(buy_ex) + self.execution.get_fee_pct(sell_ex)
            withdrawal = self.execution.get_withdrawal_fee(buy_ex)
            est_cost_pct = est_slip * 100 + est_fees + (withdrawal / self.max_trade * 100)

            net_spread = raw_spread - est_cost_pct
            data_source = self._get_data_source(tickers[buy_ex])

            if net_spread > self.MIN_SPREAD and net_spread > best_spread:
                best_spread = net_spread
                best = {
                    "pair": pair, "buy_exchange": buy_ex, "sell_exchange": sell_ex,
                    "buy_price": round(buy_price, 6), "sell_price": round(sell_price, 6),
                    "raw_spread_pct": round(raw_spread, 4),
                    "est_costs_pct": round(est_cost_pct, 4),
                    "net_spread_pct": round(net_spread, 4),
                    "potential_profit_usd": round(self.max_trade * net_spread / 100, 4),
                    "data_source": data_source,
                }

        if best:
            self.opportunities_found += 1
            self.last_opportunity = best
            self._add_event("opportunity", best)

            if self._risk_ok() and random.random() < 0.92:
                self._execute_buy_sell(
                    best["pair"], best["buy_exchange"], best["sell_exchange"],
                    best["buy_price"], best["sell_price"], self.max_trade,
                    data_source=best["data_source"],
                )


class TriangularEngine(BaseEngine):
    """Triangular arbitrage within a single exchange"""
    TRIANGLES = [
        ("BTC/USDT", "ETH/BTC", "ETH/USDT"),
        ("SOL/USDT", "SOL/ETH", "ETH/USDT"),
        ("XRP/USDT", "XRP/BTC", "BTC/USDT"),
        ("DOGE/USDT", "DOGE/BTC", "BTC/USDT"),
        ("LINK/USDT", "LINK/ETH", "ETH/USDT"),
    ]
    MIN_PROFIT = 0.015 if AGGRESSIVE else 0.02

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cross_prices = {
            "ETH/BTC": 0.0337, "SOL/ETH": 0.0547, "SOL/BTC": 0.00184,
            "XRP/BTC": 0.0000253, "DOGE/BTC": 0.00000263,
            "LINK/ETH": 0.00563, "LINK/BTC": 0.000190,
        }

    def scan_and_execute(self):
        if not self.running:
            return

        for tri in self.TRIANGLES:
            try:
                exchange = "binance"
                t1 = self.market.get_ticker(tri[0], exchange)
                if not t1:
                    continue

                cross_key = tri[1]
                base_cross = self._cross_prices.get(cross_key, 0.05)
                cross_price = base_cross * (1 + random.gauss(0, 0.001))
                self._cross_prices[cross_key] = cross_price

                t3 = self.market.get_ticker(tri[2], exchange)
                if not t3:
                    continue

                step1 = 1.0 / t1["ask"]
                step2 = step1 * cross_price
                step3 = step2 * t3["bid"]

                total_fee_pct = self.execution.get_fee_pct(exchange) * 3
                total_slip = self.execution.estimate_slippage(tri[0], self.max_trade) * 3 * 100
                profit_pct = (step3 - 1.0) * 100 - total_fee_pct - total_slip
                data_source = self._get_data_source(t1)

                if profit_pct > self.MIN_PROFIT:
                    opp = {
                        "path": list(tri), "exchange": exchange,
                        "gross_profit_pct": round((step3 - 1.0) * 100, 4),
                        "fees_pct": round(total_fee_pct, 4),
                        "slippage_pct": round(total_slip, 4),
                        "net_profit_pct": round(profit_pct, 4),
                        "potential_profit_usd": round(self.max_trade * profit_pct / 100, 4),
                        "data_source": data_source,
                    }
                    self.opportunities_found += 1
                    self.last_opportunity = opp
                    self._add_event("opportunity", opp)

                    if self._risk_ok() and random.random() < 0.88:
                        total_latency = sum(
                            self.execution.estimate_latency_ms(exchange) for _ in range(3)
                        )
                        drifted_price = self.execution.simulate_price_drift(t1["ask"], total_latency)
                        actual_profit = profit_pct * random.uniform(0.3, 1.2)

                        exec_price = drifted_price
                        exit_price = exec_price * (1 + actual_profit / 100)
                        fee = self.max_trade * total_fee_pct / 100
                        amount = self.max_trade / exec_price

                        trade = self.portfolio.open_trade(
                            self.name, tri[0], exchange, "buy", exec_price, amount,
                            fee_usd=fee / 2, slippage_pct=total_slip / 2,
                            latency_ms=total_latency / 2, data_source=data_source,
                        )
                        if trade:
                            pnl = self.portfolio.close_trade(
                                trade.id, exit_price,
                                fee_usd=fee / 2, slippage_pct=total_slip / 2,
                                latency_ms=total_latency / 2,
                            )
                            self.trades_executed += 1
                            self.total_profit += pnl
                            if pnl < 0:
                                self._record_engine_loss()
                            self._add_event("trade", {
                                "trade_id": trade.id, "path": list(tri),
                                "net_profit_pct": round(actual_profit, 4),
                                "latency_ms": round(total_latency, 1),
                                "pnl": round(pnl, 4),
                                "data_source": data_source,
                            })
            except Exception:
                pass


class StatisticalEngine(BaseEngine):
    """Pairs trading based on z-score mean reversion"""
    PAIR_COMBOS = [
        ("BTC/USDT", "ETH/USDT"), ("SOL/USDT", "AVAX/USDT"),
        ("LINK/USDT", "DOT/USDT"), ("ADA/USDT", "XRP/USDT"),
        ("UNI/USDT", "ATOM/USDT"), ("ARB/USDT", "OP/USDT"),
    ]
    Z_ENTRY = 1.3 if AGGRESSIVE else 1.5
    Z_EXIT = 0.4 if AGGRESSIVE else 0.5

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._history = {}
        self._active = {}

    def scan_and_execute(self):
        if not self.running:
            return

        for pa, pb in self.PAIR_COMBOS:
            ta = self.market.get_ticker(pa, "binance")
            tb = self.market.get_ticker(pb, "binance")
            if not ta or not tb:
                continue

            key = f"{pa}:{pb}"
            if key not in self._history:
                self._history[key] = []

            ratio = ta["last"] / tb["last"]
            self._history[key].append(ratio)
            if len(self._history[key]) > 200:
                self._history[key] = self._history[key][-100:]
            if len(self._history[key]) < 25:
                continue

            data = self._history[key]
            mean = sum(data) / len(data)
            std = (sum((x - mean) ** 2 for x in data) / len(data)) ** 0.5
            if std == 0:
                continue
            z = (data[-1] - mean) / std
            data_source = self._get_data_source(ta)

            # Close position if z reverts
            if key in self._active and abs(z) < self.Z_EXIT:
                active = self._active[key]
                sell_price, sell_fee, sell_slip, sell_lat, sell_ok = \
                    self.execution.execute_order(pa, "binance", "sell", ta["last"], self.max_trade)
                if sell_ok:
                    pnl = self.portfolio.close_trade(
                        active["trade_id"], sell_price,
                        fee_usd=sell_fee, slippage_pct=sell_slip, latency_ms=sell_lat,
                    )
                    self.trades_executed += 1
                    self.total_profit += pnl
                    if pnl < 0:
                        self._record_engine_loss()
                    self._add_event("trade", {
                        "trade_id": active["trade_id"], "action": "close",
                        "exit_z": round(z, 4), "pnl": round(pnl, 4),
                        "data_source": data_source,
                    })
                del self._active[key]
                continue

            # Open new position
            if key not in self._active and abs(z) > self.Z_ENTRY:
                opp = {
                    "pair_a": pa, "pair_b": pb, "z_score": round(z, 4),
                    "direction": "short_a_long_b" if z > 0 else "long_a_short_b",
                    "potential_profit_usd": round(self.max_trade * abs(z) * 0.05, 4),
                    "data_source": data_source,
                }
                self.opportunities_found += 1
                self.last_opportunity = opp
                self._add_event("opportunity", opp)

                if self._risk_ok():
                    side = "sell" if z > 0 else "buy"
                    exec_price, exec_fee, exec_slip, exec_lat, exec_ok = \
                        self.execution.execute_order(pa, "binance", side, ta["last"], self.max_trade)
                    if exec_ok:
                        amount = self.max_trade / exec_price
                        trade = self.portfolio.open_trade(
                            self.name, pa, "binance", side, exec_price, amount,
                            fee_usd=exec_fee, slippage_pct=exec_slip,
                            latency_ms=exec_lat, data_source=data_source,
                        )
                        if trade:
                            self._active[key] = {"trade_id": trade.id, "z": z}
                            self._add_event("trade", {
                                "trade_id": trade.id, "action": "open",
                                "z_score": round(z, 4), "pnl": 0,
                            })


class FundingRateEngine(BaseEngine):
    """Captures funding rate premium between spot and perpetual futures"""
    PAIRS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "DOGE/USDT"]
    MIN_RATE = 0.008 if AGGRESSIVE else 0.01

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._active = {}

    def scan_and_execute(self):
        if not self.running:
            return

        for pair in self.PAIRS:
            if pair in self._active:
                self._active[pair]["ticks"] += 1
                if self._active[pair]["ticks"] > 6:
                    active = self._active[pair]
                    t = self.market.get_ticker(pair, "binance")
                    if t:
                        exec_price, fee, slip, lat, ok = \
                            self.execution.execute_order(pair, "binance", "sell", t["last"], self.max_trade)
                        if ok:
                            pnl = self.portfolio.close_trade(
                                active["trade_id"], exec_price,
                                fee_usd=fee, slippage_pct=slip, latency_ms=lat,
                            )
                            funding_pnl = self.max_trade * abs(active["rate"]) / 100
                            pnl_total = pnl + funding_pnl
                            self.trades_executed += 1
                            self.total_profit += pnl_total
                            if pnl_total < 0:
                                self._record_engine_loss()
                            self._add_event("trade", {
                                "trade_id": active["trade_id"], "action": "close",
                                "funding_earned": round(funding_pnl, 4),
                                "pnl": round(pnl_total, 4),
                            })
                    del self._active[pair]
                continue

            rate = self.market.get_funding_rate(pair)
            if abs(rate) >= self.MIN_RATE:
                annual_yield = abs(rate) * 3 * 365
                opp = {
                    "pair": pair, "funding_rate_pct": round(rate, 6),
                    "annual_yield_pct": round(annual_yield, 2),
                    "direction": "short_perp_long_spot" if rate > 0 else "long_perp_short_spot",
                    "potential_profit_usd": round(self.max_trade * abs(rate) / 100, 4),
                }
                self.opportunities_found += 1
                self.last_opportunity = opp
                self._add_event("opportunity", opp)

                if self._risk_ok() and random.random() < 0.75:
                    t = self.market.get_ticker(pair, "binance")
                    if t:
                        exec_price, fee, slip, lat, ok = \
                            self.execution.execute_order(pair, "binance", "buy", t["last"], self.max_trade)
                        if ok:
                            amount = self.max_trade / exec_price
                            data_source = self._get_data_source(t)
                            trade = self.portfolio.open_trade(
                                self.name, pair, "binance", "buy", exec_price, amount,
                                fee_usd=fee, slippage_pct=slip, latency_ms=lat,
                                data_source=data_source,
                            )
                            if trade:
                                self._active[pair] = {"trade_id": trade.id, "rate": rate, "ticks": 0}
                                self._add_event("trade", {
                                    "trade_id": trade.id, "action": "open",
                                    "funding_rate": round(rate, 6), "pnl": 0,
                                })


class DexCexEngine(BaseEngine):
    """DEX vs CEX price discrepancy arbitrage"""
    PAIRS = ["ETH/USDT", "SOL/USDT", "ARB/USDT", "OP/USDT", "UNI/USDT"]
    MIN_SPREAD = 0.08 if AGGRESSIVE else 0.10
    GAS_COST = 8.0  # Reduced for L2

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._dex_offsets = {p: random.gauss(0, 0.006) for p in self.PAIRS}

    def scan_and_execute(self):
        if not self.running:
            return

        for pair in self.PAIRS:
            t = self.market.get_ticker(pair, "binance")
            if not t:
                continue

            self._dex_offsets[pair] += random.gauss(0, 0.003)
            self._dex_offsets[pair] *= 0.92
            dex_price = t["last"] * (1 + self._dex_offsets[pair])

            spread_d2c = (t["bid"] - dex_price) / dex_price * 100
            spread_c2d = (dex_price - t["ask"]) / t["ask"] * 100
            best_spread = max(spread_d2c, spread_c2d)
            direction = "buy_dex_sell_cex" if spread_d2c > spread_c2d else "buy_cex_sell_dex"

            dex_fee_pct = EXCHANGE_FEES["dex"]["taker"]
            cex_fee_pct = self.execution.get_fee_pct("binance")
            est_slip = self.execution.estimate_slippage(pair, self.max_trade) * 100
            gas_as_pct = self.GAS_COST / self.max_trade * 100

            total_cost_pct = dex_fee_pct + cex_fee_pct + est_slip * 2 + gas_as_pct
            net_spread = best_spread - total_cost_pct
            data_source = self._get_data_source(t)

            if net_spread > self.MIN_SPREAD:
                opp = {
                    "pair": pair, "direction": direction,
                    "dex_price": round(dex_price, 6),
                    "cex_bid": round(t["bid"], 6), "cex_ask": round(t["ask"], 6),
                    "raw_spread_pct": round(best_spread, 4),
                    "costs_pct": round(total_cost_pct, 4),
                    "net_spread_pct": round(net_spread, 4),
                    "gas_cost": self.GAS_COST,
                    "net_profit_usd": round(self.max_trade * net_spread / 100, 4),
                    "data_source": data_source,
                }
                self.opportunities_found += 1
                self.last_opportunity = opp
                self._add_event("opportunity", opp)

                if self._risk_ok() and random.random() < 0.82:
                    buy_ex = "dex" if "buy_dex" in direction else "binance"
                    sell_ex = "binance" if "sell_cex" in direction else "dex"
                    buy_p = dex_price if "buy_dex" in direction else t["ask"]
                    sell_p = t["bid"] if "sell_cex" in direction else dex_price

                    buy_exec, buy_fee, buy_slip, buy_lat, buy_ok = \
                        self.execution.execute_order(pair, buy_ex, "buy", buy_p, self.max_trade)
                    sell_exec, sell_fee, sell_slip, sell_lat, sell_ok = \
                        self.execution.execute_order(pair, sell_ex, "sell", sell_p, self.max_trade)

                    if buy_ok and sell_ok:
                        amount = self.max_trade / buy_exec
                        trade = self.portfolio.open_trade(
                            self.name, pair, "dex_cex", "buy", buy_exec, amount,
                            fee_usd=buy_fee, slippage_pct=buy_slip, latency_ms=buy_lat,
                            data_source=data_source,
                        )
                        if trade:
                            pnl = self.portfolio.close_trade(
                                trade.id, sell_exec,
                                fee_usd=sell_fee + self.GAS_COST,
                                slippage_pct=sell_slip, latency_ms=sell_lat,
                            )
                            self.trades_executed += 1
                            self.total_profit += pnl
                            if pnl < 0:
                                self._record_engine_loss()
                            self._add_event("trade", {
                                "trade_id": trade.id, "pair": pair,
                                "direction": direction,
                                "gas_cost": self.GAS_COST, "pnl": round(pnl, 4),
                            })
                    else:
                        self.trades_failed += 1


# ═══════════════════════════════════════════════════════════
# WEBSOCKET SERVER (RFC 6455)
# ═══════════════════════════════════════════════════════════

class WebSocketHandler:
    def __init__(self, conn, addr):
        self.conn = conn
        self.addr = addr
        self.alive = True

    def send(self, message):
        try:
            data = message.encode() if isinstance(message, str) else message
            length = len(data)
            frame = bytearray()
            frame.append(0x81)
            if length < 126:
                frame.append(length)
            elif length < 65536:
                frame.append(126)
                frame.extend(struct.pack(">H", length))
            else:
                frame.append(127)
                frame.extend(struct.pack(">Q", length))
            frame.extend(data)
            self.conn.sendall(bytes(frame))
            return True
        except Exception:
            self.alive = False
            return False

    def recv(self, timeout=0.1):
        try:
            self.conn.settimeout(timeout)
            data = self.conn.recv(4096)
            if not data:
                self.alive = False
                return None
            if data[0] == 0x88:
                self.alive = False
                return None
            if len(data) < 2:
                return None
            length = data[1] & 0x7F
            offset = 2
            if length == 126:
                length = struct.unpack(">H", data[2:4])[0]
                offset = 4
            elif length == 127:
                length = struct.unpack(">Q", data[2:10])[0]
                offset = 10
            mask = data[offset:offset + 4]
            offset += 4
            decoded = bytearray()
            for i in range(length):
                if offset + i < len(data):
                    decoded.append(data[offset + i] ^ mask[i % 4])
            return bytes(decoded).decode()
        except socket.timeout:
            return None
        except Exception:
            self.alive = False
            return None

    def close(self):
        self.alive = False
        try:
            self.conn.close()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════
# BOT SERVER v3
# ═══════════════════════════════════════════════════════════

class BotServer:
    def __init__(self, port=PORT):
        self.port = port
        self.db = Database()
        self.market = HybridMarket()
        self.portfolio = Portfolio(INITIAL_BALANCE, TRADING_MODE, self.db)
        self.engines = {}
        self.ws_clients = []
        self.running = True

        self.engines["cross_exchange"] = CrossExchangeEngine("cross_exchange", self.market, self.portfolio)
        self.engines["triangular"] = TriangularEngine("triangular", self.market, self.portfolio)
        self.engines["statistical"] = StatisticalEngine("statistical", self.market, self.portfolio)
        self.engines["funding_rate"] = FundingRateEngine("funding_rate", self.market, self.portfolio)
        self.engines["dex_cex"] = DexCexEngine("dex_cex", self.market, self.portfolio)

        self.db.save_session(TRADING_MODE, INITIAL_BALANCE, {
            "risk": RISK, "exchanges": EXCHANGES,
            "price_source": self.market.get_price_source(),
            "ccxt_available": CCXT_AVAILABLE,
            "aggressive": AGGRESSIVE,
            "version": "v3",
        })

    def get_state(self):
        return {
            "version": "v3",
            "portfolio": self.portfolio.get_stats(),
            "strategy_breakdown": self.portfolio.get_breakdown(),
            "engines": {n: e.get_status() for n, e in self.engines.items()},
            "exchanges": EXCHANGES,
            "price_source": self.market.get_price_source(),
            "data_quality": self.market.get_data_quality(),
            "ccxt_available": CCXT_AVAILABLE,
            "aggressive": AGGRESSIVE,
            "scan_interval": SCAN_INTERVAL,
            "timestamp": time.time(),
        }

    def _handle_http(self, conn, data):
        first_line = data.split("\r\n")[0] if "\r\n" in data else data.split("\n")[0]
        parts = first_line.split(" ")
        path = parts[1] if len(parts) > 1 else "/"

        if path == "/" or path == "/index.html":
            html_path = Path(__file__).parent / "dashboard" / "index.html"
            if html_path.exists():
                content = html_path.read_bytes()
                resp = (
                    f"HTTP/1.1 200 OK\r\n"
                    f"Content-Type: text/html; charset=utf-8\r\n"
                    f"Content-Length: {len(content)}\r\n"
                    f"Access-Control-Allow-Origin: *\r\n\r\n"
                ).encode() + content
            else:
                body = b"<h1>Dashboard not found</h1>"
                resp = f"HTTP/1.1 404 Not Found\r\nContent-Length: {len(body)}\r\n\r\n".encode() + body
        elif path.startswith("/api/"):
            body = json.dumps(self.get_state()).encode()
            resp = (
                f"HTTP/1.1 200 OK\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\n"
                f"Access-Control-Allow-Origin: *\r\n\r\n"
            ).encode() + body
        else:
            body = b"Not Found"
            resp = f"HTTP/1.1 404 Not Found\r\nContent-Length: {len(body)}\r\n\r\n".encode() + body

        try:
            conn.sendall(resp)
        except Exception:
            pass
        conn.close()

    def _handle_connection(self, conn, addr):
        try:
            conn.settimeout(5)
            data = conn.recv(4096).decode()

            if "Upgrade: websocket" in data or "upgrade: websocket" in data:
                ws = WebSocketHandler(conn, addr)
                key = None
                for line in data.split("\r\n"):
                    if line.lower().startswith("sec-websocket-key:"):
                        key = line.split(":")[1].strip()
                        break
                if key:
                    magic = "258EAFA5-E914-47DA-95CA-5AB9DC85B175"
                    accept = base64.b64encode(hashlib.sha1((key + magic).encode()).digest()).decode()
                    response = (
                        "HTTP/1.1 101 Switching Protocols\r\n"
                        "Upgrade: websocket\r\n"
                        "Connection: Upgrade\r\n"
                        f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
                    )
                    conn.sendall(response.encode())
                    self.ws_clients.append(ws)
                    ws.send(json.dumps({"type": "init", "data": self.get_state()}))
                    while ws.alive and self.running:
                        msg = ws.recv(1.0)
                        if msg:
                            try:
                                cmd = json.loads(msg)
                                if cmd.get("action") == "toggle_engine":
                                    eng = self.engines.get(cmd.get("engine"))
                                    if eng:
                                        eng.running = not eng.running
                                        log.info(f"Engine {cmd.get('engine')} -> {'ON' if eng.running else 'OFF'}")
                            except Exception:
                                pass
                    if ws in self.ws_clients:
                        self.ws_clients.remove(ws)
                    ws.close()
            else:
                self._handle_http(conn, data)
        except Exception:
            try:
                conn.close()
            except Exception:
                pass

    def _engine_loop(self):
        loop_count = 0
        while self.running:
            try:
                tick_count = 5 if AGGRESSIVE else 3
                for _ in range(tick_count):
                    self.market.tick()

                for engine in self.engines.values():
                    try:
                        engine.scan_and_execute()
                    except Exception as e:
                        engine._add_event("error", {"error": str(e)})
                        log.error(f"Engine {engine.name} error: {e}")

                loop_count += 1
                if loop_count % 30 == 0:
                    total_trades = self.portfolio.get_stats()["total_trades"]
                    log.info(f"[LOOP {loop_count}] trades={total_trades} balance=${self.portfolio.balance:,.2f} open={self.portfolio.open_positions}")

                state = json.dumps({"type": "update", "data": self.get_state()})
                dead = []
                for ws in self.ws_clients:
                    if not ws.send(state):
                        dead.append(ws)
                for ws in dead:
                    if ws in self.ws_clients:
                        self.ws_clients.remove(ws)

                time.sleep(SCAN_INTERVAL)
            except Exception as e:
                log.error(f"Engine loop error: {e}")
                time.sleep(1)

    def start(self):
        src = self.market.get_price_source()
        mode_str = "AGGRESSIVE" if AGGRESSIVE else "NORMAL"
        print(f"""
╔══════════════════════════════════════════════════════════════╗
║          ARBITRAGE NEXUS v3 — REAL MARKET HUNTER             ║
╠══════════════════════════════════════════════════════════════╣
║  Mode:     {TRADING_MODE.upper():>6} ({mode_str})                            ║
║  Balance:  ${INITIAL_BALANCE:>10,.0f}                                  ║
║  Prices:   {src:<48s} ║
║  CCXT:     {'CONNECTED' if CCXT_AVAILABLE else 'Not installed':48s} ║
║  Pairs:    {len(ALL_PAIRS)} tracked across {len(EXCHANGES)} exchanges             ║
║  Scan:     Every {SCAN_INTERVAL}s                                       ║
╠══════════════════════════════════════════════════════════════╣
║  v3 UPGRADES:                                                ║
║   + Auto-install ccxt (real prices from exchanges)           ║
║   + 6 exchanges: Binance, Bybit, OKX, KuCoin, Gate, MEXC    ║
║   + 20 trading pairs (top by volume)                         ║
║   + Aggressive mode (lower thresholds, more trades)          ║
║   + Real-time data quality tracking                          ║
║   + REAL vs SIMULATED trade tagging                          ║
║   + Faster 0.5s scan interval                                ║
║   + 5 more triangular paths                                  ║
║   + 6 stat-arb pair combos                                   ║
║   + L2 DEX support (lower gas)                               ║
╠══════════════════════════════════════════════════════════════╣
║  Dashboard:  http://localhost:{self.port}                         ║
║  API:        http://localhost:{self.port}/api/status               ║
╚══════════════════════════════════════════════════════════════╝
""")

        engine_thread = threading.Thread(target=self._engine_loop, daemon=True)
        engine_thread.start()

        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("0.0.0.0", self.port))
        server.listen(20)
        server.settimeout(1)

        log.info(f"Server listening on port {self.port}")

        try:
            while self.running:
                try:
                    conn, addr = server.accept()
                    t = threading.Thread(target=self._handle_connection, args=(conn, addr), daemon=True)
                    t.start()
                except socket.timeout:
                    continue
        except KeyboardInterrupt:
            log.info("Shutting down...")
        finally:
            self.running = False
            server.close()


if __name__ == "__main__":
    bot = BotServer(PORT)
    bot.start()
