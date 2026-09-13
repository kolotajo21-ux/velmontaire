from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.context import StrategyContext
from .generic_live_runtime_service import (
    GenericLiveRuntimeService,
    GenericLiveRuntimeServiceResult,
)


@dataclass(slots=True)
class ProductionReadinessResult:
    ready: bool
    started: bool
    cycle_allowed: bool
    reason: str
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": bool(self.ready),
            "started": bool(self.started),
            "cycle_allowed": bool(self.cycle_allowed),
            "reason": self.reason,
            "diagnostics": dict(self.diagnostics),
        }


class ProductionLiveRuntime:
    """
    Day 80 final production boundary.

    It deliberately adds no new broker behavior.  It wraps the Day 79
    service and exposes the smallest safe application-facing API:

        boot() -> verify startup readiness
        cycle(context) -> run exactly one externally requested cycle
        readiness() -> inspect whether live cycles are currently allowed

    Safety invariants:
    - no cycle before successful startup;
    - no automatic retry/resubmission;
    - blocked startup remains fail-closed;
    - Day 79 remains authoritative for cycle execution and counters.
    """

    def __init__(
        self,
        *,
        service: GenericLiveRuntimeService,
    ) -> None:
        self.service = service
        self._boot_attempted = False
        self._boot_succeeded = False
        self._last_reason: str | None = None

    def boot(self) -> ProductionReadinessResult:
        self._boot_attempted = True

        result = self.service.start()
        self._boot_succeeded = bool(
            result.success
            and result.status is not None
            and result.status.ready
        )
        self._last_reason = result.reason

        return ProductionReadinessResult(
            ready=self._boot_succeeded,
            started=True,
            cycle_allowed=self._boot_succeeded,
            reason=(
                "production_runtime_ready"
                if self._boot_succeeded
                else "production_runtime_startup_blocked"
            ),
            diagnostics={
                "service_reason": result.reason,
                "startup_performed": True,
                "broker_call_performed": False,
                "resubmission_performed": False,
            },
        )

    def cycle(
        self,
        context: StrategyContext,
    ) -> GenericLiveRuntimeServiceResult:
        if not self._boot_attempted or not self._boot_succeeded:
            return GenericLiveRuntimeServiceResult(
                success=False,
                attempted=False,
                reason="production_runtime_not_ready",
                status=self.service.status(),
                diagnostics={
                    "startup_performed": False,
                    "strategy_cycle_performed": False,
                    "resubmission_performed": False,
                },
            )

        result = self.service.run_cycle(context)
        self._last_reason = result.reason

        context.diagnostics["production_live_runtime"] = {
            "ready": bool(self.readiness().ready),
            "service_status": self.service.status().to_dict(),
            "last_reason": self._last_reason,
        }

        return result

    def readiness(self) -> ProductionReadinessResult:
        status = self.service.status()
        ready = bool(
            self._boot_attempted
            and self._boot_succeeded
            and status.ready
        )

        return ProductionReadinessResult(
            ready=ready,
            started=bool(status.started),
            cycle_allowed=ready,
            reason=(
                "production_runtime_ready"
                if ready
                else "production_runtime_not_ready"
            ),
            diagnostics={
                "service_status": status.to_dict(),
                "last_reason": self._last_reason,
                "resubmission_performed": False,
            },
        )