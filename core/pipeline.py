from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .context import (
    ModuleExecutionResult,
    StrategyContext,
)
from .poi_selector import (
    POISelectionResult,
    POISelector,
)
from .strategy import (
    ModuleRole,
    StrategyDefinition,
    StrategyModuleDefinition,
)
from .strategy_registry import (
    StrategyModuleRegistry,
)


@dataclass(slots=True)
class PipelineStepResult:
    role: ModuleRole
    provider: str

    executed: bool = False
    success: bool = False
    passed: bool = False

    skipped: bool = False
    skip_reason: str | None = None

    error: str | None = None

    result: ModuleExecutionResult | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role.value,
            "provider": self.provider,
            "executed": bool(self.executed),
            "success": bool(self.success),
            "passed": bool(self.passed),
            "skipped": bool(self.skipped),
            "skip_reason": self.skip_reason,
            "error": self.error,
            "result": (
                self.result.to_dict()
                if self.result is not None
                else None
            ),
        }


@dataclass(slots=True)
class PipelineExecutionReport:
    strategy_id: str
    symbol: str

    steps: list[
        PipelineStepResult
    ] = field(
        default_factory=list
    )

    stopped_early: bool = False
    stop_reason: str | None = None

    success: bool = True

    poi_selection: (
        POISelectionResult
        | None
    ) = None

    diagnostics: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "symbol": self.symbol,
            "steps": [
                step.to_dict()
                for step in self.steps
            ],
            "stopped_early": bool(
                self.stopped_early
            ),
            "stop_reason": self.stop_reason,
            "success": bool(
                self.success
            ),
            "poi_selection": (
                self.poi_selection.to_dict()
                if self.poi_selection
                is not None
                else None
            ),
            "diagnostics": dict(
                self.diagnostics
            ),
        }


