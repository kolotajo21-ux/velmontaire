from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.context import StrategyContext
from .live_position_management_runtime import (
    LivePositionManagementRuntime,
    LivePositionManagementRuntimeResult,
)
from .position_management import PositionManagementRequest
from .position_management_startup_recovery import (
    PositionManagementStartupRecovery,
    StartupRecoveryReport,
)


@dataclass(slots=True)
class PositionManagementStartupGateResult:
    ready: bool
    reason: str
    recovery_report: StartupRecoveryReport
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": bool(self.ready),
            "reason": self.reason,
            "recovery_report": self.recovery_report.to_dict(),
            "diagnostics": dict(self.diagnostics),
        }


@dataclass(slots=True)
class GatedPositionManagementResult:
    success: bool
    attempted: bool
    reason: str
    runtime_result: LivePositionManagementRuntimeResult | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": bool(self.success),
            "attempted": bool(self.attempted),
            "reason": self.reason,
            "runtime_result": (
                self.runtime_result.to_dict()
                if self.runtime_result is not None
                else None
            ),
            "diagnostics": dict(self.diagnostics),
        }


class PositionManagementStartupSafetyGate:
    """
    Day 76 startup safety gate.

    Startup must complete before live position-management runtime is allowed.

    Rules:
    - successful startup recovery -> runtime unlocked;
    - any blocked/unresolved startup recovery -> runtime locked;
    - retryable FAILED entries do not block startup;
    - runtime cannot be called before startup check;
    - blocked gate never performs a broker call.
    """

    def __init__(
        self,
        *,
        startup_recovery: PositionManagementStartupRecovery,
        runtime: LivePositionManagementRuntime,
    ) -> None:
        self.startup_recovery = startup_recovery
        self.runtime = runtime

        self._checked = False
        self._ready = False
        self._report: StartupRecoveryReport | None = None

    @property
    def checked(self) -> bool:
        return self._checked

    @property
    def ready(self) -> bool:
        return self._checked and self._ready

    @property
    def report(self) -> StartupRecoveryReport | None:
        return self._report

    def startup(self) -> PositionManagementStartupGateResult:
        report = self.startup_recovery.run()

        self._checked = True
        self._report = report
        self._ready = bool(report.success)

        reason = (
            "position_management_startup_ready"
            if self._ready
            else "position_management_startup_blocked"
        )

        return PositionManagementStartupGateResult(
            ready=self._ready,
            reason=reason,
            recovery_report=report,
            diagnostics={
                "blocked_recovery_items": int(report.blocked),
                "retryable_recovery_items": int(report.retryable),
                "broker_management_call_performed": False,
            },
        )

    def execute(
        self,
        request: PositionManagementRequest,
        context: StrategyContext,
    ) -> GatedPositionManagementResult:
        if not self._checked:
            return self._blocked(
                "position_management_startup_not_checked"
            )

        if not self._ready:
            return self._blocked(
                "position_management_startup_gate_blocked"
            )

        result = self.runtime.execute(
            request,
            context,
        )

        context.trade[
            "position_management_startup_gate"
        ] = {
            "checked": True,
            "ready": True,
            "startup_blocked_items": (
                self._report.blocked
                if self._report is not None
                else 0
            ),
            "runtime_reason": result.reason,
        }

        return GatedPositionManagementResult(
            success=bool(result.success),
            attempted=bool(result.attempted),
            reason=result.reason,
            runtime_result=result,
            diagnostics={
                "startup_gate_ready": True,
                "broker_management_call_performed": bool(
                    result.diagnostics.get(
                        "broker_call_performed",
                        result.attempted,
                    )
                ),
                "resubmission_performed": False,
            },
        )

    def _blocked(
        self,
        reason: str,
    ) -> GatedPositionManagementResult:
        return GatedPositionManagementResult(
            success=False,
            attempted=False,
            reason=reason,
            runtime_result=None,
            diagnostics={
                "startup_gate_ready": False,
                "broker_management_call_performed": False,
                "resubmission_performed": False,
            },
        )