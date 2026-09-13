from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Type

from strategy_runtime.execution_request import (
    ExecutionRequestBuildResult,
    TradePlanExecutionRequestBuilder,
)
from strategy_runtime.trade_plan import (
    TradePlanResolution,
    TradePlanResolver,
)

from .ai_compilation_pipeline import (
    AICompilationPipelineResult,
)
from .ai_generic_runtime_dry_run import (
    AIGenericRuntimeDryRunResult,
)


@dataclass(slots=True)
class AISafeExecutionRequestResult:
    success: bool
    attempted: bool
    reason: str
    trade_plan_result: TradePlanResolution | None = None
    request_result: ExecutionRequestBuildResult | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def order(self) -> Any | None:
        if (
            self.success
            and self.request_result is not None
            and self.request_result.success
        ):
            return self.request_result.order

        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": bool(self.success),
            "attempted": bool(self.attempted),
            "reason": self.reason,
            "trade_plan_result": (
                self.trade_plan_result.__dict__.copy()
                if (
                    self.trade_plan_result is not None
                    and not hasattr(
                        self.trade_plan_result,
                        "to_dict",
                    )
                )
                else (
                    self.trade_plan_result.to_dict()
                    if (
                        self.trade_plan_result is not None
                        and hasattr(
                            self.trade_plan_result,
                            "to_dict",
                        )
                    )
                    else None
                )
            ),
            "request_result": (
                self.request_result.to_dict()
                if self.request_result is not None
                else None
            ),
            "diagnostics": dict(self.diagnostics),
        }


