from __future__ import annotations

from typing import Any

from core.context import StrategyContext
from safety.prop_account_state_tracker import (
    PropAccountState,
    PropAccountStateTracker,
)


class PropAccountStateContextBuilder:
    """
    Builds prop_account_state directly from StrategyContext.

    Expected context data:
    - account:
        {
            "starting_balance": ...,
            "balance": ...,
            "equity": ...,
        }
    - closed_trades_today: list[dict]
    - execution_snapshot:
        {
            "positions": [...]
        }
    - trading_day_state: optional persisted state

    Result:
    - context["prop_account_state"]
    - context["trading_day_state"]
    """

    def __init__(
        self,
        tracker: PropAccountStateTracker | None = None,
    ) -> None:
        self.tracker = (
            tracker
            if tracker is not None
            else PropAccountStateTracker()
        )

    def build(
        self,
        context: StrategyContext,
    ) -> PropAccountState:
        account = context.get(
            "account"
        )

        if not isinstance(
            account,
            dict,
        ):
            raise ValueError(
                "account_state_missing"
            )

        starting_balance = self._required_float(
            account,
            "starting_balance",
        )

        balance = self._required_float(
            account,
            "balance",
        )

        equity = self._required_float(
            account,
            "equity",
        )

        closed_trades = context.get(
            "closed_trades_today"
        )

        if closed_trades is None:
            closed_trades = []

        if not isinstance(
            closed_trades,
            list,
        ):
            raise ValueError(
                "closed_trades_today_invalid"
            )

        execution_snapshot = context.get(
            "execution_snapshot"
        )

        open_positions: list[
            dict[str, Any]
        ] = []

        if isinstance(
            execution_snapshot,
            dict,
        ):
            positions = execution_snapshot.get(
                "positions",
                [],
            )

            if isinstance(
                positions,
                list,
            ):
                open_positions = [
                    dict(position)
                    for position in positions
                    if isinstance(
                        position,
                        dict,
                    )
                ]

        previous_day_state = context.get(
            "trading_day_state"
        )

        if not isinstance(
            previous_day_state,
            dict,
        ):
            previous_day_state = None

        try:
            timestamp = int(
                context.current_time
            )
        except (
            TypeError,
            ValueError,
        ) as exc:
            raise ValueError(
                "current_time_invalid"
            ) from exc

        state = self.tracker.build(
            timestamp=timestamp,
            starting_balance=starting_balance,
            balance=balance,
            equity=equity,
            closed_trades_today=closed_trades,
            open_positions=open_positions,
            previous_trading_day_state=(
                previous_day_state
            ),
        )

        data = state.to_dict()

        trading_day_state = (
            self.tracker
            .trading_day_snapshot()
        )

        context.put(
            "prop_account_state",
            data,
        )

        context.trade[
            "prop_account_state"
        ] = data

        if isinstance(
            trading_day_state,
            dict,
        ):
            context.put(
                "trading_day_state",
                trading_day_state,
            )

            context.trade[
                "trading_day_state"
            ] = trading_day_state

        return state

    @staticmethod
    def _required_float(
        data: dict[str, Any],
        key: str,
    ) -> float:
        value = data.get(
            key
        )

        if value is None:
            raise ValueError(
                f"{key}_missing"
            )

        try:
            number = float(
                value
            )
        except (
            TypeError,
            ValueError,
        ) as exc:
            raise ValueError(
                f"{key}_invalid"
            ) from exc

        if number <= 0:
            raise ValueError(
                f"{key}_invalid"
            )

        return number