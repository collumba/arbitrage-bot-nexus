"""
Base Engine — Classe base para todas as estratégias de arbitragem
"""
import asyncio
import time
from abc import ABC, abstractmethod
from typing import Optional


class BaseEngine(ABC):
    """Classe base para todos os bots de arbitragem"""

    def __init__(self, name: str, config: dict, connector, portfolio):
        self.name = name
        self.config = config
        self.connector = connector
        self.portfolio = portfolio
        self.running = False
        self.opportunities_found = 0
        self.trades_executed = 0
        self.total_profit = 0.0
        self.last_scan_time: float = 0
        self.last_opportunity: Optional[dict] = None
        self.scan_history: list[dict] = []
        self._start_time: Optional[float] = None

    @abstractmethod
    async def scan(self) -> Optional[dict]:
        """Scan for arbitrage opportunities. Returns opportunity dict or None."""
        pass

    @abstractmethod
    async def execute(self, opportunity: dict) -> Optional[dict]:
        """Execute an arbitrage trade. Returns trade result or None."""
        pass

    async def run(self):
        """Main loop: scan → evaluate → execute"""
        self.running = True
        self._start_time = time.time()
        interval = self.config.get("scan_interval_sec", 5)

        print(f"  ▸ [{self.name}] Engine started (interval: {interval}s)")

        while self.running:
            try:
                self.last_scan_time = time.time()
                opportunity = await self.scan()

                if opportunity:
                    self.opportunities_found += 1
                    self.last_opportunity = opportunity
                    self.scan_history.append({
                        "timestamp": time.time(),
                        "type": "opportunity",
                        "data": opportunity,
                    })

                    if self._should_execute(opportunity):
                        result = await self.execute(opportunity)
                        if result:
                            self.trades_executed += 1
                            self.total_profit += result.get("pnl", 0)
                            self.scan_history.append({
                                "timestamp": time.time(),
                                "type": "trade",
                                "data": result,
                            })

                # Keep history manageable
                if len(self.scan_history) > 500:
                    self.scan_history = self.scan_history[-300:]

            except Exception as e:
                self.scan_history.append({
                    "timestamp": time.time(),
                    "type": "error",
                    "data": {"error": str(e)},
                })

            await asyncio.sleep(interval)

    def stop(self):
        self.running = False
        print(f"  ▸ [{self.name}] Engine stopped")

    def _should_execute(self, opportunity: dict) -> bool:
        """Risk checks before execution"""
        from config import RISK

        if self.portfolio.get_stats()["open_positions"] >= RISK["max_open_positions"]:
            return False

        if self.portfolio.max_drawdown >= RISK["max_drawdown_pct"]:
            return False

        if abs(self.portfolio.daily_pnl) >= RISK["max_daily_loss_usd"] and self.portfolio.daily_pnl < 0:
            return False

        return True

    def get_status(self) -> dict:
        runtime = time.time() - self._start_time if self._start_time else 0
        return {
            "name": self.name,
            "running": self.running,
            "opportunities_found": self.opportunities_found,
            "trades_executed": self.trades_executed,
            "total_profit": round(self.total_profit, 4),
            "last_scan": self.last_scan_time,
            "last_opportunity": self.last_opportunity,
            "runtime_sec": round(runtime),
            "recent_events": self.scan_history[-20:],
        }
