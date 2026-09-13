from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Type

from strategy_runtime.executor import (
    GenericStrategyRuntimeExecutor,
)

from .ai_compilation_pipeline import (
    AICompilationPipelineResult,
)
from .ai_runtime_bridge import (
    AIRuntimeBridgeResult,
)


@dataclass(slots=True)
class AIGenericRuntimeDryRunResult:
    success: bool
    attempted: bool
    reason: str
    runtime_result: Any | None = None
    context: Any | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        runtime_payload = None

        if self.runtime_result is not None and hasattr(
            self.runtime_result,
            "to_dict",
        ):
            runtime_payload = self.runtime_result.to_dict()

        context_payload = None

        if self.context is not None and hasattr(
            self.context,
            "to_dict",
        ):
            context_payload = self.context.to_dict()

        return {
            "success": bool(self.success),
            "attempted": bool(self.attempted),
            "reason": self.reason,
            "runtime_result": runtime_payload,
            "context": context_payload,
            "diagnostics": dict(self.diagnostics),
        }


class AIGenericRuntimeDryRun:
    """
    Day 89 AI strategy -> GenericStrategyRuntimeExecutor dry-run gateway.

    Pipeline:
        Day 87 compiled strategy
        + Day 88 verified runtime payload
        -> GenericStrategyRuntimeExecutor
        -> StrategyContext
        -> generic strategy evaluation

    Safety:
    - no execution adapter is accepted here;
    - no broker/MT5 call exists in this class;
    - Day 87 and Day 88 must both be READY;
    - compilation identity must match the Day 88 payload;
    - one call evaluates the generic strategy exactly once;
    - ENTRY_READY is only a signal result, not an order submission.
    """

    def __init__(
        self,
        *,
        registry: Any,
        executor_class: Type[Any] = GenericStrategyRuntimeExecutor,
    ) -> None:
        self.registry = registry
        self.executor_class = executor_class

    def run(
        self,
        *,
        compilation: AICompilationPipelineResult,
        bridge: AIRuntimeBridgeResult,
        symbol: str,
        current_time: int,
        rates_by_timeframe: dict[str, Any] | None = None,
        market: dict[str, Any] | None = None,
    ) -> AIGenericRuntimeDryRunResult:
        if not compilation.ready:
            return self._blocked(
                "ai_compilation_pipeline_not_ready"
            )

        if not bridge.success or bridge.payload is None:
            return self._blocked(
                "ai_runtime_bridge_not_ready"
            )

        compiled = compilation.compiled

        if compiled is None:
            return self._blocked(
                "compiled_strategy_missing"
            )

        identity_error = self._verify_identity(
            compiled=compiled,
            bridge=bridge,
        )

        if identity_error is not None:
            return self._blocked(
                identity_error
            )

        try:
            executor = self.executor_class(
                registry=self.registry,
                compiled=compiled,
            )
        except Exception as exc:
            return AIGenericRuntimeDryRunResult(
                success=False,
                attempted=False,
                reason="generic_runtime_executor_creation_failed",
                diagnostics={
                    "generic_runtime_called": False,
                    "execution_adapter_called": False,
                    "broker_call_performed": False,
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                },
            )

        try:
            context = executor.create_context(
                symbol=symbol,
                current_time=int(current_time),
                rates_by_timeframe=dict(
                    rates_by_timeframe or {}
                ),
                market=dict(
                    market or {}
                ),
            )
        except Exception as exc:
            return AIGenericRuntimeDryRunResult(
                success=False,
                attempted=False,
                reason="generic_runtime_context_creation_failed",
                diagnostics={
                    "generic_runtime_called": False,
                    "execution_adapter_called": False,
                    "broker_call_performed": False,
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                },
            )

        try:
            runtime_result = executor.execute(
                context
            )
        except Exception as exc:
            if hasattr(
                context,
                "add_error",
            ):
                context.add_error(
                    "ai_generic_runtime_dry_run",
                    f"{type(exc).__name__}:{exc}",
                )

            return AIGenericRuntimeDryRunResult(
                success=False,
                attempted=True,
                reason="generic_runtime_execution_exception",
                context=context,
                diagnostics={
                    "generic_runtime_called": True,
                    "execution_adapter_called": False,
                    "broker_call_performed": False,
                    "resubmission_performed": False,
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                },
            )

        success = bool(
            getattr(
                runtime_result,
                "success",
                False,
            )
        )

        event = str(
            getattr(
                runtime_result,
                "event",
                "",
            )
        )

        context.trade[
            "ai_generic_runtime_dry_run"
        ] = {
            "compilation_id": str(
                compiled.compilation_id
            ),
            "strategy_id": str(
                compiled.strategy_id
            ),
            "event": event,
            "runtime_success": success,
            "broker_call_performed": False,
        }

        return AIGenericRuntimeDryRunResult(
            success=success,
            attempted=True,
            reason=(
                "generic_runtime_dry_run_completed"
                if success
                else "generic_runtime_dry_run_failed"
            ),
            runtime_result=runtime_result,
            context=context,
            diagnostics={
                "generic_runtime_called": True,
                "execution_adapter_called": False,
                "broker_call_performed": False,
                "resubmission_performed": False,
                "runtime_event": event,
                "entry_ready_only": (
                    event == "ENTRY_READY"
                ),
            },
        )

    @staticmethod
    def _verify_identity(
        *,
        compiled: Any,
        bridge: AIRuntimeBridgeResult,
    ) -> str | None:
        payload = bridge.payload

        if payload is None:
            return "ai_runtime_bridge_payload_missing"

        if (
            str(payload.compilation_id)
            != str(compiled.compilation_id)
        ):
            return "dry_run_compilation_id_mismatch"

        if (
            str(payload.strategy_id)
            != str(compiled.strategy_id)
        ):
            return "dry_run_strategy_id_mismatch"

        if list(payload.symbols) != list(
            compiled.symbols
        ):
            return "dry_run_symbols_mismatch"

        if list(payload.timeframes) != list(
            compiled.timeframes
        ):
            return "dry_run_timeframes_mismatch"

        return None

    @staticmethod
    def _blocked(
        reason: str,
    ) -> AIGenericRuntimeDryRunResult:
        return AIGenericRuntimeDryRunResult(
            success=False,
            attempted=False,
            reason=reason,
            diagnostics={
                "generic_runtime_called": False,
                "execution_adapter_called": False,
                "broker_call_performed": False,
                "resubmission_performed": False,
            },
        )