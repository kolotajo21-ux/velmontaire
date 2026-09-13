from __future__ import annotations

from dataclasses import asdict, dataclass
from math import sqrt
from typing import Any, Iterable


@dataclass
class BacktestStatistics:
    total_trades: int
    closed_trades: int
    open_trades: int
    expired_orders: int
    cancelled_orders: int
    not_triggered_orders: int

    wins: int
    losses: int
    break_even: int

    win_rate: float
    loss_rate: float
    break_even_rate: float

    total_r: float
    average_r: float
    median_r: float
    average_win_r: float
    average_loss_r: float

    gross_profit_r: float
    gross_loss_r: float
    profit_factor: float

    expectancy_r: float
    payoff_ratio: float

    best_trade_r: float
    worst_trade_r: float

    max_consecutive_wins: int
    max_consecutive_losses: int

    max_drawdown_r: float
    max_drawdown_percent: float

    recovery_factor: float
    sharpe_ratio: float

    final_balance: float
    net_profit: float
    return_percent: float

    average_bars_in_trade: float
    average_bars_waited: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _average(values: list[float]) -> float:
    if not values:
        return 0.0

    return sum(values) / len(values)


def _median(values: list[float]) -> float:
    if not values:
        return 0.0

    ordered = sorted(values)
    middle = len(ordered) // 2

    if len(ordered) % 2 == 1:
        return ordered[middle]

    return (
        ordered[middle - 1] + ordered[middle]
    ) / 2.0


def _calculate_streaks(
    result_values: list[float],
) -> tuple[int, int]:
    max_wins = 0
    max_losses = 0
    current_wins = 0
    current_losses = 0

    for result_r in result_values:
        if result_r > 0:
            current_wins += 1
            current_losses = 0
            max_wins = max(max_wins, current_wins)

        elif result_r < 0:
            current_losses += 1
            current_wins = 0
            max_losses = max(max_losses, current_losses)

        else:
            current_wins = 0
            current_losses = 0

    return max_wins, max_losses


def _calculate_drawdown(
    result_values: list[float],
    starting_balance: float,
    risk_percent: float,
) -> tuple[float, float, float]:
    cumulative_r = 0.0
    peak_r = 0.0
    max_drawdown_r = 0.0

    balance = float(starting_balance)
    peak_balance = balance
    max_drawdown_percent = 0.0

    for result_r in result_values:
        cumulative_r += result_r
        peak_r = max(peak_r, cumulative_r)

        drawdown_r = peak_r - cumulative_r
        max_drawdown_r = max(
            max_drawdown_r,
            drawdown_r,
        )

        risk_money = balance * (risk_percent / 100.0)
        balance += risk_money * result_r

        peak_balance = max(peak_balance, balance)

        if peak_balance > 0:
            drawdown_percent = (
                (peak_balance - balance)
                / peak_balance
            ) * 100.0

            max_drawdown_percent = max(
                max_drawdown_percent,
                drawdown_percent,
            )

    return (
        max_drawdown_r,
        max_drawdown_percent,
        balance,
    )


def _calculate_sharpe_ratio(
    result_values: list[float],
) -> float:
    if len(result_values) < 2:
        return 0.0

    average = _average(result_values)

    variance = sum(
        (value - average) ** 2
        for value in result_values
    ) / (len(result_values) - 1)

    standard_deviation = sqrt(variance)

    if standard_deviation == 0:
        return 0.0

    return average / standard_deviation


