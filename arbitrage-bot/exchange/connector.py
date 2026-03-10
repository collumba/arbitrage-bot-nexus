"""
Exchange Connector — Abstração sobre CCXT para conectar a múltiplas exchanges
Suporta dados reais em modo paper e execução real em modo live
"""
import asyncio
import ccxt.async_support as ccxt
from typing import Optional
import time


class ExchangeConnector:
    """Gerencia conexões com múltiplas exchanges via CCXT"""

    def __init__(self):
        self.exchanges: dict[str, ccxt.Exchange] = {}
        self._price_cache: dict[str, dict] = {}
        self._cache_ttl = 1.0  # seconds

    async def connect(self, exchange_id: str, config: dict):
        exchange_class = getattr(ccxt, exchange_id, None)
        if not exchange_class:
            raise ValueError(f"Exchange '{exchange_id}' not supported")

        params = {
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        }
        if config.get("apiKey"):
            params["apiKey"] = config["apiKey"]
            params["secret"] = config["secret"]
        if config.get("password"):
            params["password"] = config["password"]
        if config.get("sandbox"):
            params["sandbox"] = True

        ex = exchange_class(params)
        try:
            await ex.load_markets()
            self.exchanges[exchange_id] = ex
            print(f"  ✓ Connected to {exchange_id} ({len(ex.markets)} markets)")
        except Exception as e:
            print(f"  ✗ Failed to connect to {exchange_id}: {e}")
            await ex.close()

    async def disconnect_all(self):
        for ex in self.exchanges.values():
            await ex.close()
        self.exchanges.clear()

    async def fetch_ticker(self, exchange_id: str, symbol: str) -> Optional[dict]:
        ex = self.exchanges.get(exchange_id)
        if not ex or symbol not in ex.markets:
            return None

        cache_key = f"{exchange_id}:{symbol}"
        cached = self._price_cache.get(cache_key)
        if cached and time.time() - cached["ts"] < self._cache_ttl:
            return cached["data"]

        try:
            ticker = await ex.fetch_ticker(symbol)
            self._price_cache[cache_key] = {"data": ticker, "ts": time.time()}
            return ticker
        except Exception:
            return None

    async def fetch_tickers(self, exchange_id: str, symbols: list[str]) -> dict:
        ex = self.exchanges.get(exchange_id)
        if not ex:
            return {}
        try:
            tickers = await ex.fetch_tickers(symbols)
            now = time.time()
            for sym, ticker in tickers.items():
                self._price_cache[f"{exchange_id}:{sym}"] = {"data": ticker, "ts": now}
            return tickers
        except Exception:
            results = {}
            for sym in symbols:
                t = await self.fetch_ticker(exchange_id, sym)
                if t:
                    results[sym] = t
            return results

    async def fetch_order_book(self, exchange_id: str, symbol: str, limit: int = 10) -> Optional[dict]:
        ex = self.exchanges.get(exchange_id)
        if not ex or symbol not in ex.markets:
            return None
        try:
            return await ex.fetch_order_book(symbol, limit)
        except Exception:
            return None

    async def fetch_ohlcv(self, exchange_id: str, symbol: str,
                          timeframe: str = "1m", limit: int = 100) -> list:
        ex = self.exchanges.get(exchange_id)
        if not ex or symbol not in ex.markets:
            return []
        try:
            return await ex.fetch_ohlcv(symbol, timeframe, limit=limit)
        except Exception:
            return []

    async def fetch_funding_rate(self, exchange_id: str, symbol: str) -> Optional[dict]:
        ex = self.exchanges.get(exchange_id)
        if not ex:
            return None
        try:
            if hasattr(ex, 'fetch_funding_rate'):
                return await ex.fetch_funding_rate(symbol)
        except Exception:
            pass
        return None

    async def create_order(self, exchange_id: str, symbol: str,
                           order_type: str, side: str, amount: float,
                           price: Optional[float] = None) -> Optional[dict]:
        ex = self.exchanges.get(exchange_id)
        if not ex:
            return None
        try:
            return await ex.create_order(symbol, order_type, side, amount, price)
        except Exception as e:
            print(f"  Order error on {exchange_id}: {e}")
            return None

    def get_market_info(self, exchange_id: str, symbol: str) -> Optional[dict]:
        ex = self.exchanges.get(exchange_id)
        if not ex or symbol not in ex.markets:
            return None
        return ex.markets[symbol]

    def get_connected_exchanges(self) -> list[str]:
        return list(self.exchanges.keys())