class AISafeExecutionRequestGateway:
    """
    Day 90:
        Day 89 ENTRY_READY
        -> TradePlanResolver
        -> TradePlanExecutionRequestBuilder
        -> validated ExecutionOrder

    This gateway NEVER submits the order.

    Safety:
    - Day 87 compilation must still be READY;
    - Day 89 dry-run must have succeeded;
    - only ENTRY_READY may produce an order;
    - compiled identity must match the StrategyContext strategy;
    - plan resolution must succeed;
    - ExecutionOrder.validate() is enforced by the existing Day 54 builder;
    - no adapter, submitter, orchestrator, broker or MT5 call exists here.
    """

    def __init__(
        self,
        *,
        plan_resolver_class: Type[Any] = TradePlanResolver,
        request_builder: TradePlanExecutionRequestBuilder | None = None,
    ) -> None:
        self.plan_resolver_class = plan_resolver_class
        self.request_builder = (
            request_builder
            if request_builder is not None
            else TradePlanExecutionRequestBuilder(
                provider="ai_strategy_runtime"
            )
        )

    def build(
        self,
        *,
        compilation: AICompilationPipelineResult,
        dry_run: AIGenericRuntimeDryRunResult,
        balance: float,
        entry_index: int = 0,
        pip_size: float = 0.0001,
        pip_value_per_lot: float = 10.0,
        expiration_time: int | None = None,
    ) -> AISafeExecutionRequestResult:
        if not compilation.ready:
            return self._blocked(
                "ai_compilation_pipeline_not_ready"
            )

        if not dry_run.success or dry_run.context is None:
            return self._blocked(
                "ai_generic_runtime_dry_run_not_ready"
            )

        runtime_result = dry_run.runtime_result

        if runtime_result is None:
            return self._blocked(
                "generic_runtime_result_missing"
            )

        event = str(
            getattr(
                runtime_result,
                "event",
                "",
            )
        ).strip().upper()

        if event != "ENTRY_READY":
            return self._blocked(
                "generic_runtime_entry_not_ready"
            )

        compiled = compilation.compiled

        if compiled is None:
            return self._blocked(
                "compiled_strategy_missing"
            )

        context = dry_run.context

        strategy_id = str(
            context.strategy.metadata.strategy_id
        )

        if (
            strategy_id
            != str(compiled.strategy_id)
        ):
            return self._blocked(
                "compiled_strategy_context_strategy_mismatch"
            )

        if (
            str(context.symbol).strip().upper()
            not in {
                str(item).strip().upper()
                for item in compiled.symbols
            }
        ):
            return self._blocked(
                "compiled_strategy_context_symbol_mismatch"
            )

        try:
            resolver = self.plan_resolver_class(
                compiled
            )

            plan_result = resolver.resolve(
                context,
                balance=float(balance),
                entry_index=int(entry_index),
                pip_size=float(pip_size),
                pip_value_per_lot=float(
                    pip_value_per_lot
                ),
            )
        except Exception as exc:
            return AISafeExecutionRequestResult(
                success=False,
                attempted=True,
                reason="trade_plan_resolution_exception",
                diagnostics={
                    "trade_plan_resolution_attempted": True,
                    "execution_request_build_attempted": False,
                    "broker_call_performed": False,
                    "submission_performed": False,
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                },
            )

        if (
            not bool(
                getattr(
                    plan_result,
                    "success",
                    False,
                )
            )
            or getattr(
                plan_result,
                "plan",
                None,
            )
            is None
        ):
            return AISafeExecutionRequestResult(
                success=False,
                attempted=True,
                reason="trade_plan_resolution_failed",
                trade_plan_result=plan_result,
                diagnostics={
                    "trade_plan_resolution_attempted": True,
                    "execution_request_build_attempted": False,
                    "broker_call_performed": False,
                    "submission_performed": False,
                    "trade_plan_reason": getattr(
                        plan_result,
                        "reason",
                        None,
                    ),
                },
            )

        try:
            request_result = self.request_builder.build(
                plan_result.plan,
                context,
                expiration_time=expiration_time,
            )
        except Exception as exc:
            return AISafeExecutionRequestResult(
                success=False,
                attempted=True,
                reason="execution_request_build_exception",
                trade_plan_result=plan_result,
                diagnostics={
                    "trade_plan_resolution_attempted": True,
                    "execution_request_build_attempted": True,
                    "broker_call_performed": False,
                    "submission_performed": False,
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                },
            )

        if (
            not request_result.success
            or request_result.order is None
        ):
            return AISafeExecutionRequestResult(
                success=False,
                attempted=True,
                reason="execution_request_build_failed",
                trade_plan_result=plan_result,
                request_result=request_result,
                diagnostics={
                    "trade_plan_resolution_attempted": True,
                    "execution_request_build_attempted": True,
                    "broker_call_performed": False,
                    "submission_performed": False,
                    "execution_request_reason": (
                        request_result.reason
                    ),
                },
            )

        context.trade[
            "ai_safe_execution_request"
        ] = {
            "execution_id": (
                request_result.order.execution_id
            ),
            "entry_index": int(
                entry_index
            ),
            "request_ready": True,
            "submission_performed": False,
            "broker_call_performed": False,
        }

        return AISafeExecutionRequestResult(
            success=True,
            attempted=True,
            reason="ai_execution_request_ready",
            trade_plan_result=plan_result,
            request_result=request_result,
            diagnostics={
                "trade_plan_resolution_attempted": True,
                "execution_request_build_attempted": True,
                "execution_order_validated": True,
                "submission_performed": False,
                "broker_call_performed": False,
                "execution_id": (
                    request_result.order.execution_id
                ),
            },
        )

    def require_order(
        self,
        result: AISafeExecutionRequestResult,
    ) -> Any:
        if not result.success or result.order is None:
            raise ValueError(
                "ai_safe_execution_request_not_ready"
            )

        return result.order

    @staticmethod
    def _blocked(
        reason: str,
    ) -> AISafeExecutionRequestResult:
        return AISafeExecutionRequestResult(
            success=False,
            attempted=False,
            reason=reason,
            diagnostics={
                "trade_plan_resolution_attempted": False,
                "execution_request_build_attempted": False,
                "submission_performed": False,
                "broker_call_performed": False,
            },
        )