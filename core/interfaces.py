from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

from .context import (
    ModuleExecutionResult,
    StrategyContext,
)
from .strategy import (
    ModuleRole,
    StrategyModuleDefinition,
)


@dataclass(slots=True)
class ModuleCapabilities:
    names: set[str] = field(default_factory=set)
    metadata: dict[str, Any] = field(default_factory=dict)

    def supports(self, capability: str) -> bool:
        target = str(capability).strip().lower()

        return any(
            str(name).strip().lower() == target
            for name in self.names
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "names": sorted(
                str(name)
                for name in self.names
            ),
            "metadata": dict(self.metadata),
        }


class StrategyModule(ABC):
    """
    Базовый интерфейс любого модуля платформы.

    ВАЖНО:
    dependency = модуль-зависимость должен УСПЕШНО исполниться,
    но не обязан вернуть passed=True.
    """

    provider: ClassVar[str] = "base"
    role: ClassVar[ModuleRole] = ModuleRole.MARKET
    version: ClassVar[str] = "1.0.0"
    capabilities: ClassVar[tuple[str, ...]] = ()
    dependencies: ClassVar[tuple[ModuleRole, ...]] = ()

    def __init__(
        self,
        definition: StrategyModuleDefinition | None = None,
    ) -> None:
        self.definition = (
            definition
            if definition is not None
            else StrategyModuleDefinition(
                role=self.role,
                provider=self.provider,
            )
        )

        self._validate_definition()

    @abstractmethod
    def execute(
        self,
        context: StrategyContext,
    ) -> ModuleExecutionResult:
        raise NotImplementedError

    def validate_context(
        self,
        context: StrategyContext,
    ) -> tuple[bool, str | None]:
        for dependency in self.dependencies:
            if not context.has_succeeded(
                dependency
            ):
                return (
                    False,
                    (
                        "dependency_not_succeeded:"
                        f"{dependency.value}"
                    ),
                )

        return (
            True,
            None,
        )

    def run(
        self,
        context: StrategyContext,
    ) -> ModuleExecutionResult:
        valid, reason = self.validate_context(
            context
        )

        if not valid:
            return self.failure(
                error=(
                    reason
                    or "context_invalid"
                ),
                passed=False,
            )

        try:
            result = self.execute(
                context
            )

        except Exception as exc:
            return self.failure(
                error=(
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),
                passed=False,
            )

        if not isinstance(
            result,
            ModuleExecutionResult,
        ):
            return self.failure(
                error=(
                    "module_execute_must_return_"
                    "ModuleExecutionResult"
                ),
                passed=False,
            )

        return result

    def success(
        self,
        *,
        passed: bool = True,
        data: dict[str, Any] | None = None,
        events: list[dict[str, Any]] | None = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> ModuleExecutionResult:
        return ModuleExecutionResult(
            role=self.role,
            provider=self.provider,
            success=True,
            passed=bool(passed),
            data=dict(data or {}),
            events=[
                dict(event)
                for event in (events or [])
            ],
            diagnostics=dict(
                diagnostics or {}
            ),
            error=None,
        )

    def failure(
        self,
        *,
        error: str,
        passed: bool = False,
        data: dict[str, Any] | None = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> ModuleExecutionResult:
        return ModuleExecutionResult(
            role=self.role,
            provider=self.provider,
            success=False,
            passed=bool(passed),
            data=dict(data or {}),
            events=[],
            diagnostics=dict(
                diagnostics or {}
            ),
            error=str(error),
        )

    def capability_set(
        self,
    ) -> ModuleCapabilities:
        return ModuleCapabilities(
            names=set(self.capabilities),
            metadata={
                "provider": self.provider,
                "role": self.role.value,
                "version": self.version,
            },
        )

    def matches_definition(
        self,
        definition: StrategyModuleDefinition,
    ) -> bool:
        return (
            definition.role == self.role
            and (
                definition.provider
                .strip()
                .lower()
                == self.provider
                .strip()
                .lower()
            )
        )

    def _validate_definition(self) -> None:
        if self.definition.role != self.role:
            raise ValueError(
                "Module definition role "
                "does not match module role"
            )

        if (
            self.definition.provider
            .strip()
            .lower()
            != self.provider
            .strip()
            .lower()
        ):
            raise ValueError(
                "Module definition provider "
                "does not match module provider"
            )


class TrendModule(StrategyModule):
    role = ModuleRole.TREND


class LiquidityModule(StrategyModule):
    role = ModuleRole.LIQUIDITY


class POIModule(StrategyModule):
    role = ModuleRole.POI


class EntryModule(StrategyModule):
    role = ModuleRole.ENTRY


class RiskModule(StrategyModule):
    role = ModuleRole.RISK


class ManagementModule(StrategyModule):
    role = ModuleRole.MANAGEMENT


class FilterModule(StrategyModule):
    role = ModuleRole.FILTER


class ExecutionModule(StrategyModule):
    role = ModuleRole.EXECUTION