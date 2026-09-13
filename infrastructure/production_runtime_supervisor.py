from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.context import StrategyContext


@dataclass(slots=True)
class ProductionRuntimeSupervisorStatus:
    boot_attempted: bool
    boot_ready: bool
    circuit_open: bool
    total_cycles: int
    successful_cycles: int
    failed_cycles: int
    consecutive_failures: int
    last_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "boot_attempted": bool(self.boot_attempted),
            "boot_ready": bool(self.boot_ready),
            "circuit_open": bool(self.circuit_open),
            "total_cycles": int(self.total_cycles),
            "successful_cycles": int(self.successful_cycles),
            "failed_cycles": int(self.failed_cycles),
            "consecutive_failures": int(
                self.consecutive_failures
            ),
            "last_reason": self.last_reason,
        }


@dataclass(slots=True)
class ProductionRuntimeSupervisorResult:
    success: bool
    attempted: bool
    blocked: bool
    reason: str
    runtime_result: Any = None
    status: ProductionRuntimeSupervisorStatus | None = None
    diagnostics: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": bool(self.success),
            "attempted": bool(self.attempted),
            "blocked": bool(self.blocked),
            "reason": self.reason,
            "runtime_result": (
                self.runtime_result.to_dict()
                if (
                    self.runtime_result is not None
                    and hasattr(
                        self.runtime_result,
                        "to_dict",
                    )
                )
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


class ProductionRuntimeStabilitySupervisor:
    """
    Day 96 outer stability boundary around ProductionLiveRuntime.

    This class adds no trading or broker behavior.

    Guarantees:
    - boot exceptions fail closed;
    - cycle exceptions never crash the application boundary;
    - no automatic retry/resubmission;
    - every external cycle is attempted at most once;
    - repeated failures open a circuit breaker;
    - open circuit blocks future cycles until explicit recovery reset;
    - one successful cycle clears the consecutive-failure counter;
    - supervisor itself never talks to MT5/broker.
    """

    def __init__(
        self,
        *,
        runtime: Any,
        max_consecutive_failures: int = 3,
    ) -> None:
        self.runtime = runtime
        self.max_consecutive_failures = int(
            max_consecutive_failures
        )

        if self.max_consecutive_failures <= 0:
            raise ValueError(
                "max_consecutive_failures_must_be_positive"
            )

        self._boot_attempted = False
        self._boot_ready = False
        self._circuit_open = False

        self._total_cycles = 0
        self._successful_cycles = 0
        self._failed_cycles = 0
        self._consecutive_failures = 0

        self._last_reason: str | None = None

    def boot(
        self,
    ) -> ProductionRuntimeSupervisorResult:
        self._boot_attempted = True

        try:
            result = self.runtime.boot()
        except Exception as exc:
            self._boot_ready = False
            self._last_reason = (
                "production_runtime_boot_exception"
            )

            return self._result(
                success=False,
                attempted=True,
                blocked=True,
                reason=self._last_reason,
                diagnostics={
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                    "automatic_retry_performed": False,
                    "resubmission_performed": False,
                    "broker_call_performed": False,
                },
            )

        self._boot_ready = bool(
            getattr(
                result,
                "ready",
                False,
            )
            and getattr(
                result,
                "cycle_allowed",
                False,
            )
        )

        self._last_reason = (
            "production_runtime_supervisor_ready"
            if self._boot_ready
            else "production_runtime_boot_blocked"
        )

        return self._result(
            success=self._boot_ready,
            attempted=True,
            blocked=not self._boot_ready,
            reason=self._last_reason,
            runtime_result=result,
            diagnostics={
                "automatic_retry_performed": False,
                "resubmission_performed": False,
                "broker_call_performed": False,
            },
        )

    def cycle(
        self,
        context: StrategyContext,
    ) -> ProductionRuntimeSupervisorResult:
        if not self._boot_attempted:
            self._last_reason = (
                "production_runtime_supervisor_not_booted"
            )
            return self._blocked_result(
                self._last_reason
            )

        if not self._boot_ready:
            self._last_reason = (
                "production_runtime_supervisor_not_ready"
            )
            return self._blocked_result(
                self._last_reason
            )

        if self._circuit_open:
            self._last_reason = (
                "production_runtime_circuit_open"
            )
            return self._blocked_result(
                self._last_reason
            )

        self._total_cycles += 1

        try:
            result = self.runtime.cycle(
                context
            )
        except Exception as exc:
            self._register_failure(
                "production_runtime_cycle_exception"
            )

            self._persist_context_status(
                context
            )

            return self._result(
                success=False,
                attempted=True,
                blocked=False,
                reason=(
                    "production_runtime_cycle_exception"
                ),
                diagnostics={
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                    "automatic_retry_performed": False,
                    "resubmission_performed": False,
                    "broker_call_performed": False,
                    "circuit_opened": bool(
                        self._circuit_open
                    ),
                },
            )

        success = bool(
            getattr(
                result,
                "success",
                False,
            )
        )

        attempted = bool(
            getattr(
                result,
                "attempted",
                False,
            )
        )

        reason = str(
            getattr(
                result,
                "reason",
                (
                    "production_runtime_cycle_completed"
                    if success
                    else "production_runtime_cycle_failed"
                ),
            )
        )

        if success:
            self._successful_cycles += 1
            self._consecutive_failures = 0
            self._last_reason = reason
        else:
            self._register_failure(
                reason
            )

        self._persist_context_status(
            context
        )

        return self._result(
            success=success,
            attempted=attempted,
            blocked=False,
            reason=reason,
            runtime_result=result,
            diagnostics={
                "automatic_retry_performed": False,
                "resubmission_performed": False,
                "broker_call_performed": False,
                "circuit_opened": bool(
                    self._circuit_open
                ),
            },
        )

    def reset_after_recovery(
        self,
        *,
        recovery_verified: bool,
    ) -> ProductionRuntimeSupervisorResult:
        if recovery_verified is not True:
            self._last_reason = (
                "runtime_recovery_not_verified"
            )
            return self._result(
                success=False,
                attempted=False,
                blocked=True,
                reason=self._last_reason,
                diagnostics={
                    "circuit_reset": False,
                    "automatic_retry_performed": False,
                    "resubmission_performed": False,
                    "broker_call_performed": False,
                },
            )

        self._circuit_open = False
        self._consecutive_failures = 0
        self._last_reason = (
            "runtime_recovery_reset_complete"
        )

        return self._result(
            success=True,
            attempted=False,
            blocked=False,
            reason=self._last_reason,
            diagnostics={
                "circuit_reset": True,
                "automatic_retry_performed": False,
                "resubmission_performed": False,
                "broker_call_performed": False,
            },
        )

    def status(
        self,
    ) -> ProductionRuntimeSupervisorStatus:
        return ProductionRuntimeSupervisorStatus(
            boot_attempted=self._boot_attempted,
            boot_ready=self._boot_ready,
            circuit_open=self._circuit_open,
            total_cycles=self._total_cycles,
            successful_cycles=(
                self._successful_cycles
            ),
            failed_cycles=self._failed_cycles,
            consecutive_failures=(
                self._consecutive_failures
            ),
            last_reason=self._last_reason,
        )

    def _register_failure(
        self,
        reason: str,
    ) -> None:
        self._failed_cycles += 1
        self._consecutive_failures += 1
        self._last_reason = str(
            reason
        )

        if (
            self._consecutive_failures
            >= self.max_consecutive_failures
        ):
            self._circuit_open = True

    def _persist_context_status(
        self,
        context: StrategyContext,
    ) -> None:
        context.diagnostics[
            "production_runtime_stability_supervisor"
        ] = self.status().to_dict()

    def _blocked_result(
        self,
        reason: str,
    ) -> ProductionRuntimeSupervisorResult:
        return self._result(
            success=False,
            attempted=False,
            blocked=True,
            reason=reason,
            diagnostics={
                "automatic_retry_performed": False,
                "resubmission_performed": False,
                "broker_call_performed": False,
            },
        )

    def _result(
        self,
        *,
        success: bool,
        attempted: bool,
        blocked: bool,
        reason: str,
        runtime_result: Any = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> ProductionRuntimeSupervisorResult:
        return ProductionRuntimeSupervisorResult(
            success=success,
            attempted=attempted,
            blocked=blocked,
            reason=reason,
            runtime_result=runtime_result,
            status=self.status(),
            diagnostics=dict(
                diagnostics or {}
            ),
        )