def calculate_statistics(
    trades: Iterable[Any],
    starting_balance: float = 5000.0,
    risk_percent: float = 0.5,
) -> BacktestStatistics:
    if starting_balance <= 0:
        raise ValueError(
            "starting_balance должен быть больше 0"
        )

    if risk_percent <= 0:
        raise ValueError(
            "risk_percent должен быть больше 0"
        )

    trade_list = list(trades)

    statuses = [
        _enum_value(
            _trade_value(trade, "status", "")
        )
        for trade in trade_list
    ]

    outcomes = [
        _enum_value(
            _trade_value(trade, "outcome", "")
        )
        for trade in trade_list
    ]

    closed_trades = [
        trade
        for trade, status in zip(
            trade_list,
            statuses,
        )
        if status == "CLOSED"
    ]

    result_values = [
        _safe_float(
            _trade_value(trade, "result_r", 0.0)
        )
        for trade in closed_trades
    ]

    win_values = [
        value for value in result_values
        if value > 0
    ]

    loss_values = [
        value for value in result_values
        if value < 0
    ]

    zero_values = [
        value for value in result_values
        if value == 0
    ]

    wins = len(win_values)
    losses = len(loss_values)
    break_even = len(zero_values)
    closed_count = len(closed_trades)

    win_rate = (
        wins / closed_count * 100.0
        if closed_count else 0.0
    )

    loss_rate = (
        losses / closed_count * 100.0
        if closed_count else 0.0
    )

    break_even_rate = (
        break_even / closed_count * 100.0
        if closed_count else 0.0
    )

    gross_profit_r = sum(win_values)
    gross_loss_r = abs(sum(loss_values))

    if gross_loss_r > 0:
        profit_factor = (
            gross_profit_r / gross_loss_r
        )
    elif gross_profit_r > 0:
        profit_factor = float("inf")
    else:
        profit_factor = 0.0

    average_win_r = _average(win_values)
    average_loss_r = _average(
        [abs(value) for value in loss_values]
    )

    if average_loss_r > 0:
        payoff_ratio = (
            average_win_r / average_loss_r
        )
    elif average_win_r > 0:
        payoff_ratio = float("inf")
    else:
        payoff_ratio = 0.0

    total_r = sum(result_values)
    expectancy_r = _average(result_values)

    best_trade_r = (
        max(result_values)
        if result_values else 0.0
    )

    worst_trade_r = (
        min(result_values)
        if result_values else 0.0
    )

    max_wins, max_losses = _calculate_streaks(
        result_values
    )

    (
        max_drawdown_r,
        max_drawdown_percent,
        final_balance,
    ) = _calculate_drawdown(
        result_values=result_values,
        starting_balance=starting_balance,
        risk_percent=risk_percent,
    )

    net_profit = final_balance - starting_balance
    return_percent = (
        net_profit / starting_balance * 100.0
    )

    recovery_factor = (
        return_percent / max_drawdown_percent
        if max_drawdown_percent > 0
        else 0.0
    )

    average_bars_in_trade = _average(
        [
            _safe_float(
                _trade_value(
                    trade,
                    "bars_in_trade",
                    0,
                )
            )
            for trade in closed_trades
        ]
    )

    average_bars_waited = _average(
        [
            _safe_float(
                _trade_value(
                    trade,
                    "bars_waited",
                    0,
                )
            )
            for trade in trade_list
        ]
    )

    return BacktestStatistics(
        total_trades=len(trade_list),
        closed_trades=closed_count,
        open_trades=statuses.count("OPEN"),
        expired_orders=statuses.count("EXPIRED"),
        cancelled_orders=statuses.count("CANCELLED"),
        not_triggered_orders=outcomes.count(
            "NOT_TRIGGERED"
        ),
        wins=wins,
        losses=losses,
        break_even=break_even,
        win_rate=round(win_rate, 2),
        loss_rate=round(loss_rate, 2),
        break_even_rate=round(
            break_even_rate,
            2,
        ),
        total_r=round(total_r, 4),
        average_r=round(
            _average(result_values),
            4,
        ),
        median_r=round(
            _median(result_values),
            4,
        ),
        average_win_r=round(
            average_win_r,
            4,
        ),
        average_loss_r=round(
            average_loss_r,
            4,
        ),
        gross_profit_r=round(
            gross_profit_r,
            4,
        ),
        gross_loss_r=round(
            gross_loss_r,
            4,
        ),
        profit_factor=(
            round(profit_factor, 4)
            if profit_factor != float("inf")
            else float("inf")
        ),
        expectancy_r=round(
            expectancy_r,
            4,
        ),
        payoff_ratio=(
            round(payoff_ratio, 4)
            if payoff_ratio != float("inf")
            else float("inf")
        ),
        best_trade_r=round(
            best_trade_r,
            4,
        ),
        worst_trade_r=round(
            worst_trade_r,
            4,
        ),
        max_consecutive_wins=max_wins,
        max_consecutive_losses=max_losses,
        max_drawdown_r=round(
            max_drawdown_r,
            4,
        ),
        max_drawdown_percent=round(
            max_drawdown_percent,
            2,
        ),
        recovery_factor=round(
            recovery_factor,
            4,
        ),
        sharpe_ratio=round(
            _calculate_sharpe_ratio(
                result_values
            ),
            4,
        ),
        final_balance=round(
            final_balance,
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
        average_bars_in_trade=round(
            average_bars_in_trade,
            2,
        ),
        average_bars_waited=round(
            average_bars_waited,
            2,
        ),
    )


def print_statistics(
    statistics: BacktestStatistics,
) -> None:
    profit_factor_text = (
        "∞"
        if statistics.profit_factor == float("inf")
        else f"{statistics.profit_factor:.2f}"
    )

    payoff_ratio_text = (
        "∞"
        if statistics.payoff_ratio == float("inf")
        else f"{statistics.payoff_ratio:.2f}"
    )

    print("\n========== BACKTEST STATISTICS ==========")
    print(f"Total trades: {statistics.total_trades}")
    print(f"Closed trades: {statistics.closed_trades}")
    print(f"Wins: {statistics.wins}")
    print(f"Losses: {statistics.losses}")
    print(f"Break Even: {statistics.break_even}")
    print(f"Win Rate: {statistics.win_rate:.2f}%")
    print(f"Profit Factor: {profit_factor_text}")
    print(f"Payoff Ratio: {payoff_ratio_text}")
    print(f"Expectancy: {statistics.expectancy_r:.2f}R")
    print(f"Total R: {statistics.total_r:.2f}R")
    print(
        f"Max Drawdown: "
        f"{statistics.max_drawdown_r:.2f}R / "
        f"{statistics.max_drawdown_percent:.2f}%"
    )
    print(
        f"Final Balance: "
        f"${statistics.final_balance:.2f}"
    )
    print(
        f"Net Profit: "
        f"${statistics.net_profit:.2f} "
        f"({statistics.return_percent:.2f}%)"
    )
    print(
        f"Max Win Streak: "
        f"{statistics.max_consecutive_wins}"
    )
    print(
        f"Max Loss Streak: "
        f"{statistics.max_consecutive_losses}"
    )
    print(
        f"Sharpe Ratio: "
        f"{statistics.sharpe_ratio:.2f}"
    )
    print("=========================================\n")
