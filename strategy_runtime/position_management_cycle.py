from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.context import StrategyContext
from .position_management import PositionManagementRequest
from .live_position_management_runtime import (
    LivePositionManagementRuntime,
    LivePositionManagementRuntimeResult,
)


@dataclass(slots=True)
class PositionManagementCycleResult:
    success: bool
    attempted: bool
    execution_id: str
    reason: str
    runtime_result: LivePositionManagementRuntimeResult | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": bool(self.success),
            "attempted": bool(self.attempted),
            "execution_id": self.execution_id,
            "reason": self.reason,
            "runtime_result": (
                self.runtime_result.to_dict()
                if self.runtime_result is not None
                else None
            ),
            "diagnostics": dict(self.diagnostics),
        }


class PositionManagementCycleCoordinator:
    """
    Day 71 idempotent position-management cycle coordinator.

    Prevents the same management request from being executed repeatedly
    during repeated runtime ticks.

    Request identity is derived from:
      execution_id + broker_position_id + action + SL + TP.

    Safety:
    - identical successful request -> skipped;
    - failed/blocked request is not marked completed;
    - different SL/TP/action remains a new request;
    - coordinator never submits or resubmits an entry execution.
    """

    def __init__(
        self,
        *,
        runtime: LivePositionManagementRuntime,
    ) -> None:
        self.runtime = runtime

    def execute(
        self,
        request: PositionManagementRequest,
        context: StrategyContext,
    ) -> PositionManagementCycleResult:
        if not isinstance(request, PositionManagementRequest):
            return PositionManagementCycleResult(
                success=False,
                attempted=False,
                execution_id="",
                reason="position_management_request_required",
                diagnostics={
                    "duplicate": False,
                    "resubmission_performed": False,
                },
            )

        request_key = self._request_key(request)

        state = context.trade.setdefault(
            "position_management_cycle",
            {},
        )

        completed = state.setdefault(
            "completed_request_keys",
            [],
        )

        if request_key in completed:
            return PositionManagementCycleResult(
                success=True,
                attempted=False,
                execution_id=request.execution_id,
                reason="position_management_request_already_completed",
                diagnostics={
                    "duplicate": True,
                    "request_key": request_key,
                    "resubmission_performed": False,
                },
            )

        result = self.runtime.execute(
            request,
            context,
        )

        state["last_request_key"] = request_key
        state["last_reason"] = result.reason
        state["last_success"] = bool(result.success)
        state["last_attempted"] = bool(result.attempted)

        if result.success:
            completed.append(request_key)

        return PositionManagementCycleResult(
            success=bool(result.success),
            attempted=bool(result.attempted),
            execution_id=request.execution_id,
            reason=result.reason,
            runtime_result=result,
            diagnostics={
                "duplicate": False,
                "request_key": request_key,
                "resubmission_performed": False,
            },
        )

    @staticmethod
    def _request_key(
        request: PositionManagementRequest,
    ) -> str:
        return "|".join([
            str(request.execution_id),
            str(request.broker_position_id or ""),
            str(request.action.value),
            PositionManagementCycleCoordinator._number(
                request.stop_loss
            ),
            PositionManagementCycleCoordinator._number(
                request.take_profit
            ),
        ])

    @staticmethod
    def _number(value: Any) -> str:
        if value is None:
            return ""
        try:
            return format(float(value), ".12g")
        except (TypeError, ValueError):
            return str(value)