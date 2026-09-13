from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from core.context import StrategyContext
from .generic_runtime_startup import GenericRuntimeStartupOrchestrator


@dataclass(slots=True)
class GenericLiveRuntimeCycleResult:
    success: bool
    attempted: bool
    reason: str
    diagnostics: dict[str, Any] = field(default_factory=dict)


class GenericLiveRuntime:
    """
    Day 78 startup-gated generic live runtime.

    Every live cycle is blocked unless Day 77 startup orchestration is READY.

    Safety:
    - no strategy evaluation before startup READY;
    - no entry execution before startup READY;
    - startup recovery itself never becomes an entry trigger;
    - one cycle performs strategy evaluation at most once.
    """

    def __init__(
        self,
        *,
        startup: GenericRuntimeStartupOrchestrator,
        strategy_cycle: Callable[[StrategyContext], Any],
    ) -> None:
        self.startup = startup
        self.strategy_cycle = strategy_cycle

    def run_cycle(
        self,
        context: StrategyContext,
    ) -> GenericLiveRuntimeCycleResult:
        if not self.startup.checked:
            return GenericLiveRuntimeCycleResult(
                success=False,
                attempted=False,
                reason="live_runtime_startup_not_checked",
                diagnostics={
                    "strategy_cycle_performed": False,
                    "resubmission_performed": False,
                },
            )

        if not self.startup.ready:
            return GenericLiveRuntimeCycleResult(
                success=False,
                attempted=False,
                reason="live_runtime_startup_not_ready",
                diagnostics={
                    "strategy_cycle_performed": False,
                    "resubmission_performed": False,
                },
            )

        try:
            result = self.strategy_cycle(context)
        except Exception as exc:
            context.add_error(
                "generic_live_runtime_cycle",
                f"{type(exc).__name__}:{exc}",
            )
            return GenericLiveRuntimeCycleResult(
                success=False,
                attempted=True,
                reason="live_runtime_strategy_cycle_exception",
                diagnostics={
                    "strategy_cycle_performed": True,
                    "resubmission_performed": False,
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                },
            )

        success = bool(
            getattr(result, "success", True)
        )

        context.trade["generic_live_runtime"] = {
            "startup_ready": True,
            "strategy_cycle_performed": True,
            "cycle_success": success,
        }

        return GenericLiveRuntimeCycleResult(
            success=success,
            attempted=True,
            reason=(
                "live_runtime_cycle_completed"
                if success
                else "live_runtime_cycle_failed"
            ),
            diagnostics={
                "strategy_cycle_performed": True,
                "resubmission_performed": False,
            },
        )