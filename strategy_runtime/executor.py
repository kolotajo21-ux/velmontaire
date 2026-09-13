from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.context import StrategyContext
from core.strategy import (
    ModuleRole,
    StrategyDefinition,
    StrategyMetadata,
    StrategyModuleDefinition,
    StrategyStatus,
)
from core.strategy_registry import StrategyModuleRegistry
from strategy_compiler import CompiledStrategy

from .condition_evaluator import (
    ConditionEvaluationResult,
    GenericConditionEvaluator,
)


@dataclass(slots=True)
class GenericRuntimeResult:
    success: bool
    passed: bool
    event: str
    reason: str
    entry_index: int | None = None
    context: StrategyContext | None = None
    diagnostics: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": bool(self.success),
            "passed": bool(self.passed),
            "event": self.event,
            "reason": self.reason,
            "entry_index": self.entry_index,
            "context": (
                self.context.to_dict()
                if self.context is not None
                else None
            ),
            "diagnostics": dict(
                self.diagnostics
            ),
        }


class GenericStrategyRuntimeExecutor:
    """
    Generic executor for CompiledStrategy.

    No broker calls.
    Existing hard-coded SMC StrategyEngine is untouched.

    Diagnostic behavior:
    - every compiled entry evaluation is recorded;
    - WAIT includes the first identifiable failed condition;
    - runtime stays fail-closed on evaluator errors.
    """

    def __init__(
        self,
        *,
        registry: StrategyModuleRegistry,
        compiled: CompiledStrategy,
    ) -> None:
        self.registry = registry
        self.compiled = compiled

        self.strategy_definition = (
            self._build_strategy_definition()
        )

        self.evaluator = (
            GenericConditionEvaluator(
                registry=registry,
                compiled=compiled,
            )
        )

    def create_context(
        self,
        *,
        symbol: str,
        current_time: int,
        rates_by_timeframe: dict[str, Any] | None = None,
        market: dict[str, Any] | None = None,
        rates_by_symbol: dict[str, dict[str, Any]] | None = None,
        market_by_symbol: dict[str, dict[str, Any]] | None = None,
    ) -> StrategyContext:
        normalized_symbol = str(
            symbol
        ).strip().upper()

        if (
            normalized_symbol
            not in {
                item.upper()
                for item in self.compiled.symbols
            }
        ):
            raise ValueError(
                "symbol_not_allowed_by_compiled_strategy"
            )

        return StrategyContext(
            strategy=self.strategy_definition,
            symbol=normalized_symbol,
            current_time=int(
                current_time
            ),
            rates_by_timeframe=dict(
                rates_by_timeframe or {}
            ),
            market=dict(
                market or {}
            ),
            rates_by_symbol={
                str(key).strip().upper(): dict(value or {})
                for key, value in (rates_by_symbol or {}).items()
            },
            market_by_symbol={
                str(key).strip().upper(): dict(value or {})
                for key, value in (market_by_symbol or {}).items()
            },
        )

    def execute(
        self,
        context: StrategyContext,
    ) -> GenericRuntimeResult:
        if (
            context.strategy.metadata.strategy_id
            != self.compiled.strategy_id
        ):
            return GenericRuntimeResult(
                False,
                False,
                "ERROR",
                "strategy_context_mismatch",
                context=context,
            )

        if not self.compiled.entries:
            return GenericRuntimeResult(
                False,
                False,
                "ERROR",
                "compiled_strategy_has_no_entries",
                context=context,
            )

        failures: list[str] = []
        entry_evaluations: list[dict[str, Any]] = []
        first_blocker: str | None = None

        for entry in self.compiled.entries:
            entry_index = int(
                entry.get(
                    "entry_index",
                    0,
                )
            )

            conditions = entry.get(
                "conditions"
            )

            result = self.evaluator.evaluate(
                conditions,
                context,
            )

            result_dict = self._safe_result_dict(
                result
            )

            blocker = self._find_first_blocker(
                result_dict
            )

            entry_evaluations.append(
                {
                    "entry_index": entry_index,
                    "side": entry.get("side"),
                    "order_type": entry.get(
                        "order_type"
                    ),
                    "success": bool(
                        getattr(
                            result,
                            "success",
                            False,
                        )
                    ),
                    "passed": bool(
                        getattr(
                            result,
                            "passed",
                            False,
                        )
                    ),
                    "reason": str(
                        getattr(
                            result,
                            "reason",
                            "",
                        )
                    ),
                    "first_blocker": blocker,
                    "condition": result_dict,
                }
            )

            if (
                first_blocker is None
                and blocker
            ):
                first_blocker = blocker

            if not result.success:
                failures.append(
                    result.reason
                )
                continue

            if not result.passed:
                continue

            context.trade.update(
                {
                    "side": entry.get(
                        "side"
                    ),
                    "order_type": entry.get(
                        "order_type"
                    ),
                    "entry_price": entry.get(
                        "entry_price"
                    ),
                    "stop_loss": (
                        self.compiled.stop_loss
                    ),
                    "take_profit": (
                        self.compiled.take_profit
                    ),
                    "risk": dict(
                        self.compiled.risk
                    ),
                    "compilation_id": (
                        self.compiled.compilation_id
                    ),
                    "strategy_id": (
                        self.compiled.strategy_id
                    ),
                    "entry_index": entry_index,
                }
            )

            return GenericRuntimeResult(
                True,
                True,
                "ENTRY_READY",
                "compiled_entry_conditions_passed",
                entry_index=entry_index,
                context=context,
                diagnostics={
                    "condition": result_dict,
                    "entry_evaluations": (
                        entry_evaluations
                    ),
                },
            )

        if failures:
            return GenericRuntimeResult(
                False,
                False,
                "ERROR",
                failures[0],
                context=context,
                diagnostics={
                    "failures": failures,
                    "entry_evaluations": (
                        entry_evaluations
                    ),
                    "first_blocker": (
                        first_blocker
                    ),
                },
            )

        wait_reason = (
            "entry_conditions_not_passed"
        )

        if first_blocker:
            wait_reason = (
                "entry_conditions_not_passed:"
                + first_blocker
            )

        return GenericRuntimeResult(
            True,
            False,
            "WAIT",
            wait_reason,
            context=context,
            diagnostics={
                "entry_evaluations": (
                    entry_evaluations
                ),
                "first_blocker": (
                    first_blocker
                ),
            },
        )

    @staticmethod
    def _safe_result_dict(
        result: ConditionEvaluationResult,
    ) -> dict[str, Any]:
        try:
            payload = result.to_dict()
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass

        return {
            "success": bool(
                getattr(
                    result,
                    "success",
                    False,
                )
            ),
            "passed": bool(
                getattr(
                    result,
                    "passed",
                    False,
                )
            ),
            "reason": str(
                getattr(
                    result,
                    "reason",
                    "",
                )
            ),
        }

    @classmethod
    def _find_first_blocker(
        cls,
        node: Any,
    ) -> str | None:
        """
        Best-effort extraction of the first failed condition/event from
        ConditionEvaluationResult.to_dict(), without depending on one exact
        diagnostic payload shape.
        """
        if isinstance(node, dict):
            passed = node.get("passed")
            success = node.get("success")

            if passed is False or success is False:
                label = cls._diagnostic_label(
                    node
                )
                if label:
                    return label

            # Sequence order matters. Prefer child/sequence traversal first.
            for key in (
                "children",
                "sequence",
                "steps",
                "results",
                "evaluations",
                "conditions",
            ):
                value = node.get(key)
                if isinstance(
                    value,
                    (list, tuple),
                ):
                    for child in value:
                        blocker = (
                            cls._find_first_blocker(
                                child
                            )
                        )
                        if blocker:
                            return blocker

            # Then inspect nested dictionaries.
            for key, value in node.items():
                if key in {
                    "children",
                    "sequence",
                    "steps",
                    "results",
                    "evaluations",
                    "conditions",
                }:
                    continue

                if isinstance(
                    value,
                    (dict, list, tuple),
                ):
                    blocker = (
                        cls._find_first_blocker(
                            value
                        )
                    )
                    if blocker:
                        return blocker

        elif isinstance(
            node,
            (list, tuple),
        ):
            for child in node:
                blocker = (
                    cls._find_first_blocker(
                        child
                    )
                )
                if blocker:
                    return blocker

        return None

    @staticmethod
    def _diagnostic_label(
        node: dict[str, Any],
    ) -> str | None:
        for key in (
            "event_name",
            "semantic_event",
            "condition_id",
            "node_id",
            "reason",
            "operation",
            "provider",
        ):
            value = node.get(key)
            if value not in (
                None,
                "",
                "None",
            ):
                return (
                    f"{key}={value}"
                )

        payload = node.get("payload")
        if isinstance(payload, dict):
            for key in (
                "event_name",
                "condition_id",
                "node_id",
                "reason",
                "operation",
            ):
                value = payload.get(key)
                if value not in (
                    None,
                    "",
                    "None",
                ):
                    return (
                        f"{key}={value}"
                    )

            metadata = payload.get(
                "metadata"
            )
            if isinstance(
                metadata,
                dict,
            ):
                for key in (
                    "semantic_event",
                    "timeframe",
                    "provider_hint",
                ):
                    value = metadata.get(
                        key
                    )
                    if value not in (
                        None,
                        "",
                        "None",
                    ):
                        return (
                            f"{key}={value}"
                        )

        return None

    def _build_strategy_definition(
        self,
    ) -> StrategyDefinition:
        modules: list[
            StrategyModuleDefinition
        ] = []

        seen: set[
            tuple[str, str]
        ] = set()

        for binding in self.compiled.module_bindings:
            key = (
                binding.role,
                binding.provider.lower(),
            )

            if key in seen:
                continue

            seen.add(
                key
            )

            role = ModuleRole(
                binding.role
            )

            modules.append(
                StrategyModuleDefinition(
                    role=role,
                    provider=binding.provider,
                    enabled=True,
                    required=True,
                    parameters={
                        "capability": (
                            binding.capability
                        ),
                    },
                    metadata={
                        "compiled": True,
                        "compiler_version": (
                            self.compiled
                            .metadata
                            .get(
                                "compiler_version"
                            )
                        ),
                    },
                )
            )

        return StrategyDefinition(
            metadata=StrategyMetadata(
                name=str(
                    self.compiled.metadata.get(
                        "source_schema_name",
                        self.compiled.strategy_id,
                    )
                ),
                strategy_id=(
                    self.compiled.strategy_id
                ),
                version=str(
                    self.compiled.metadata.get(
                        "source_schema_version",
                        self.compiled.schema_version,
                    )
                ),
                created_from="STRATEGY_COMPILER",
            ),
            modules=modules,
            symbols=list(
                self.compiled.symbols
            ),
            timeframes=list(
                self.compiled.timeframes
            ),
            status=StrategyStatus.COMPILED,
            settings={
                "compilation_id": (
                    self.compiled.compilation_id
                ),
            },
            metadata_extra={
                "generic_runtime": True,
            },
        )
