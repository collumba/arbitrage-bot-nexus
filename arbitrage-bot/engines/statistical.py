"""
Strategy 3: Statistical Arbitrage (Pairs Trading)
Identifica pares correlacionados e opera quando o spread
se desvia da média (mean reversion com z-score).
"""
import asyncio
import time
import numpy as np
from typing import Optional
from .base_engine import BaseEngine


class StatisticalEngine(BaseEngine):
    def __init__(self, config: dict, connector, portfolio):
        super().__init__("statistical", config, connector, portfolio)
        self.pair_combos = config.get("pairs", [])
        self.lookback = config.get("lookback_periods", 100)
        self.z_entry = config.get("z_score_entry", 2.0)
        self.z_exit = config.get("z_score_exit", 0.5)
        self.max_trade = config.get("max_trade_usd", 400)
        self.exchange_id = "binance"
        self._price_history: dict[str, list[float]] = {}
        self._active_stat_trades: dict[str, dict] = {}

    async def _update_prices(self, pair: str):
        """Fetch latest price and append to history"""
        ticker = await self.connector.fetch_ticker(self.exchange_id, pair)
        if ticker and ticker.get("last"):
            if pair not in self._price_history:
                # Bootstrap with OHLCV data
                candles = await self.connector.fetch_ohlcv(
                    self.exchange_id, pair, "1m", self.lookback
                )
                if candles:
                    self._price_history[pair] = [c[4] for c in candles]
                else:
                    self._price_history[pair] = []

            self._price_history[pair].append(ticker["last"])

            if len(self._price_history[pair]) > self.lookback * 2:
                self._price_history[pair] = self._price_history[pair][-self.lookback:]

    def _calculate_z_score(self, pair_a: str, pair_b: str) -> Optional[float]:
        prices_a = self._price_history.get(pair_a, [])
        prices_b = self._price_history.get(pair_b, [])

        min_len = min(len(prices_a), len(prices_b))
        if min_len < 30:
            return None

        a = np.array(prices_a[-min_len:])
        b = np.array(prices_b[-min_len:])

        # Calculate spread ratio
        ratio = a / b
        mean = np.mean(ratio)
        std = np.std(ratio)

        if std == 0:
            return None

        current_ratio = ratio[-1]
        z_score = (current_ratio - mean) / std
        return float(z_score)

    async def scan(self) -> Optional[dict]:
        best_opportunity = None
        best_z = 0

        for pair_a, pair_b in self.pair_combos:
            await self._update_prices(pair_a)
            await self._update_prices(pair_b)

            combo_key = f"{pair_a}:{pair_b}"

            z_score = self._calculate_z_score(pair_a, pair_b)
            if z_score is None:
                continue

            # Check for exit signal on active trades
            if combo_key in self._active_stat_trades:
                if abs(z_score) < self.z_exit:
                    active = self._active_stat_trades[combo_key]
                    # Signal to close
                    best_opportunity = {
                        "strategy": self.name,
                        "action": "close",
                        "pair_a": pair_a,
                        "pair_b": pair_b,
                        "z_score": round(z_score, 4),
                        "trade_id": active.get("trade_id"),
                        "entry_z": active.get("z_score"),
                        "timestamp": time.time(),
                    }
                    return best_opportunity
                continue

            # Check for entry signal
            if abs(z_score) > self.z_entry and abs(z_score) > best_z:
                best_z = abs(z_score)
                direction = "short_a_long_b" if z_score > 0 else "long_a_short_b"

                prices_a = self._price_history[pair_a]
                prices_b = self._price_history[pair_b]
                correlation = float(np.corrcoef(
                    prices_a[-30:], prices_b[-30:]
                )[0, 1])

                best_opportunity = {
                    "strategy": self.name,
                    "action": "open",
                    "pair_a": pair_a,
                    "pair_b": pair_b,
                    "z_score": round(z_score, 4),
                    "direction": direction,
                    "correlation": round(correlation, 4),
                    "price_a": prices_a[-1],
                    "price_b": prices_b[-1],
                    "potential_profit_usd": round(
                        self.max_trade * abs(z_score) * 0.1 / 100, 4
                    ),
                    "timestamp": time.time(),
                }

        return best_opportunity

    async def execute(self, opportunity: dict) -> Optional[dict]:
        if opportunity["action"] == "close":
            trade_id = opportunity.get("trade_id")
            combo_key = f"{opportunity['pair_a']}:{opportunity['pair_b']}"

            if trade_id:
                current_price_a = self._price_history.get(opportunity["pair_a"], [0])[-1]
                pnl = self.portfolio.close_trade(trade_id, current_price_a)
                del self._active_stat_trades[combo_key]
                return {
                    "action": "close",
                    "pair_a": opportunity["pair_a"],
                    "pair_b": opportunity["pair_b"],
                    "exit_z": opportunity["z_score"],
                    "pnl": pnl or 0,
                    "mode": self.portfolio.mode,
                }

        elif opportunity["action"] == "open":
            pair_a = opportunity["pair_a"]
            price_a = opportunity["price_a"]
            amount = self.max_trade / price_a

            if self.portfolio.mode == "paper":
                trade = self.portfolio.open_trade(
                    strategy=self.name,
                    pair=pair_a,
                    exchange=self.exchange_id,
                    side="buy" if "long_a" in opportunity["direction"] else "sell",
                    price=price_a,
                    amount=amount,
                )
                if trade:
                    combo_key = f"{pair_a}:{opportunity['pair_b']}"
                    self._active_stat_trades[combo_key] = {
                        "trade_id": trade.id,
                        "z_score": opportunity["z_score"],
                        "direction": opportunity["direction"],
                    }
                    return {
                        "trade_id": trade.id,
                        "action": "open",
                        "pair_a": pair_a,
                        "pair_b": opportunity["pair_b"],
                        "direction": opportunity["direction"],
                        "z_score": opportunity["z_score"],
                        "pnl": 0,
                        "mode": "paper",
                    }

        return None
