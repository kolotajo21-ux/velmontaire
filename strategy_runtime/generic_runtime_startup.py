from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .position_management_startup_gate import (
    PositionManagementStartupGateResult,
    PositionManagementStartupSafetyGate,
)


@dataclass(slots=True)
class RuntimeStartupResult:
    ready: bool
    reason: str
    position_management: PositionManagementStartupGateResult | None = None
    execution_recovery_ready: bool = True
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": bool(self.ready),
            "reason": self.reason,
            "position_management": (
                self.position_management.to_dict()
                if self.position_management is not None
                else None
            ),
            "execution_recovery_ready": bool(
                self.execution_recovery_ready
            ),
            "diagnostics": dict(self.diagnostics),
        }


class GenericRuntimeStartupOrchestrator:
    """
    Day 77 unified runtime startup safety orchestrator.

    Startup order:
        1. generic execution recovery/reconciliation
        2. position-management startup recovery/gate
        3. runtime READY only if both are safe

    Safety:
    - startup never submits a new entry;
    - unresolved execution recovery blocks runtime;
    - unresolved position-management recovery blocks runtime;
    - retryable management failures do not block runtime;
    - state is sticky: once startup failed, rerun is explicit via startup().
    """

    def __init__(
        self,
        *,
        execution_recovery: Any,
        position_management_gate: PositionManagementStartupSafetyGate,
    ) -> None:
        self.execution_recovery = execution_recovery
        self.position_management_gate = position_management_gate

        self._checked = False
        self._ready = False
        self._last_result: RuntimeStartupResult | None = None

    @property
    def checked(self) -> bool:
        return self._checked

    @property
    def ready(self) -> bool:
        return self._checked and self._ready

    @property
    def last_result(self) -> RuntimeStartupResult | None:
        return self._last_result

    def startup(self) -> RuntimeStartupResult:
        execution_report = self.execution_recovery.reconcile()

        execution_ready = bool(
            getattr(
                execution_report,
                "success",
                False,
            )
        )

        if not execution_ready:
            result = RuntimeStartupResult(
                ready=False,
                reason="execution_recovery_blocked_startup",
                position_management=None,
                execution_recovery_ready=False,
                diagnostics={
                    "entry_submission_performed": False,
                    "position_management_started": False,
                    "execution_unresolved": int(
                        getattr(
                            execution_report,
                            "unresolved",
                            0,
                        )
                    ),
                },
            )
            self._checked = True
            self._ready = False
            self._last_result = result
            return result

        management_result = (
            self.position_management_gate.startup()
        )

        ready = bool(
            execution_ready
            and management_result.ready
        )

        result = RuntimeStartupResult(
            ready=ready,
            reason=(
                "generic_runtime_startup_ready"
                if ready
                else "position_management_recovery_blocked_startup"
            ),
            position_management=management_result,
            execution_recovery_ready=execution_ready,
            diagnostics={
                "entry_submission_performed": False,
                "position_management_started": True,
                "execution_unresolved": int(
                    getattr(
                        execution_report,
                        "unresolved",
                        0,
                    )
                ),
                "management_blocked": int(
                    management_result
                    .recovery_report
                    .blocked
                ),
            },
        )

        self._checked = True
        self._ready = ready
        self._last_result = result

        return result

    def require_ready(self) -> None:
        if not self._checked:
            raise RuntimeError(
                "generic_runtime_startup_not_checked"
            )

        if not self._ready:
            raise RuntimeError(
                "generic_runtime_startup_not_ready"
            )