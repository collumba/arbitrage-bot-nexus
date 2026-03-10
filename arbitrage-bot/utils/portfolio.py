"""
Portfolio Manager — Gestão de saldo, posições e P&L
Suporta modo paper (simulado) e live (real)
"""
import time
import json
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Trade:
    id: str
    strategy: str
    side: str  # "buy" ou "sell"
    pair: str
    exchange: str
    price: float
    amount: float
    fee: float
    timestamp: float
    pnl: float = 0.0
    status: str = "open"  # "open", "closed"

    def to_dict(self):
        return asdict(self)


@dataclass
class Position:
    pair: str
    strategy: str
    exchange: str
    entry_price: float
    amount: float
    side: str
    timestamp: float
    unrealized_pnl: float = 0.0

    def to_dict(self):
        return asdict(self)


class PortfolioManager:
    def __init__(self, initial_balance: float, mode: str = "paper"):
        self.mode = mode
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.positions: list[Position] = []
        self.trades: list[Trade] = []
        self.equity_curve: list[dict] = []
        self.daily_pnl: float = 0.0
        self.total_pnl: float = 0.0
        self.win_count: int = 0
        self.loss_count: int = 0
        self.max_balance: float = initial_balance
        self.max_drawdown: float = 0.0
        self._trade_counter: int = 0
        self._start_time = time.time()

        self._record_equity()

    def _generate_trade_id(self) -> str:
        self._trade_counter += 1
        return f"T{self._trade_counter:06d}"

    def _record_equity(self):
        equity = self.balance + sum(p.unrealized_pnl for p in self.positions)
        self.equity_curve.append({
            "timestamp": time.time(),
            "equity": equity,
            "balance": self.balance,
            "positions": len(self.positions),
        })
        if equity > self.max_balance:
            self.max_balance = equity
        dd = (self.max_balance - equity) / self.max_balance * 100 if self.max_balance > 0 else 0
        if dd > self.max_drawdown:
            self.max_drawdown = dd

    def open_trade(self, strategy: str, pair: str, exchange: str,
                   side: str, price: float, amount: float, fee_pct: float = 0.1) -> Optional[Trade]:
        cost = price * amount
        fee = cost * fee_pct / 100

        if cost + fee > self.balance:
            return None

        self.balance -= (cost + fee)

        trade = Trade(
            id=self._generate_trade_id(),
            strategy=strategy,
            side=side,
            pair=pair,
            exchange=exchange,
            price=price,
            amount=amount,
            fee=fee,
            timestamp=time.time(),
        )
        self.trades.append(trade)

        pos = Position(
            pair=pair,
            strategy=strategy,
            exchange=exchange,
            entry_price=price,
            amount=amount,
            side=side,
            timestamp=time.time(),
        )
        self.positions.append(pos)
        self._record_equity()
        return trade

    def close_trade(self, trade_id: str, exit_price: float, fee_pct: float = 0.1) -> Optional[float]:
        trade = next((t for t in self.trades if t.id == trade_id and t.status == "open"), None)
        if not trade:
            return None

        revenue = exit_price * trade.amount
        fee = revenue * fee_pct / 100

        if trade.side == "buy":
            pnl = (exit_price - trade.price) * trade.amount - trade.fee - fee
        else:
            pnl = (trade.price - exit_price) * trade.amount - trade.fee - fee

        trade.pnl = pnl
        trade.status = "closed"
        self.balance += revenue - fee
        self.total_pnl += pnl
        self.daily_pnl += pnl

        if pnl > 0:
            self.win_count += 1
        else:
            self.loss_count += 1

        self.positions = [p for p in self.positions
                          if not (p.pair == trade.pair and p.strategy == trade.strategy)]
        self._record_equity()
        return pnl

    def get_stats(self) -> dict:
        total_trades = self.win_count + self.loss_count
        win_rate = (self.win_count / total_trades * 100) if total_trades > 0 else 0
        runtime = time.time() - self._start_time
        roi = (self.total_pnl / self.initial_balance * 100) if self.initial_balance > 0 else 0

        return {
            "mode": self.mode,
            "initial_balance": self.initial_balance,
            "current_balance": round(self.balance, 2),
            "total_pnl": round(self.total_pnl, 2),
            "daily_pnl": round(self.daily_pnl, 2),
            "roi_pct": round(roi, 4),
            "total_trades": total_trades,
            "win_count": self.win_count,
            "loss_count": self.loss_count,
            "win_rate": round(win_rate, 2),
            "open_positions": len(self.positions),
            "max_drawdown_pct": round(self.max_drawdown, 4),
            "runtime_sec": round(runtime, 0),
            "equity_curve": self.equity_curve[-200:],
            "positions": [p.to_dict() for p in self.positions],
            "recent_trades": [t.to_dict() for t in self.trades[-50:]],
        }

    def get_strategy_breakdown(self) -> dict:
        breakdown = {}
        for t in self.trades:
            if t.strategy not in breakdown:
                breakdown[t.strategy] = {
                    "trades": 0, "wins": 0, "losses": 0,
                    "total_pnl": 0, "avg_pnl": 0
                }
            s = breakdown[t.strategy]
            s["trades"] += 1
            s["total_pnl"] += t.pnl
            if t.pnl > 0:
                s["wins"] += 1
            elif t.pnl < 0:
                s["losses"] += 1

        for s in breakdown.values():
            if s["trades"] > 0:
                s["avg_pnl"] = round(s["total_pnl"] / s["trades"], 4)
                s["win_rate"] = round(s["wins"] / s["trades"] * 100, 2)
            s["total_pnl"] = round(s["total_pnl"], 2)
        return breakdown
