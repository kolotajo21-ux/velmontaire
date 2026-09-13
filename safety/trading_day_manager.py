from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping


@dataclass(frozen=True)
class TradingDayState:
    trading_day: str
    day_start_balance: float
    day_start_equity: float
    current_balance: float
    current_equity: float
    day_changed: bool
    initialized: bool
    timestamp: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "trading_day": self.trading_day,
            "day_start_balance": self.day_start_balance,
            "day_start_equity": self.day_start_equity,
            "current_balance": self.current_balance,
            "current_equity": self.current_equity,
            "day_changed": self.day_changed,
            "initialized": self.initialized,
            "timestamp": self.timestamp,
        }


class TradingDayManager:
    """
    Tracks the current trading day and survives bot restarts.

    Important behavior:
    - same-day restart restores the original baseline;
    - restart on a NEW day must report day_changed=True;
    - daily reset therefore happens exactly once across the boundary.
    """

    def __init__(self) -> None:
        self._state: TradingDayState | None = None

    @staticmethod
    def _trading_day_from_timestamp(
        timestamp: int,
    ) -> str:
        dt = datetime.fromtimestamp(
            timestamp,
            tz=timezone.utc,
        )
        return dt.date().isoformat()

    @staticmethod
    def _read_number(
        account: Mapping[str, Any],
        *keys: str,
    ) -> float:
        for key in keys:
            value = account.get(key)
            if value is not None:
                return float(value)

        raise ValueError(
            "Account data is missing required field. "
            f"Expected one of: {keys}"
        )

    def update(
        self,
        *,
        timestamp: int,
        account: Mapping[str, Any],
        previous_state: Mapping[str, Any] | None = None,
    ) -> TradingDayState:
        trading_day = (
            self._trading_day_from_timestamp(
                timestamp
            )
        )

        balance = self._read_number(
            account,
            "balance",
            "account_balance",
        )

        equity = self._read_number(
            account,
            "equity",
            "account_equity",
        )

        # ---------------------------------------------------------
        # Restore persisted state after restart.
        # ---------------------------------------------------------
        if (
            self._state is None
            and previous_state is not None
        ):
            previous_day = str(
                previous_state.get(
                    "trading_day",
                    "",
                )
            )

            # Restart inside the SAME trading day.
            if previous_day == trading_day:
                self._state = TradingDayState(
                    trading_day=previous_day,
                    day_start_balance=float(
                        previous_state.get(
                            "day_start_balance",
                            balance,
                        )
                    ),
                    day_start_equity=float(
                        previous_state.get(
                            "day_start_equity",
                            equity,
                        )
                    ),
                    current_balance=balance,
                    current_equity=equity,
                    day_changed=False,
                    initialized=True,
                    timestamp=timestamp,
                )
                return self._state

            # Restart AFTER the trading-day boundary.
            # This is NOT a first initialization:
            # a valid previous day existed, therefore we must emit
            # day_changed=True so daily counters are reset.
            if previous_day:
                self._state = TradingDayState(
                    trading_day=trading_day,
                    day_start_balance=balance,
                    day_start_equity=equity,
                    current_balance=balance,
                    current_equity=equity,
                    day_changed=True,
                    initialized=True,
                    timestamp=timestamp,
                )
                return self._state

        # ---------------------------------------------------------
        # Genuine first initialization.
        # ---------------------------------------------------------
        if self._state is None:
            self._state = TradingDayState(
                trading_day=trading_day,
                day_start_balance=balance,
                day_start_equity=equity,
                current_balance=balance,
                current_equity=equity,
                day_changed=False,
                initialized=True,
                timestamp=timestamp,
            )
            return self._state

        # ---------------------------------------------------------
        # Same trading day.
        # ---------------------------------------------------------
        if self._state.trading_day == trading_day:
            self._state = TradingDayState(
                trading_day=trading_day,
                day_start_balance=(
                    self._state.day_start_balance
                ),
                day_start_equity=(
                    self._state.day_start_equity
                ),
                current_balance=balance,
                current_equity=equity,
                day_changed=False,
                initialized=True,
                timestamp=timestamp,
            )
            return self._state

        # ---------------------------------------------------------
        # Normal in-process transition to a new trading day.
        # ---------------------------------------------------------
        self._state = TradingDayState(
            trading_day=trading_day,
            day_start_balance=balance,
            day_start_equity=equity,
            current_balance=balance,
            current_equity=equity,
            day_changed=True,
            initialized=True,
            timestamp=timestamp,
        )

        return self._state

    def snapshot(
        self,
    ) -> dict[str, Any] | None:
        if self._state is None:
            return None
        return self._state.to_dict()

    def restore(
        self,
        state: Mapping[str, Any],
    ) -> None:
        self._state = TradingDayState(
            trading_day=str(
                state["trading_day"]
            ),
            day_start_balance=float(
                state["day_start_balance"]
            ),
            day_start_equity=float(
                state["day_start_equity"]
            ),
            current_balance=float(
                state.get(
                    "current_balance",
                    state["day_start_balance"],
                )
            ),
            current_equity=float(
                state.get(
                    "current_equity",
                    state["day_start_equity"],
                )
            ),
            day_changed=False,
            initialized=True,
            timestamp=int(
                state.get(
                    "timestamp",
                    0,
                )
            ),
        )

    @property
    def state(
        self,
    ) -> TradingDayState | None:
        return self._state