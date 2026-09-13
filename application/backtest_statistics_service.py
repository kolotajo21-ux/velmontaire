from __future__ import annotations

from dataclasses import asdict, dataclass
from math import inf
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class BacktestStatistics:
    trades: int
    wins: int
    losses: int
    breakeven: int
    win_rate: float
    net_profit: float
    net_r: float
    gross_profit: float
    gross_loss: float
    profit_factor: float | None
    max_drawdown: float
    max_drawdown_r: float
    average_r: float
    average_win_r: float
    average_loss_r: float
    average_rr: float
    expectancy_r: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BacktestStatisticsService:
    """
    Converts raw closed-trade results into one stable SaaS/dashboard format.

    Expected trade fields:
      pnl / profit
      r / r_multiple
      optional rr / planned_rr
    """

    def calculate(self, trades: Iterable[Any]) -> BacktestStatistics:
        rows = [self._normalize_trade(t) for t in trades]

        count = len(rows)
        wins = sum(1 for t in rows if t["pnl"] > 0)
        losses = sum(1 for t in rows if t["pnl"] < 0)
        breakeven = count - wins - losses

        net_profit = sum(t["pnl"] for t in rows)
        net_r = sum(t["r"] for t in rows)

        gross_profit = sum(t["pnl"] for t in rows if t["pnl"] > 0)
        gross_loss_abs = abs(sum(t["pnl"] for t in rows if t["pnl"] < 0))

        if gross_loss_abs > 0:
            profit_factor = gross_profit / gross_loss_abs
        elif gross_profit > 0:
            profit_factor = None
        else:
            profit_factor = 0.0

        win_rate = wins / count if count else 0.0
        average_r = net_r / count if count else 0.0

        win_rs = [t["r"] for t in rows if t["r"] > 0]
        loss_rs = [t["r"] for t in rows if t["r"] < 0]

        average_win_r = sum(win_rs) / len(win_rs) if win_rs else 0.0
        average_loss_r = sum(loss_rs) / len(loss_rs) if loss_rs else 0.0

        rr_values = [t["rr"] for t in rows if t["rr"] is not None]
        average_rr = sum(rr_values) / len(rr_values) if rr_values else 0.0

        max_drawdown = self._max_drawdown([t["pnl"] for t in rows])
        max_drawdown_r = self._max_drawdown([t["r"] for t in rows])

        # In R-space expectancy is mathematically the average realized R/trade.
        expectancy_r = average_r

        return BacktestStatistics(
            trades=count,
            wins=wins,
            losses=losses,
            breakeven=breakeven,
            win_rate=round(win_rate, 8),
            net_profit=round(net_profit, 8),
            net_r=round(net_r, 8),
            gross_profit=round(gross_profit, 8),
            gross_loss=round(gross_loss_abs, 8),
            profit_factor=(
                round(profit_factor, 8)
                if profit_factor is not None
                else None
            ),
            max_drawdown=round(max_drawdown, 8),
            max_drawdown_r=round(max_drawdown_r, 8),
            average_r=round(average_r, 8),
            average_win_r=round(average_win_r, 8),
            average_loss_r=round(average_loss_r, 8),
            average_rr=round(average_rr, 8),
            expectancy_r=round(expectancy_r, 8),
        )

    def dashboard_payload(
        self,
        *,
        backtest_id: str,
        strategy_id: str,
        version_id: str,
        trades: Iterable[Any],
    ) -> dict[str, Any]:
        stats = self.calculate(trades)
        return {
            "backtest_id": backtest_id,
            "strategy_id": strategy_id,
            "version_id": version_id,
            "status": "COMPLETED",
            "statistics": stats.to_dict(),
        }

    @staticmethod
    def _normalize_trade(trade: Any) -> dict[str, float | None]:
        def read(*names: str, default: Any = None) -> Any:
            for name in names:
                if isinstance(trade, dict) and name in trade:
                    return trade[name]
                if hasattr(trade, name):
                    return getattr(trade, name)
            return default

        pnl = read("pnl", "profit")
        r_value = read("r", "r_multiple")
        rr = read("rr", "planned_rr", default=None)

        if pnl is None:
            raise ValueError("trade_pnl_required")
        if r_value is None:
            raise ValueError("trade_r_required")

        return {
            "pnl": float(pnl),
            "r": float(r_value),
            "rr": float(rr) if rr is not None else None,
        }

    @staticmethod
    def _max_drawdown(values: list[float]) -> float:
        equity = 0.0
        peak = 0.0
        maximum = 0.0

        for value in values:
            equity += value
            peak = max(peak, equity)
            maximum = max(maximum, peak - equity)

        return maximum
