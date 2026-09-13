from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from core.context import StrategyContext
from infrastructure.runtime_state_store import (
    RuntimeStateLoadResult,
    RuntimeStateStore,
)


class MultiSymbolRuntimeStateCoordinator:
    """
    Multi-symbol persistent runtime coordinator.

    Global/account state:
    - trading_day_state
    - prop_account_state

    Symbol-scoped state:
    - execution_snapshot
    - execution_recovery_plan
    - new_entries_allowed

    Storage layout:
        <root>/
            global_runtime_state.json
            symbols/
                EURUSD.json
                GBPUSD.json
                XAUUSD.json

    This prevents one symbol from overwriting another symbol's
    execution/recovery state while keeping account-level prop state shared.
    """

    GLOBAL_STATE_KEYS = (
        "trading_day_state",
        "prop_account_state",
    )

    SYMBOL_STATE_KEYS = (
        "execution_snapshot",
        "execution_recovery_plan",
        "new_entries_allowed",
    )

    def __init__(
        self,
        root_dir: str | Path,
        *,
        create_backup: bool = True,
    ) -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.symbols_dir = (
            self.root_dir / "symbols"
        )
        self.symbols_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.create_backup = bool(
            create_backup
        )

        self.global_store = RuntimeStateStore(
            self.root_dir
            / "global_runtime_state.json",
            create_backup=self.create_backup,
        )

        self._symbol_stores: dict[
            str,
            RuntimeStateStore,
        ] = {}

    def capture(
        self,
        context: StrategyContext,
    ) -> dict[str, Any]:
        """
        Returns a combined diagnostic view.
        It is not the on-disk format.
        """
        state: dict[str, Any] = {
            "symbol": context.symbol,
            "current_time": int(
                context.current_time
            ),
            "global": {},
            "symbol_state": {},
        }

        for key in self.GLOBAL_STATE_KEYS:
            value = context.get(key)

            if value is not None:
                state["global"][key] = value

        for key in self.SYMBOL_STATE_KEYS:
            value = context.get(key)

            if value is not None:
                state["symbol_state"][key] = value

        return state

    def save_context(
        self,
        context: StrategyContext,
    ) -> dict[str, Any]:
        captured = self.capture(
            context
        )

        global_state = {
            "current_time": int(
                context.current_time
            ),
            **captured["global"],
        }

        # Save shared account state only when there is something
        # meaningful to persist.
        if captured["global"]:
            self.global_store.save(
                global_state
            )

        symbol = str(
            context.symbol
        )

        symbol_state = {
            "symbol": symbol,
            "current_time": int(
                context.current_time
            ),
            **captured["symbol_state"],
        }

        self._store_for_symbol(
            symbol
        ).save(
            symbol_state
        )

        return captured

    def load_state(
        self,
        *,
        symbol: str,
    ) -> RuntimeStateLoadResult:
        """
        Returns the merged state for one symbol.
        """
        global_result = (
            self.global_store.load()
        )

        if not global_result.success:
            return global_result

        symbol_result = (
            self._store_for_symbol(
                symbol
            ).load()
        )

        if not symbol_result.success:
            return symbol_result

        merged: dict[str, Any] = {
            "symbol": str(symbol),
        }

        if isinstance(
            global_result.state,
            dict,
        ):
            for key in self.GLOBAL_STATE_KEYS:
                if key in global_result.state:
                    merged[key] = (
                        global_result.state[key]
                    )

        if isinstance(
            symbol_result.state,
            dict,
        ):
            for key in self.SYMBOL_STATE_KEYS:
                if key in symbol_result.state:
                    merged[key] = (
                        symbol_result.state[key]
                    )

            if (
                "current_time"
                in symbol_result.state
            ):
                merged["current_time"] = (
                    symbol_result.state[
                        "current_time"
                    ]
                )

        if (
            len(merged) == 1
            and global_result.state is None
            and symbol_result.state is None
        ):
            merged_state = None
        else:
            merged_state = merged

        return RuntimeStateLoadResult(
            success=True,
            state=merged_state,
            error=None,
            recovered_from_backup=bool(
                global_result.recovered_from_backup
                or symbol_result.recovered_from_backup
            ),
        )

    def restore_context(
        self,
        context: StrategyContext,
        *,
        strict_symbol: bool = True,
    ) -> RuntimeStateLoadResult:
        # strict_symbol is naturally satisfied because every symbol
        # has its own isolated state file.
        del strict_symbol

        symbol = str(
            context.symbol
        )

        result = self.load_state(
            symbol=symbol
        )

        if not result.success:
            return result

        if result.state is None:
            return result

        state = result.state

        saved_symbol = state.get(
            "symbol"
        )

        if (
            saved_symbol is not None
            and str(saved_symbol)
            != symbol
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

        for key in (
            *self.GLOBAL_STATE_KEYS,
            *self.SYMBOL_STATE_KEYS,
        ):
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

        context.trade[
            "runtime_state_recovered_from_backup"
        ] = bool(
            result.recovered_from_backup
        )

        return result

    def clear(
        self,
        *,
        symbol: str | None = None,
        clear_global: bool = False,
    ) -> None:
        if symbol is not None:
            self._store_for_symbol(
                symbol
            ).clear()

        if clear_global:
            self.global_store.clear()

        if (
            symbol is None
            and not clear_global
        ):
            for store in list(
                self._symbol_stores.values()
            ):
                store.clear()

            for path in self.symbols_dir.glob(
                "*.json"
            ):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass

    def _store_for_symbol(
        self,
        symbol: str,
    ) -> RuntimeStateStore:
        normalized = str(
            symbol
        ).strip()

        if not normalized:
            raise ValueError(
                "symbol must not be empty"
            )

        if normalized in self._symbol_stores:
            return self._symbol_stores[
                normalized
            ]

        safe_name = re.sub(
            r"[^A-Za-z0-9._-]+",
            "_",
            normalized,
        )

        store = RuntimeStateStore(
            self.symbols_dir
            / f"{safe_name}.json",
            create_backup=self.create_backup,
        )

        self._symbol_stores[
            normalized
        ] = store

        return store