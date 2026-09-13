from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .strategy import (
    ModuleRole,
    StrategyDefinition,
    StrategyModuleDefinition,
)
from .strategy_registry import (
    StrategyModuleRegistry,
)


@dataclass(slots=True)
class ExecutionPlanStep:
    index: int

    role: ModuleRole
    provider: str

    priority: int

    required: bool
    enabled: bool

    timeframe: str | None = None

    parameters: dict[str, Any] = field(
        default_factory=dict
    )

    capabilities: set[str] = field(
        default_factory=set
    )

    dependencies: tuple[
        ModuleRole,
        ...
    ] = ()

    version: str = "1.0.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": int(
                self.index
            ),
            "role": self.role.value,
            "provider": self.provider,
            "priority": int(
                self.priority
            ),
            "required": bool(
                self.required
            ),
            "enabled": bool(
                self.enabled
            ),
            "timeframe": (
                str(self.timeframe)
                if self.timeframe
                is not None
                else None
            ),
            "parameters": dict(
                self.parameters
            ),
            "capabilities": sorted(
                self.capabilities
            ),
            "dependencies": [
                role.value
                for role
                in self.dependencies
            ],
            "version": self.version,
        }


@dataclass(slots=True)
class ExecutionPlan:
    strategy_id: str
    strategy_name: str
    strategy_version: str

    steps: list[
        ExecutionPlanStep
    ] = field(
        default_factory=list
    )

    symbols: list[str] = field(
        default_factory=list
    )

    timeframes: list[str] = field(
        default_factory=list
    )

    settings: dict[str, Any] = field(
        default_factory=dict
    )

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def enabled_steps(
        self,
    ) -> list[ExecutionPlanStep]:
        return [
            step
            for step in self.steps
            if step.enabled
        ]

    def steps_by_role(
        self,
        role: ModuleRole,
    ) -> list[ExecutionPlanStep]:
        return [
            step
            for step in self.steps
            if (
                step.enabled
                and step.role == role
            )
        ]

    def required_steps(
        self,
    ) -> list[ExecutionPlanStep]:
        return [
            step
            for step in self.steps
            if (
                step.enabled
                and step.required
            )
        ]

    def providers(
        self,
    ) -> list[str]:
        return [
            step.provider
            for step in self.steps
            if step.enabled
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": (
                self.strategy_id
            ),
            "strategy_name": (
                self.strategy_name
            ),
            "strategy_version": (
                self.strategy_version
            ),
            "steps": [
                step.to_dict()
                for step in self.steps
            ],
            "symbols": list(
                self.symbols
            ),
            "timeframes": list(
                self.timeframes
            ),
            "settings": dict(
                self.settings
            ),
            "metadata": dict(
                self.metadata
            ),
        }


class StrategyCompiler:
    """
    Компилирует StrategyDefinition
    в детерминированный ExecutionPlan.

    Compiler не исполняет торговую логику.
    Он только проверяет доступность provider'ов
    и строит порядок выполнения.
    """

    ROLE_ORDER: tuple[
        ModuleRole,
        ...
    ] = (
        ModuleRole.MARKET,
        ModuleRole.TREND,
        ModuleRole.LIQUIDITY,
        ModuleRole.POI,
        ModuleRole.FILTER,
        ModuleRole.ENTRY,
        ModuleRole.RISK,
        ModuleRole.MANAGEMENT,
        ModuleRole.EXECUTION,
    )

    def __init__(
        self,
        registry: StrategyModuleRegistry,
    ) -> None:
        self.registry = registry

    def compile(
        self,
        strategy: StrategyDefinition,
    ) -> ExecutionPlan:
        ordered = self._ordered_definitions(
            strategy
        )

        steps: list[
            ExecutionPlanStep
        ] = []

        for index, definition in enumerate(
            ordered
        ):
            step = self._compile_step(
                index=index,
                definition=definition,
            )

            steps.append(
                step
            )

        return ExecutionPlan(
            strategy_id=(
                strategy.metadata.strategy_id
            ),
            strategy_name=(
                strategy.metadata.name
            ),
            strategy_version=(
                strategy.metadata.version
            ),
            steps=steps,
            symbols=list(
                strategy.symbols
            ),
            timeframes=list(
                strategy.timeframes
            ),
            settings=dict(
                strategy.settings
            ),
            metadata={
                "module_count": len(
                    steps
                ),
                "enabled_module_count": sum(
                    1
                    for step in steps
                    if step.enabled
                ),
                "required_module_count": sum(
                    1
                    for step in steps
                    if (
                        step.enabled
                        and step.required
                    )
                ),
            },
        )

    def _compile_step(
        self,
        *,
        index: int,
        definition: StrategyModuleDefinition,
    ) -> ExecutionPlanStep:
        if not definition.enabled:
            return ExecutionPlanStep(
                index=index,
                role=definition.role,
                provider=definition.provider,
                priority=definition.priority,
                required=definition.required,
                enabled=False,
                timeframe=definition.timeframe,
                parameters=dict(
                    definition.parameters
                ),
            )

        valid, reason = (
            self.registry
            .validate_definition(
                definition
            )
        )

        if not valid:
            raise ValueError(
                reason
                or (
                    "Strategy module "
                    "definition is invalid"
                )
            )

        registered = (
            self.registry
            .get_registration(
                role=definition.role,
                provider=definition.provider,
            )
        )

        module_class = (
            registered.module_class
        )

        dependencies = tuple(
            module_class.dependencies
        )

        self._validate_dependency_order(
            definition=definition,
            dependencies=dependencies,
        )

        return ExecutionPlanStep(
            index=index,
            role=definition.role,
            provider=definition.provider,
            priority=definition.priority,
            required=definition.required,
            enabled=True,
            timeframe=definition.timeframe,
            parameters=dict(
                definition.parameters
            ),
            capabilities=set(
                registered.capabilities
            ),
            dependencies=dependencies,
            version=registered.version,
        )

    def _validate_dependency_order(
        self,
        *,
        definition: StrategyModuleDefinition,
        dependencies: tuple[
            ModuleRole,
            ...
        ],
    ) -> None:
        if not dependencies:
            return

        current_rank = (
            self._role_rank(
                definition.role
            )
        )

        for dependency in dependencies:
            dependency_rank = (
                self._role_rank(
                    dependency
                )
            )

            if (
                dependency_rank
                > current_rank
            ):
                raise ValueError(
                    "Invalid module dependency "
                    f"order: {definition.role.value}/"
                    f"{definition.provider} depends on "
                    f"{dependency.value}, which executes "
                    "after the current role"
                )

    def _ordered_definitions(
        self,
        strategy: StrategyDefinition,
    ) -> list[
        StrategyModuleDefinition
    ]:
        return sorted(
            strategy.modules,
            key=lambda definition: (
                self._role_rank(
                    definition.role
                ),
                int(
                    definition.priority
                ),
                definition.provider.lower(),
            ),
        )

    def _role_rank(
        self,
        role: ModuleRole,
    ) -> int:
        try:
            return self.ROLE_ORDER.index(
                role
            )
        except ValueError:
            return len(
                self.ROLE_ORDER
            )