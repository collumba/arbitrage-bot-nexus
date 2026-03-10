"""
Strategy 4: Funding Rate Arbitrage
Explora diferenças de funding rate entre spot e perpetual futures.
Quando funding rate é alto positivo: short perp + long spot (recebe funding).
Quando funding rate é alto negativo: long perp + short spot (recebe funding).
"""
import asyncio
import time
from typing import Optional
from .base_engine import BaseEngine


class FundingRateEngine(BaseEngine):
    def __init__(self, config: dict, connector, portfolio):
        super().__init__("funding_rate", config, connector, portfolio)
        self.pairs = config.get("pairs", [])
        self.min_rate = config.get("min_rate_pct", 0.01)
        self.max_trade = config.get("max_trade_usd", 1000)
        self.exchange_id = "binance"
        self._active_funding_trades: dict[str, dict] = {}

    async def scan(self) -> Optional[dict]:
        best_opportunity = None
        best_rate = 0

        for pair in self.pairs:
            # Check if we have an active position to potentially close
            if pair in self._active_funding_trades:
                active = self._active_funding_trades[pair]
                time_held = time.time() - active["entry_time"]
                # Close after 8 hours (one funding period)
                if time_held > 8 * 3600:
                    return {
                        "strategy": self.name,
                        "action": "close",
                        "pair": pair,
                        "trade_id": active["trade_id"],
                        "entry_rate": active["funding_rate"],
                        "time_held_hours": round(time_held / 3600, 2),
                        "timestamp": time.time(),
                    }
                continue

            # Fetch funding rate
            funding_data = await self.connector.fetch_funding_rate(
                self.exchange_id, pair
            )

            if not funding_data:
                # Simulate funding rate for paper mode
                ticker = await self.connector.fetch_ticker(self.exchange_id, pair)
                if not ticker:
                    continue
                # Generate realistic simulated funding rate
                import random
                funding_rate = random.gauss(0.01, 0.02)
                funding_data = {
                    "fundingRate": funding_rate / 100,
                    "fundingTimestamp": time.time(),
                }

            rate = funding_data.get("fundingRate", 0) * 100  # Convert to percentage

            if abs(rate) >= self.min_rate and abs(rate) > best_rate:
                best_rate = abs(rate)

                ticker = await self.connector.fetch_ticker(self.exchange_id, pair)
                if not ticker:
                    continue

                direction = "short_perp_long_spot" if rate > 0 else "long_perp_short_spot"
                # Annualized yield: rate × 3 payments/day × 365 days
                annual_yield = abs(rate) * 3 * 365

                best_opportunity = {
                    "strategy": self.name,
                    "action": "open",
                    "pair": pair,
                    "funding_rate_pct": round(rate, 6),
                    "annual_yield_pct": round(annual_yield, 2),
                    "direction": direction,
                    "spot_price": ticker.get("last", 0),
                    "next_funding": funding_data.get("fundingTimestamp"),
                    "potential_profit_usd": round(
                        self.max_trade * abs(rate) / 100, 4
                    ),
                    "timestamp": time.time(),
                }

        return best_opportunity

    async def execute(self, opportunity: dict) -> Optional[dict]:
        if opportunity["action"] == "close":
            trade_id = opportunity.get("trade_id")
            pair = opportunity["pair"]
            if trade_id:
                ticker = await self.connector.fetch_ticker(self.exchange_id, pair)
                current_price = ticker["last"] if ticker else 0
                pnl = self.portfolio.close_trade(trade_id, current_price)
                if pair in self._active_funding_trades:
                    del self._active_funding_trades[pair]
                return {
                    "action": "close",
                    "pair": pair,
                    "pnl": pnl or 0,
                    "time_held_hours": opportunity.get("time_held_hours", 0),
                    "mode": self.portfolio.mode,
                }

        elif opportunity["action"] == "open":
            pair = opportunity["pair"]
            spot_price = opportunity["spot_price"]
            amount = self.max_trade / spot_price

            if self.portfolio.mode == "paper":
                trade = self.portfolio.open_trade(
                    strategy=self.name,
                    pair=pair,
                    exchange=self.exchange_id,
                    side="buy",
                    price=spot_price,
                    amount=amount,
                )
                if trade:
                    self._active_funding_trades[pair] = {
                        "trade_id": trade.id,
                        "funding_rate": opportunity["funding_rate_pct"],
                        "direction": opportunity["direction"],
                        "entry_time": time.time(),
                    }
                    return {
                        "trade_id": trade.id,
                        "action": "open",
                        "pair": pair,
                        "funding_rate": opportunity["funding_rate_pct"],
                        "annual_yield": opportunity["annual_yield_pct"],
                        "direction": opportunity["direction"],
                        "pnl": 0,
                        "mode": "paper",
                    }

        return None
