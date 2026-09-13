from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable


@dataclass
class EquityPoint:
    trade_number: int
    result_r: float
    cumulative_r: float

    balance_before: float
    risk_money: float
    profit_money: float
    balance_after: float

    peak_balance: float
    drawdown_money: float
    drawdown_percent: float

    close_time: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EquityCurve:
    starting_balance: float
    final_balance: float
    net_profit: float
    return_percent: float

    max_drawdown_money: float
    max_drawdown_percent: float
    max_drawdown_r: float

    points: list[EquityPoint]

    def to_dict(self) -> dict[str, Any]:
        return {
            "starting_balance": self.starting_balance,
            "final_balance": self.final_balance,
            "net_profit": self.net_profit,
            "return_percent": self.return_percent,
            "max_drawdown_money": self.max_drawdown_money,
            "max_drawdown_percent": self.max_drawdown_percent,
            "max_drawdown_r": self.max_drawdown_r,
            "points": [
                point.to_dict()
                for point in self.points
            ],
        }


def _trade_value(
    trade: Any,
    field: str,
    default: Any = None,
) -> Any:
    if isinstance(trade, dict):
        return trade.get(field, default)

    return getattr(trade, field, default)


def _enum_value(value: Any) -> str:
    if value is None:
        return ""

    return str(getattr(value, "value", value)).upper()


def _safe_float(
    value: Any,
    default: float = 0.0,
) -> float:
    try:
        if value is None:
            return default

        return float(value)

    except (TypeError, ValueError):
        return default


def build_equity_curve(
    trades: Iterable[Any],
    starting_balance: float = 5000.0,
    risk_percent: float = 0.5,
) -> EquityCurve:
    """
    Строит equity curve по закрытым сделкам.

    Риск рассчитывается как процент от текущего баланса:
        risk_money = current_balance * risk_percent / 100

    При результате +3R:
        profit = risk_money * 3

    При результате -1R:
        loss = risk_money * -1
    """

    if starting_balance <= 0:
        raise ValueError(
            "starting_balance должен быть больше 0"
        )

    if risk_percent <= 0:
        raise ValueError(
            "risk_percent должен быть больше 0"
        )

    closed_trades = [
        trade
        for trade in trades
        if _enum_value(
            _trade_value(trade, "status", "")
        ) == "CLOSED"
    ]

    balance = float(starting_balance)
    peak_balance = balance

    cumulative_r = 0.0
    peak_r = 0.0

    max_drawdown_money = 0.0
    max_drawdown_percent = 0.0
    max_drawdown_r = 0.0

    points: list[EquityPoint] = []

    for trade_number, trade in enumerate(
        closed_trades,
        start=1,
    ):
        result_r = _safe_float(
            _trade_value(trade, "result_r", 0.0)
        )

        balance_before = balance
        risk_money = (
            balance_before * risk_percent / 100.0
        )

        profit_money = risk_money * result_r
        balance += profit_money

        peak_balance = max(peak_balance, balance)

        drawdown_money = max(
            peak_balance - balance,
            0.0,
        )

        drawdown_percent = (
            drawdown_money / peak_balance * 100.0
            if peak_balance > 0
            else 0.0
        )

        cumulative_r += result_r
        peak_r = max(peak_r, cumulative_r)

        drawdown_r = max(
            peak_r - cumulative_r,
            0.0,
        )

        max_drawdown_money = max(
            max_drawdown_money,
            drawdown_money,
        )

        max_drawdown_percent = max(
            max_drawdown_percent,
            drawdown_percent,
        )

        max_drawdown_r = max(
            max_drawdown_r,
            drawdown_r,
        )

        close_time_value = _trade_value(
            trade,
            "close_time",
            None,
        )

        close_time = (
            int(close_time_value)
            if close_time_value is not None
            else None
        )

        points.append(
            EquityPoint(
                trade_number=trade_number,
                result_r=round(result_r, 4),
                cumulative_r=round(
                    cumulative_r,
                    4,
                ),
                balance_before=round(
                    balance_before,
                    2,
                ),
                risk_money=round(
                    risk_money,
                    2,
                ),
                profit_money=round(
                    profit_money,
                    2,
                ),
                balance_after=round(
                    balance,
                    2,
                ),
                peak_balance=round(
                    peak_balance,
                    2,
                ),
                drawdown_money=round(
                    drawdown_money,
                    2,
                ),
                drawdown_percent=round(
                    drawdown_percent,
                    4,
                ),
                close_time=close_time,
            )
        )

    net_profit = balance - starting_balance
    return_percent = (
        net_profit / starting_balance * 100.0
    )

    return EquityCurve(
        starting_balance=round(
            starting_balance,
            2,
        ),
        final_balance=round(
            balance,
            2,
        ),
        net_profit=round(
            net_profit,
            2,
        ),
        return_percent=round(
            return_percent,
            2,
        ),
        max_drawdown_money=round(
            max_drawdown_money,
            2,
        ),
        max_drawdown_percent=round(
            max_drawdown_percent,
            2,
        ),
        max_drawdown_r=round(
            max_drawdown_r,
            4,
        ),
        points=points,
    )


def print_equity_summary(
    equity: EquityCurve,
) -> None:
    print("\n============== EQUITY ==============")
    print(
        f"Starting Balance: "
        f"${equity.starting_balance:.2f}"
    )
    print(
        f"Final Balance: "
        f"${equity.final_balance:.2f}"
    )
    print(
        f"Net Profit: "
        f"${equity.net_profit:.2f}"
    )
    print(
        f"Return: "
        f"{equity.return_percent:.2f}%"
    )
    print(
        f"Max Drawdown: "
        f"${equity.max_drawdown_money:.2f} / "
        f"{equity.max_drawdown_percent:.2f}% / "
        f"{equity.max_drawdown_r:.2f}R"
    )
    print(
        f"Closed Trades: "
        f"{len(equity.points)}"
    )
    print("====================================\n")
