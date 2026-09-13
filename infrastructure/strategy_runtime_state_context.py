from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from core.context import StrategyContext
from infrastructure.multi_symbol_runtime_state_context import (
    MultiSymbolRuntimeStateCoordinator,
)
from infrastructure.runtime_state_store import (
    RuntimeStateLoadResult,
)


class StrategyRuntimeStateCoordinator:
    """
    Final production runtime namespace.

    Isolation hierarchy:
        root/
            strategies/
                <strategy_id>/
                    global_runtime_state.json
                    symbols/
                        EURUSD.json
                        XAUUSD.json

    Result:
    - account/runtime state of one strategy cannot overwrite another;
    - symbol state remains isolated inside each strategy;
    - existing MultiSymbolRuntimeStateCoordinator remains unchanged.
    """

    def __init__(
        self,
        root_dir: str | Path,
        *,
        strategy_id: str,
        create_backup: bool = True,
    ) -> None:
        self.strategy_id = (
            self._normalize_strategy_id(
                strategy_id
            )
        )

        safe_strategy_id = (
            self._safe_component(
                self.strategy_id
            )
        )

        self.root_dir = (
            Path(root_dir)
            / "strategies"
            / safe_strategy_id
        )

        self.delegate = (
            MultiSymbolRuntimeStateCoordinator(
                self.root_dir,
                create_backup=create_backup,
            )
        )

    def capture(
        self,
        context: StrategyContext,
    ) -> dict[str, Any]:
        state = self.delegate.capture(
            context
        )

        state[
            "strategy_id"
        ] = self.strategy_id

        return state

    def save_context(
        self,
        context: StrategyContext,
    ) -> dict[str, Any]:
        self._validate_context_strategy(
            context
        )

        state = self.delegate.save_context(
            context
        )

        state[
            "strategy_id"
        ] = self.strategy_id

        return state

    def load_state(
        self,
        *,
        symbol: str,
    ) -> RuntimeStateLoadResult:
        return self.delegate.load_state(
            symbol=symbol
        )

    def restore_context(
        self,
        context: StrategyContext,
        *,
        strict_symbol: bool = True,
    ) -> RuntimeStateLoadResult:
        self._validate_context_strategy(
            context
        )

        return self.delegate.restore_context(
            context,
            strict_symbol=strict_symbol,
        )

    def clear(
        self,
        *,
        symbol: str | None = None,
        clear_global: bool = False,
    ) -> None:
        self.delegate.clear(
            symbol=symbol,
            clear_global=clear_global,
        )

    def _validate_context_strategy(
        self,
        context: StrategyContext,
    ) -> None:
        strategy = getattr(
            context,
            "strategy",
            None,
        )

        metadata = getattr(
            strategy,
            "metadata",
            None,
        )

        context_strategy_id = getattr(
            metadata,
            "strategy_id",
            None,
        )

        if context_strategy_id is None:
            return

        normalized = str(
            context_strategy_id
        ).strip()

        if (
            normalized
            and normalized
            != self.strategy_id
        ):
            raise ValueError(
                "runtime_state_strategy_mismatch"
            )

    @staticmethod
    def _normalize_strategy_id(
        strategy_id: str,
    ) -> str:
        value = str(
            strategy_id
        ).strip()

        if not value:
            raise ValueError(
                "strategy_id is required"
            )

        return value

    @staticmethod
    def _safe_component(
        value: str,
    ) -> str:
        safe = re.sub(
            r"[^A-Za-z0-9._-]+",
            "_",
            value,
        ).strip("._")

        if not safe:
            raise ValueError(
                "strategy_id cannot produce "
                "empty path component"
            )

        return safe