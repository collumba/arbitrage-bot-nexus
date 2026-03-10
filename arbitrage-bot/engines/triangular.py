"""
Strategy 2: Triangular Arbitrage
Explora ineficiências entre 3 pares de moedas na mesma exchange.
Ex: USDT → BTC → ETH → USDT (se o ciclo dá mais do que começou)
"""
import asyncio
import time
import itertools
from typing import Optional
from .base_engine import BaseEngine


class TriangularEngine(BaseEngine):
    def __init__(self, config: dict, connector, portfolio):
        super().__init__("triangular", config, connector, portfolio)
        self.exchange_id = config.get("exchange", "binance")
        self.base_currencies = config.get("base_currencies", ["USDT", "BTC", "ETH"])
        self.min_profit = config.get("min_profit_pct", 0.08)
        self.max_trade = config.get("max_trade_usd", 300)

    def _find_triangles(self) -> list[list[str]]:
        """Find all valid triangular paths"""
        ex = self.connector.exchanges.get(self.exchange_id)
        if not ex:
            return []

        symbols = list(ex.markets.keys())
        triangles = []

        for base in self.base_currencies:
            # Find pairs involving the base
            base_pairs = [s for s in symbols if s.endswith(f"/{base}")]
            currencies = [s.split("/")[0] for s in base_pairs]

            for c1, c2 in itertools.combinations(currencies, 2):
                # Check if c1/c2 or c2/c1 pair exists
                pair_12 = f"{c1}/{c2}"
                pair_21 = f"{c2}/{c1}"
                if pair_12 in symbols:
                    triangles.append([
                        f"{c1}/{base}",  # Buy c1 with base
                        pair_12,          # Convert c1 to c2
                        f"{c2}/{base}",  # Sell c2 for base
                    ])
                elif pair_21 in symbols:
                    triangles.append([
                        f"{c2}/{base}",
                        pair_21,
                        f"{c1}/{base}",
                    ])

        return triangles[:50]  # Limit to top 50

    async def scan(self) -> Optional[dict]:
        triangles = self._find_triangles()
        if not triangles:
            return None

        best_opportunity = None
        best_profit = 0

        for tri in triangles:
            try:
                tickers = {}
                valid = True
                for pair in tri:
                    ticker = await self.connector.fetch_ticker(self.exchange_id, pair)
                    if not ticker or not ticker.get("bid") or not ticker.get("ask"):
                        valid = False
                        break
                    tickers[pair] = ticker

                if not valid:
                    continue

                # Calculate forward path profit
                # Step 1: Buy pair[0] (spend base, get c1)
                amount_c1 = 1.0 / tickers[tri[0]]["ask"]
                # Step 2: Trade c1 for c2
                amount_c2 = amount_c1 * tickers[tri[1]]["bid"]
                # Step 3: Sell c2 for base
                final_amount = amount_c2 * tickers[tri[2]]["bid"]

                profit_pct = (final_amount - 1.0) * 100
                # Account for ~0.3% total fees (3 trades × 0.1%)
                net_profit_pct = profit_pct - 0.3

                if net_profit_pct > self.min_profit and net_profit_pct > best_profit:
                    best_profit = net_profit_pct
                    best_opportunity = {
                        "strategy": self.name,
                        "exchange": self.exchange_id,
                        "path": tri,
                        "prices": {
                            p: {"bid": t["bid"], "ask": t["ask"]}
                            for p, t in tickers.items()
                        },
                        "gross_profit_pct": round(profit_pct, 4),
                        "net_profit_pct": round(net_profit_pct, 4),
                        "potential_profit_usd": round(
                            self.max_trade * net_profit_pct / 100, 4
                        ),
                        "timestamp": time.time(),
                    }

            except Exception:
                continue

        return best_opportunity

    async def execute(self, opportunity: dict) -> Optional[dict]:
        path = opportunity["path"]
        amount_usd = self.max_trade
        first_price = opportunity["prices"][path[0]]["ask"]

        if self.portfolio.mode == "paper":
            # Simulate the triangular trade
            trade = self.portfolio.open_trade(
                strategy=self.name,
                pair=path[0],
                exchange=self.exchange_id,
                side="buy",
                price=first_price,
                amount=amount_usd / first_price,
            )
            if trade:
                # Simulate profit
                exit_price = first_price * (1 + opportunity["net_profit_pct"] / 100)
                pnl = self.portfolio.close_trade(trade.id, exit_price)
                return {
                    "trade_id": trade.id,
                    "path": path,
                    "exchange": self.exchange_id,
                    "profit_pct": opportunity["net_profit_pct"],
                    "pnl": pnl or 0,
                    "mode": "paper",
                }
        else:
            # Live: execute 3 market orders in sequence
            prices = opportunity["prices"]
            amount = amount_usd / prices[path[0]]["ask"]

            order1 = await self.connector.create_order(
                self.exchange_id, path[0], "market", "buy", amount
            )
            if not order1:
                return None

            amount_mid = amount * prices[path[1]]["bid"]
            order2 = await self.connector.create_order(
                self.exchange_id, path[1], "market", "sell", amount
            )

            amount_final = amount_mid
            order3 = await self.connector.create_order(
                self.exchange_id, path[2], "market", "sell", amount_final
            )

            if order1 and order2 and order3:
                pnl = amount_usd * opportunity["net_profit_pct"] / 100
                trade = self.portfolio.open_trade(
                    self.name, path[0], self.exchange_id,
                    "buy", first_price, amount
                )
                if trade:
                    self.portfolio.close_trade(trade.id, first_price * (1 + opportunity["net_profit_pct"] / 100))
                return {
                    "path": path,
                    "pnl": pnl,
                    "mode": "live",
                }

        return None
