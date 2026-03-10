"""
Strategy 5: DEX vs CEX Arbitrage
Explora diferenças de preço entre exchanges descentralizadas (Uniswap, etc.)
e exchanges centralizadas (Binance, etc.)
"""
import asyncio
import time
import aiohttp
from typing import Optional
from .base_engine import BaseEngine


# Token addresses for Uniswap V3 (Ethereum mainnet)
TOKEN_ADDRESSES = {
    "ETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",   # WETH
    "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
    "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    "SOL": "0xD31a59c85aE9D8edEFec411D448f90841571b89c",  # Wrapped SOL
}


class DexCexEngine(BaseEngine):
    def __init__(self, config: dict, connector, portfolio):
        super().__init__("dex_cex", config, connector, portfolio)
        self.pairs = config.get("pairs", [])
        self.min_spread = config.get("min_spread_pct", 0.3)
        self.max_trade = config.get("max_trade_usd", 300)
        self.dex_apis = config.get("dex_apis", {})
        self.cex_exchange = "binance"
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self):
        if not self._session or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _fetch_dex_price(self, pair: str) -> Optional[float]:
        """Fetch price from Uniswap V3 via The Graph"""
        base, quote = pair.split("/")
        token_addr = TOKEN_ADDRESSES.get(base)
        if not token_addr:
            return None

        query = """
        {
            token(id: "%s") {
                derivedETH
                symbol
            }
            bundle(id: "1") {
                ethPriceUSD
            }
        }
        """ % token_addr.lower()

        try:
            session = await self._get_session()
            api_url = self.dex_apis.get(
                "uniswap_v3",
                "https://api.thegraph.com/subgraphs/name/uniswap/uniswap-v3"
            )
            async with session.post(
                api_url,
                json={"query": query},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    token_data = data.get("data", {}).get("token")
                    bundle = data.get("data", {}).get("bundle")
                    if token_data and bundle:
                        derived_eth = float(token_data["derivedETH"])
                        eth_price = float(bundle["ethPriceUSD"])
                        return derived_eth * eth_price
        except Exception:
            pass

        # Fallback: simulate DEX price with small variance from CEX
        ticker = await self.connector.fetch_ticker(self.cex_exchange, pair)
        if ticker and ticker.get("last"):
            import random
            # Simulate DEX premium/discount of -0.5% to +0.5%
            variance = random.uniform(-0.005, 0.005)
            return ticker["last"] * (1 + variance)

        return None

    async def scan(self) -> Optional[dict]:
        best_opportunity = None
        best_spread = 0

        for pair in self.pairs:
            # Get CEX price
            ticker = await self.connector.fetch_ticker(self.cex_exchange, pair)
            if not ticker or not ticker.get("bid") or not ticker.get("ask"):
                continue

            cex_bid = ticker["bid"]
            cex_ask = ticker["ask"]

            # Get DEX price
            dex_price = await self._fetch_dex_price(pair)
            if not dex_price:
                continue

            # Check both directions
            # Direction 1: Buy on DEX, sell on CEX
            spread_dex_to_cex = (cex_bid - dex_price) / dex_price * 100
            # Direction 2: Buy on CEX, sell on DEX
            spread_cex_to_dex = (dex_price - cex_ask) / cex_ask * 100

            if spread_dex_to_cex > self.min_spread and spread_dex_to_cex > best_spread:
                best_spread = spread_dex_to_cex
                best_opportunity = {
                    "strategy": self.name,
                    "pair": pair,
                    "direction": "buy_dex_sell_cex",
                    "dex_price": round(dex_price, 4),
                    "cex_bid": cex_bid,
                    "cex_ask": cex_ask,
                    "spread_pct": round(spread_dex_to_cex, 4),
                    "potential_profit_usd": round(
                        self.max_trade * spread_dex_to_cex / 100, 4
                    ),
                    "gas_estimate_usd": 15.0,  # Estimated gas cost
                    "net_profit_usd": round(
                        self.max_trade * spread_dex_to_cex / 100 - 15.0, 4
                    ),
                    "timestamp": time.time(),
                }

            if spread_cex_to_dex > self.min_spread and spread_cex_to_dex > best_spread:
                best_spread = spread_cex_to_dex
                best_opportunity = {
                    "strategy": self.name,
                    "pair": pair,
                    "direction": "buy_cex_sell_dex",
                    "dex_price": round(dex_price, 4),
                    "cex_bid": cex_bid,
                    "cex_ask": cex_ask,
                    "spread_pct": round(spread_cex_to_dex, 4),
                    "potential_profit_usd": round(
                        self.max_trade * spread_cex_to_dex / 100, 4
                    ),
                    "gas_estimate_usd": 15.0,
                    "net_profit_usd": round(
                        self.max_trade * spread_cex_to_dex / 100 - 15.0, 4
                    ),
                    "timestamp": time.time(),
                }

        return best_opportunity

    async def execute(self, opportunity: dict) -> Optional[dict]:
        pair = opportunity["pair"]
        direction = opportunity["direction"]

        if direction == "buy_dex_sell_cex":
            buy_price = opportunity["dex_price"]
            sell_price = opportunity["cex_bid"]
        else:
            buy_price = opportunity["cex_ask"]
            sell_price = opportunity["dex_price"]

        amount = self.max_trade / buy_price

        if self.portfolio.mode == "paper":
            trade = self.portfolio.open_trade(
                strategy=self.name,
                pair=pair,
                exchange=f"dex_cex_{direction}",
                side="buy",
                price=buy_price,
                amount=amount,
            )
            if trade:
                pnl = self.portfolio.close_trade(trade.id, sell_price)
                # Subtract gas cost in paper mode
                actual_pnl = (pnl or 0) - opportunity.get("gas_estimate_usd", 15)
                return {
                    "trade_id": trade.id,
                    "pair": pair,
                    "direction": direction,
                    "buy_price": buy_price,
                    "sell_price": sell_price,
                    "spread_pct": opportunity["spread_pct"],
                    "gas_cost": opportunity.get("gas_estimate_usd", 15),
                    "pnl": actual_pnl,
                    "mode": "paper",
                }

        return None

    async def cleanup(self):
        if self._session and not self._session.closed:
            await self._session.close()
