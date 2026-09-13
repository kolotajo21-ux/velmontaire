from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .strategy import (
    ModuleRole,
    StrategyDefinition,
)


@dataclass(slots=True)
class ModuleExecutionResult:
    role: ModuleRole
    provider: str

    success: bool = True
    passed: bool = True

    data: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role.value,
            "provider": self.provider,
            "success": bool(self.success),
            "passed": bool(self.passed),
            "data": dict(self.data),
            "events": [dict(event) for event in self.events],
            "diagnostics": dict(self.diagnostics),
            "error": self.error,
        }


@dataclass(slots=True)
class StrategyContext:
    strategy: StrategyDefinition
    symbol: str
    current_time: int

    rates_by_timeframe: dict[str, Any] = field(default_factory=dict)
    market: dict[str, Any] = field(default_factory=dict)
    rates_by_symbol: dict[str, dict[str, Any]] = field(default_factory=dict)
    market_by_symbol: dict[str, dict[str, Any]] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)

    module_results: dict[str, ModuleExecutionResult] = field(
        default_factory=dict
    )

    events: list[dict[str, Any]] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    trade: dict[str, Any] = field(default_factory=dict)
    statistics: dict[str, Any] = field(default_factory=dict)

    def get_rates(self, timeframe: str) -> Any:
        target = str(timeframe).upper()

        for key, value in self.rates_by_timeframe.items():
            if str(key).upper() == target:
                return value

        return []

    def get_symbol_rates(
        self,
        symbol: str,
        timeframe: str,
    ) -> Any:
        target_symbol = str(symbol or "").strip().upper()
        target_timeframe = str(timeframe or "").strip().upper()

        for symbol_key, timeframe_map in self.rates_by_symbol.items():
            if str(symbol_key).strip().upper() != target_symbol:
                continue
            if not isinstance(timeframe_map, dict):
                return []
            for timeframe_key, rates in timeframe_map.items():
                if str(timeframe_key).strip().upper() == target_timeframe:
                    return rates
        return []

    def set_result(self, result: ModuleExecutionResult) -> None:
        key = self._result_key(
            result.role,
            result.provider,
        )

        self.module_results[key] = result

        if result.events:
            self.events.extend(result.events)

        if not result.success and result.error:
            self.errors[key] = result.error

    def get_result(
        self,
        *,
        role: ModuleRole,
        provider: str | None = None,
    ) -> ModuleExecutionResult | None:
        if provider is not None:
            return self.module_results.get(
                self._result_key(
                    role,
                    provider,
                )
            )

        candidates = [
            result
            for result in self.module_results.values()
            if result.role == role
        ]

        if not candidates:
            return None

        return candidates[-1]

    def results_by_role(
        self,
        role: ModuleRole,
    ) -> list[ModuleExecutionResult]:
        return [
            result
            for result in self.module_results.values()
            if result.role == role
        ]

    def has_succeeded(
        self,
        role: ModuleRole,
    ) -> bool:
        """
        Dependency-level check:
        at least one module of this role executed successfully.

        success != passed:
        - success means module worked correctly;
        - passed means module's trading condition is satisfied.
        """
        results = self.results_by_role(role)

        if not results:
            return False

        return any(
            result.success
            for result in results
        )

    def has_passed(
        self,
        role: ModuleRole,
    ) -> bool:
        """
        Signal/filter-level check:
        at least one module of this role passed its trading condition.
        """
        results = self.results_by_role(role)

        if not results:
            return False

        return any(
            result.success and result.passed
            for result in results
        )

    def put(self, key: str, value: Any) -> None:
        self.state[str(key)] = value

    def get(
        self,
        key: str,
        default: Any = None,
    ) -> Any:
        return self.state.get(
            str(key),
            default,
        )

    def add_event(
        self,
        event: dict[str, Any],
    ) -> None:
        self.events.append(
            dict(event)
        )

    def add_error(
        self,
        key: str,
        message: str,
    ) -> None:
        self.errors[str(key)] = str(message)

    def is_valid(self) -> bool:
        return not bool(self.errors)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy.to_dict(),
            "symbol": self.symbol,
            "current_time": int(self.current_time),
            "market": dict(self.market),
            "available_context_symbols": sorted(
                str(symbol).strip().upper()
                for symbol in self.rates_by_symbol
            ),
            "state": dict(self.state),
            "module_results": {
                key: result.to_dict()
                for key, result in self.module_results.items()
            },
            "events": [
                dict(event)
                for event in self.events
            ],
            "errors": dict(self.errors),
            "diagnostics": dict(self.diagnostics),
            "trade": dict(self.trade),
            "statistics": dict(self.statistics),
        }

    @staticmethod
    def _result_key(
        role: ModuleRole,
        provider: str,
    ) -> str:
        return (
            f"{role.value}:"
            f"{str(provider).strip()}"
        )
