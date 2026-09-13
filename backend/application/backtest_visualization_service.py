from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class EquityPoint:
    index: int
    trade_id: str
    equity: float
    cumulative_pnl: float
    cumulative_r: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TradeListItem:
    index: int
    trade_id: str
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    pnl: float
    r: float
    result: str
    opened_at: str | None
    closed_at: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BacktestVisualizationService:
    """
    Stable product payload for dashboard equity curve + detailed trade list.
    Pure transformation layer: no broker/MT5 access.
    """

    def build(
        self,
        *,
        backtest_id: str,
        strategy_id: str,
        version_id: str,
        starting_balance: float,
        trades: Iterable[Any],
    ) -> dict[str, Any]:
        if starting_balance <= 0:
            raise ValueError("starting_balance_must_be_positive")

        normalized = [
            self._normalize_trade(t, i)
            for i, t in enumerate(trades, start=1)
        ]

        equity = float(starting_balance)
        cumulative_pnl = 0.0
        cumulative_r = 0.0

        curve = [{
            "index": 0,
            "trade_id": "START",
            "equity": round(equity, 8),
            "cumulative_pnl": 0.0,
            "cumulative_r": 0.0,
        }]

        trade_list: list[dict[str, Any]] = []

        for t in normalized:
            cumulative_pnl += t["pnl"]
            cumulative_r += t["r"]
            equity = starting_balance + cumulative_pnl

            curve.append(
                EquityPoint(
                    index=t["index"],
                    trade_id=t["trade_id"],
                    equity=round(equity, 8),
                    cumulative_pnl=round(cumulative_pnl, 8),
                    cumulative_r=round(cumulative_r, 8),
                ).to_dict()
            )

            trade_list.append(
                TradeListItem(
                    index=t["index"],
                    trade_id=t["trade_id"],
                    symbol=t["symbol"],
                    side=t["side"],
                    entry_price=t["entry_price"],
                    exit_price=t["exit_price"],
                    pnl=t["pnl"],
                    r=t["r"],
                    result=self._result(t["pnl"]),
                    opened_at=t["opened_at"],
                    closed_at=t["closed_at"],
                ).to_dict()
            )

        return {
            "backtest_id": backtest_id,
            "strategy_id": strategy_id,
            "version_id": version_id,
            "starting_balance": round(float(starting_balance), 8),
            "ending_balance": round(equity, 8),
            "equity_curve": curve,
            "trades": trade_list,
        }

    @staticmethod
    def _result(pnl: float) -> str:
        if pnl > 0:
            return "WIN"
        if pnl < 0:
            return "LOSS"
        return "BREAKEVEN"

    @staticmethod
    def _normalize_trade(trade: Any, index: int) -> dict[str, Any]:
        def read(*names: str, default: Any = None) -> Any:
            for name in names:
                if isinstance(trade, dict) and name in trade:
                    return trade[name]
                if hasattr(trade, name):
                    return getattr(trade, name)
            return default

        pnl = read("pnl", "profit")
        r_value = read("r", "r_multiple")
        entry = read("entry_price", "entry")
        exit_ = read("exit_price", "exit")

        if pnl is None:
            raise ValueError("trade_pnl_required")
        if r_value is None:
            raise ValueError("trade_r_required")
        if entry is None:
            raise ValueError("trade_entry_price_required")
        if exit_ is None:
            raise ValueError("trade_exit_price_required")

        side = str(read("side", "direction", default="")).strip().upper()
        if side not in {"BUY", "SELL", "LONG", "SHORT"}:
            raise ValueError("trade_side_invalid")

        symbol = str(read("symbol", default="")).strip().upper()
        if not symbol:
            raise ValueError("trade_symbol_required")

        trade_id = str(
            read("trade_id", "id", default=f"trade_{index}")
        ).strip()

        return {
            "index": index,
            "trade_id": trade_id,
            "symbol": symbol,
            "side": side,
            "entry_price": float(entry),
            "exit_price": float(exit_),
            "pnl": float(pnl),
            "r": float(r_value),
            "opened_at": read("opened_at", "entry_time", default=None),
            "closed_at": read("closed_at", "exit_time", default=None),
        }
