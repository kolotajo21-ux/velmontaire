from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.context import StrategyContext
from .generic_live_runtime import (
    GenericLiveRuntime,
    GenericLiveRuntimeCycleResult,
)
from .generic_runtime_startup import (
    GenericRuntimeStartupOrchestrator,
    RuntimeStartupResult,
)


@dataclass(slots=True)
class GenericLiveRuntimeServiceStatus:
    started: bool
    ready: bool
    cycles: int
    successful_cycles: int
    failed_cycles: int
    last_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "started": bool(self.started),
            "ready": bool(self.ready),
            "cycles": int(self.cycles),
            "successful_cycles": int(
                self.successful_cycles
            ),
            "failed_cycles": int(
                self.failed_cycles
            ),
            "last_reason": self.last_reason,
        }


@dataclass(slots=True)
class GenericLiveRuntimeServiceResult:
    success: bool
    attempted: bool
    reason: str
    startup_result: RuntimeStartupResult | None = None
    cycle_result: GenericLiveRuntimeCycleResult | None = None
    status: GenericLiveRuntimeServiceStatus | None = None
    diagnostics: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": bool(self.success),
            "attempted": bool(self.attempted),
            "reason": self.reason,
            "startup_result": (
                self.startup_result.to_dict()
                if self.startup_result is not None
                else None
            ),
            "cycle_result": (
                self.cycle_result.to_dict()
                if self.cycle_result is not None
                else None
            ),
            "status": (
                self.status.to_dict()
                if self.status is not None
                else None
            ),
            "diagnostics": dict(
                self.diagnostics
            ),
        }


class GenericLiveRuntimeService:
    """
    Day 79 production-style runtime coordinator.

    Responsibilities:
      1. perform Day 77 startup orchestration exactly when requested;
      2. expose one safe cycle entry point;
      3. refuse cycles until startup is READY;
      4. keep lightweight runtime health counters;
      5. never retry/resubmit an entry by itself.

    This class is orchestration only. Broker submission remains owned by
    the existing execution pipeline.
    """

    def __init__(
        self,
        *,
        startup: GenericRuntimeStartupOrchestrator,
        runtime: GenericLiveRuntime,
    ) -> None:
        self.startup = startup
        self.runtime = runtime

        self._started = False
        self._cycles = 0
        self._successful_cycles = 0
        self._failed_cycles = 0
        self._last_reason: str | None = None

    def start(
        self,
    ) -> GenericLiveRuntimeServiceResult:
        startup_result = self.startup.startup()

        self._started = True
        self._last_reason = startup_result.reason

        return GenericLiveRuntimeServiceResult(
            success=bool(
                startup_result.ready
            ),
            attempted=True,
            reason=startup_result.reason,
            startup_result=startup_result,
            cycle_result=None,
            status=self.status(),
            diagnostics={
                "startup_performed": True,
                "strategy_cycle_performed": False,
                "resubmission_performed": False,
            },
        )

    def run_cycle(
        self,
        context: StrategyContext,
    ) -> GenericLiveRuntimeServiceResult:
        if not self._started:
            self._last_reason = (
                "generic_live_service_not_started"
            )

            return GenericLiveRuntimeServiceResult(
                success=False,
                attempted=False,
                reason=self._last_reason,
                status=self.status(),
                diagnostics={
                    "startup_performed": False,
                    "strategy_cycle_performed": False,
                    "resubmission_performed": False,
                },
            )

        if not self.startup.ready:
            self._last_reason = (
                "generic_live_service_startup_not_ready"
            )

            return GenericLiveRuntimeServiceResult(
                success=False,
                attempted=False,
                reason=self._last_reason,
                status=self.status(),
                diagnostics={
                    "startup_performed": False,
                    "strategy_cycle_performed": False,
                    "resubmission_performed": False,
                },
            )

        cycle_result = self.runtime.run_cycle(
            context
        )

        self._cycles += 1

        if cycle_result.success:
            self._successful_cycles += 1
        else:
            self._failed_cycles += 1

        self._last_reason = cycle_result.reason

        context.diagnostics[
            "generic_live_runtime_service"
        ] = self.status().to_dict()

        return GenericLiveRuntimeServiceResult(
            success=bool(
                cycle_result.success
            ),
            attempted=bool(
                cycle_result.attempted
            ),
            reason=cycle_result.reason,
            cycle_result=cycle_result,
            status=self.status(),
            diagnostics={
                "startup_performed": False,
                "strategy_cycle_performed": bool(
                    cycle_result.diagnostics.get(
                        "strategy_cycle_performed",
                        cycle_result.attempted,
                    )
                ),
                "resubmission_performed": False,
            },
        )

    def status(
        self,
    ) -> GenericLiveRuntimeServiceStatus:
        return GenericLiveRuntimeServiceStatus(
            started=self._started,
            ready=bool(
                self._started
                and self.startup.ready
            ),
            cycles=self._cycles,
            successful_cycles=(
                self._successful_cycles
            ),
            failed_cycles=(
                self._failed_cycles
            ),
            last_reason=self._last_reason,
        )