class StrategyPipeline:
    """
    Исполняет StrategyDefinition через StrategyModuleRegistry.

    Дополнительно:
    после завершения всех POI provider'ов автоматически
    запускает POISelector и сохраняет active_poi
    в StrategyContext до запуска ENTRY.
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
        *,
        stop_on_failure: bool = True,
        stop_on_required_rejection: bool = True,
        poi_selector: POISelector | None = None,
        run_poi_selector: bool = True,
    ) -> None:
        self.registry = registry

        self.stop_on_failure = bool(
            stop_on_failure
        )

        self.stop_on_required_rejection = bool(
            stop_on_required_rejection
        )

        self.run_poi_selector = bool(
            run_poi_selector
        )

        self.poi_selector = (
            poi_selector
            if poi_selector is not None
            else POISelector(
                require_trend_alignment=False,
                quality_weight=1.0,
                priority_weight=0.10,
            )
        )

    def execute(
        self,
        *,
        strategy: StrategyDefinition,
        context: StrategyContext,
    ) -> PipelineExecutionReport:
        if (
            context.strategy.metadata.strategy_id
            != strategy.metadata.strategy_id
        ):
            raise ValueError(
                "Context strategy does not match "
                "pipeline strategy"
            )

        report = PipelineExecutionReport(
            strategy_id=(
                strategy.metadata.strategy_id
            ),
            symbol=context.symbol,
        )

        ordered_definitions = (
            self._ordered_definitions(
                strategy
            )
        )

        poi_selector_executed = False

        for definition in ordered_definitions:
            if (
                self.run_poi_selector
                and not poi_selector_executed
                and definition.role
                != ModuleRole.POI
                and self._has_poi_definitions(
                    strategy
                )
                and self._all_poi_steps_finished(
                    report
                )
            ):
                report.poi_selection = (
                    self._run_poi_selector(
                        context
                    )
                )

                poi_selector_executed = True

            step = self._execute_step(
                definition=definition,
                context=context,
            )

            report.steps.append(
                step
            )

            if step.skipped:
                continue

            if (
                not step.success
                and self.stop_on_failure
            ):
                report.success = False
                report.stopped_early = True
                report.stop_reason = (
                    "module_failure:"
                    f"{definition.role.value}:"
                    f"{definition.provider}"
                )
                break

            if (
                definition.required
                and not step.passed
                and self.stop_on_required_rejection
            ):
                report.success = True
                report.stopped_early = True
                report.stop_reason = (
                    "required_module_rejected:"
                    f"{definition.role.value}:"
                    f"{definition.provider}"
                )
                break

        if (
            self.run_poi_selector
            and not poi_selector_executed
            and self._has_poi_definitions(
                strategy
            )
            and not report.stopped_early
        ):
            report.poi_selection = (
                self._run_poi_selector(
                    context
                )
            )

            poi_selector_executed = True

        report.diagnostics = {
            "total_steps": len(
                ordered_definitions
            ),
            "executed_steps": sum(
                1
                for step in report.steps
                if step.executed
            ),
            "skipped_steps": sum(
                1
                for step in report.steps
                if step.skipped
            ),
            "failed_steps": sum(
                1
                for step in report.steps
                if (
                    step.executed
                    and not step.success
                )
            ),
            "passed_steps": sum(
                1
                for step in report.steps
                if (
                    step.executed
                    and step.success
                    and step.passed
                )
            ),
            "poi_selector_enabled": bool(
                self.run_poi_selector
            ),
            "poi_selector_executed": bool(
                poi_selector_executed
            ),
            "active_poi_found": bool(
                context.get(
                    "active_poi"
                )
            ),
        }

        return report

    def _execute_step(
        self,
        *,
        definition: StrategyModuleDefinition,
        context: StrategyContext,
    ) -> PipelineStepResult:
        step = PipelineStepResult(
            role=definition.role,
            provider=definition.provider,
        )

        if not definition.enabled:
            step.skipped = True
            step.skip_reason = (
                "module_disabled"
            )
            return step

        valid, reason = (
            self.registry
            .validate_definition(
                definition
            )
        )

        if not valid:
            step.executed = False
            step.success = False
            step.passed = False
            step.error = (
                reason
                or "provider_not_registered"
            )

            context.add_error(
                (
                    f"{definition.role.value}:"
                    f"{definition.provider}"
                ),
                step.error,
            )

            return step

        try:
            module = self.registry.create(
                definition
            )

        except Exception as exc:
            step.executed = False
            step.success = False
            step.passed = False
            step.error = (
                f"{type(exc).__name__}: "
                f"{exc}"
            )

            context.add_error(
                (
                    f"{definition.role.value}:"
                    f"{definition.provider}"
                ),
                step.error,
            )

            return step

        result = module.run(
            context
        )

        context.set_result(
            result
        )

        step.executed = True
        step.success = bool(
            result.success
        )
        step.passed = bool(
            result.passed
        )
        step.error = result.error
        step.result = result

        return step

    def _run_poi_selector(
        self,
        context: StrategyContext,
    ) -> POISelectionResult:
        selection = self.poi_selector.select(
            context
        )

        context.put(
            "poi_selection",
            selection.to_dict(),
        )

        if selection.selected is None:
            context.put(
                "active_poi",
                None,
            )

        return selection

    @staticmethod
    def _has_poi_definitions(
        strategy: StrategyDefinition,
    ) -> bool:
        return any(
            definition.enabled
            and definition.role
            == ModuleRole.POI
            for definition
            in strategy.modules
        )

    @staticmethod
    def _all_poi_steps_finished(
        report: PipelineExecutionReport,
    ) -> bool:
        return any(
            step.role == ModuleRole.POI
            for step in report.steps
        )

    def _ordered_definitions(
        self,
        strategy: StrategyDefinition,
    ) -> list[
        StrategyModuleDefinition
    ]:
        role_rank = {
            role: index
            for index, role
            in enumerate(
                self.ROLE_ORDER
            )
        }

        return sorted(
            strategy.modules,
            key=lambda definition: (
                role_rank.get(
                    definition.role,
                    len(
                        self.ROLE_ORDER
                    ),
                ),
                int(
                    definition.priority
                ),
                definition.provider.lower(),
            ),
        )