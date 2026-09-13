from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from safety.trading_day_manager import (
    TradingDayManager,
    TradingDayState,
)


@dataclass(slots=True)
class PropAccountState:
    starting_balance: float
    balance: float
    equity: float

    trading_day: str
    day_start_balance: float
    day_start_equity: float

    daily_closed_pnl: float = 0.0
    daily_floating_pnl: float = 0.0
    daily_risk_used_percent: float = 0.0
    trades_today: int = 0

    day_changed: bool = False

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    @property
    def daily_total_pnl(self) -> float:
        return (
            self.daily_closed_pnl
            + self.daily_floating_pnl
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "starting_balance": (
                self.starting_balance
            ),
            "balance": self.balance,
            "equity": self.equity,

            "trading_day": self.trading_day,
            "day_start_balance": (
                self.day_start_balance
            ),
            "day_start_equity": (
                self.day_start_equity
            ),

            "daily_closed_pnl": (
                self.daily_closed_pnl
            ),
            "daily_floating_pnl": (
                self.daily_floating_pnl
            ),
            "daily_total_pnl": (
                self.daily_total_pnl
            ),
            "daily_risk_used_percent": (
                self.daily_risk_used_percent
            ),
            "trades_today": (
                self.trades_today
            ),

            "day_changed": (
                self.day_changed
            ),

            "metadata": dict(
                self.metadata
            ),
        }


class PropAccountStateTracker:
    """
    Builds prop-account state with automatic trading-day handling.

    Responsibilities:
    - preserve day-start balance/equity inside the same trading day;
    - restore persisted trading-day state after bot restart;
    - reset daily closed PnL, daily risk and trade count on a new day;
    - keep floating PnL from currently open positions.
    """

    def __init__(
        self,
        *,
        trading_day_manager: (
            TradingDayManager | None
        ) = None,
    ) -> None:
        self.trading_day_manager = (
            trading_day_manager
            if trading_day_manager
            is not None
            else TradingDayManager()
        )

    def build(
        self,
        *,
        timestamp: int,
        starting_balance: float,
        balance: float,
        equity: float,
        closed_trades_today: (
            list[dict[str, Any]] | None
        ) = None,
        open_positions: (
            list[dict[str, Any]] | None
        ) = None,
        previous_trading_day_state: (
            Mapping[str, Any] | None
        ) = None,
    ) -> PropAccountState:
        self._validate_money(
            starting_balance=(
                starting_balance
            ),
            balance=balance,
            equity=equity,
        )

        day_state = (
            self.trading_day_manager
            .update(
                timestamp=timestamp,
                account={
                    "balance": balance,
                    "equity": equity,
                },
                previous_state=(
                    previous_trading_day_state
                ),
            )
        )

        closed_trades = (
            closed_trades_today or []
        )

        positions = (
            open_positions or []
        )

        # On a genuinely new trading day,
        # yesterday's closed trades must not carry over.
        if day_state.day_changed:
            closed_trades = []

        daily_closed_pnl = sum(
            self._number(
                trade.get(
                    "net_pnl",
                    trade.get(
                        "profit",
                        0.0,
                    ),
                )
            )
            for trade in closed_trades
        )

        daily_floating_pnl = sum(
            self._number(
                position.get(
                    "profit",
                    position.get(
                        "floating_pnl",
                        0.0,
                    ),
                )
            )
            for position in positions
        )

        daily_risk_used_percent = sum(
            max(
                0.0,
                self._number(
                    trade.get(
                        "risk_percent",
                        0.0,
                    )
                ),
            )
            for trade in closed_trades
        )

        trades_today = len(
            closed_trades
        )

        return PropAccountState(
            starting_balance=float(
                starting_balance
            ),
            balance=float(
                balance
            ),
            equity=float(
                equity
            ),

            trading_day=(
                day_state.trading_day
            ),
            day_start_balance=(
                day_state.day_start_balance
            ),
            day_start_equity=(
                day_state.day_start_equity
            ),

            daily_closed_pnl=(
                daily_closed_pnl
            ),
            daily_floating_pnl=(
                daily_floating_pnl
            ),
            daily_risk_used_percent=(
                daily_risk_used_percent
            ),
            trades_today=(
                trades_today
            ),

            day_changed=(
                day_state.day_changed
            ),

            metadata={
                "closed_trades_count": (
                    len(closed_trades)
                ),
                "open_positions_count": (
                    len(positions)
                ),
                "trading_day_state": (
                    day_state.to_dict()
                ),
            },
        )

    def trading_day_snapshot(
        self,
    ) -> dict[str, Any] | None:
        return (
            self.trading_day_manager
            .snapshot()
        )

    def restore_trading_day(
        self,
        state: Mapping[str, Any],
    ) -> None:
        self.trading_day_manager.restore(
            state
        )

    @staticmethod
    def _validate_money(
        *,
        starting_balance: float,
        balance: float,
        equity: float,
    ) -> None:
        values = {
            "starting_balance": (
                starting_balance
            ),
            "balance": balance,
            "equity": equity,
        }

        for name, value in values.items():
            try:
                number = float(
                    value
                )
            except (
                TypeError,
                ValueError,
            ) as exc:
                raise ValueError(
                    f"{name} must be numeric"
                ) from exc

            if number <= 0:
                raise ValueError(
                    f"{name} must be > 0"
                )

    @staticmethod
    def _number(
        value: Any,
    ) -> float:
        try:
            return float(
                value
            )
        except (
            TypeError,
            ValueError,
        ):
            return 0.0