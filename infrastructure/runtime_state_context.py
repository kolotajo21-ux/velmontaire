from __future__ import annotations

from typing import Any

from core.context import StrategyContext
from infrastructure.runtime_state_store import (
    RuntimeStateLoadResult,
    RuntimeStateStore,
)


class RuntimeStateCoordinator:
    """
    Coordinates persistent runtime state with StrategyContext.

    Persisted keys:
    - trading_day_state
    - prop_account_state
    - execution_snapshot
    - execution_recovery_plan
    - new_entries_allowed

    This class does not send or modify broker orders.
    """

    STATE_KEYS = (
        "trading_day_state",
        "prop_account_state",
        "execution_snapshot",
        "execution_recovery_plan",
        "new_entries_allowed",
    )

    def __init__(
        self,
        store: RuntimeStateStore,
    ) -> None:
        self.store = store

    def capture(
        self,
        context: StrategyContext,
    ) -> dict[str, Any]:
        state: dict[str, Any] = {
            "symbol": context.symbol,
            "current_time": int(
                context.current_time
            ),
        }

        for key in self.STATE_KEYS:
            value = context.get(
                key
            )

            if value is not None:
                state[key] = value

        return state

    def save_context(
        self,
        context: StrategyContext,
    ) -> dict[str, Any]:
        state = self.capture(
            context
        )

        self.store.save(
            state
        )

        return state

    def load_state(
        self,
    ) -> RuntimeStateLoadResult:
        return self.store.load()

    def restore_context(
        self,
        context: StrategyContext,
        *,
        strict_symbol: bool = True,
    ) -> RuntimeStateLoadResult:
        result = self.store.load()

        if not result.success:
            return result

        if result.state is None:
            return result

        state = result.state

        saved_symbol = state.get(
            "symbol"
        )

        if (
            strict_symbol
            and saved_symbol is not None
            and str(saved_symbol)
            != str(context.symbol)
        ):
            return RuntimeStateLoadResult(
                success=False,
                state=None,
                error=(
                    "runtime_state_symbol_mismatch"
                ),
                recovered_from_backup=(
                    result.recovered_from_backup
                ),
            )

        for key in self.STATE_KEYS:
            if key not in state:
                continue

            value = state[key]

            context.put(
                key,
                value,
            )

            context.trade[
                key
            ] = value

        context.put(
            "runtime_state_restored",
            True,
        )

        context.trade[
            "runtime_state_restored"
        ] = True

        context.put(
            "runtime_state_recovered_from_backup",
            bool(
                result.recovered_from_backup
            ),
        )

        return result

    def clear(
        self,
    ) -> None:
        self.store.clear()