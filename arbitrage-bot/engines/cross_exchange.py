"""
Strategy 1: Cross-Exchange Arbitrage
Compra num exchange onde o preço está mais baixo,
vende noutro onde está mais alto.
"""
import asyncio
import time
from typing import Optional
from .base_engine import BaseEngine


class CrossExchangeEngine(BaseEngine):
    def __init__(self, config: dict, connector, portfolio):
        super().__init__("cross_exchange", config, connector, portfolio)
        self.pairs = config.get("pairs", [])
        self.min_spread = config.get("min_spread_pct", 0.15)
        self.max_trade = config.get("max_trade_usd", 500)

    async def scan(self) -> Optional[dict]:
        exchanges = self.connector.get_connected_exchanges()
        if len(exchanges) < 2:
            return None

        best_opportunity = None
        best_spread = 0

        for pair in self.pairs:
            prices = {}
            for ex_id in exchanges:
                ticker = await self.connector.fetch_ticker(ex_id, pair)
                if ticker and ticker.get("bid") and ticker.get("ask"):
                    prices[ex_id] = {
                        "bid": ticker["bid"],
                        "ask": ticker["ask"],
                        "last": ticker.get("last", (ticker["bid"] + ticker["ask"]) / 2),
                    }

            if len(prices) < 2:
                continue

            # Find best buy (lowest ask) and best sell (highest bid)
            best_buy_ex = min(prices.keys(), key=lambda x: prices[x]["ask"])
            best_sell_ex = max(prices.keys(), key=lambda x: prices[x]["bid"])

            if best_buy_ex == best_sell_ex:
                continue

            buy_price = prices[best_buy_ex]["ask"]
            sell_price = prices[best_sell_ex]["bid"]
            spread_pct = (sell_price - buy_price) / buy_price * 100

            if spread_pct > self.min_spread and spread_pct > best_spread:
                best_spread = spread_pct
                best_opportunity = {
                    "strategy": self.name,
                    "pair": pair,
                    "buy_exchange": best_buy_ex,
                    "sell_exchange": best_sell_ex,
                    "buy_price": buy_price,
                    "sell_price": sell_price,
                    "spread_pct": round(spread_pct, 4),
                    "potential_profit_usd": round(
                        self.max_trade * spread_pct / 100, 4
                    ),
                    "all_prices": prices,
                    "timestamp": time.time(),
                }

        return best_opportunity

    async def execute(self, opportunity: dict) -> Optional[dict]:
        pair = opportunity["pair"]
        buy_price = opportunity["buy_price"]
        sell_price = opportunity["sell_price"]
        amount = self.max_trade / buy_price

        if self.portfolio.mode == "paper":
            # Simulate: open buy, immediately close with sell price
            trade = self.portfolio.open_trade(
                strategy=self.name,
                pair=pair,
                exchange=opportunity["buy_exchange"],
                side="buy",
                price=buy_price,
                amount=amount,
            )
            if trade:
                pnl = self.portfolio.close_trade(trade.id, sell_price)
                return {
                    "trade_id": trade.id,
                    "pair": pair,
                    "buy_exchange": opportunity["buy_exchange"],
                    "sell_exchange": opportunity["sell_exchange"],
                    "buy_price": buy_price,
                    "sell_price": sell_price,
                    "amount": amount,
                    "spread_pct": opportunity["spread_pct"],
                    "pnl": pnl or 0,
                    "mode": "paper",
                }
        else:
            # Live mode: execute real orders
            buy_order = await self.connector.create_order(
                opportunity["buy_exchange"], pair, "market", "buy", amount
            )
            sell_order = await self.connector.create_order(
                opportunity["sell_exchange"], pair, "market", "sell", amount
            )
            if buy_order and sell_order:
                actual_buy = buy_order.get("average", buy_price)
                actual_sell = sell_order.get("average", sell_price)
                pnl = (actual_sell - actual_buy) * amount
                trade = self.portfolio.open_trade(
                    self.name, pair, opportunity["buy_exchange"],
                    "buy", actual_buy, amount
                )
                if trade:
                    self.portfolio.close_trade(trade.id, actual_sell)
                return {
                    "trade_id": trade.id if trade else "N/A",
                    "pair": pair,
                    "buy_price": actual_buy,
                    "sell_price": actual_sell,
                    "pnl": pnl,
                    "mode": "live",
                }

        return None
