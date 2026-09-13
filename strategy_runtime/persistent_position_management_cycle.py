from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.context import StrategyContext
from .position_management import PositionManagementRequest
from .position_management_cycle import (
    PositionManagementCycleCoordinator,
    PositionManagementCycleResult,
)
from .position_management_state_store import (
    PositionManagementStateStore,
)


@dataclass(slots=True)
class PersistentPositionManagementCycleResult:
    success: bool
    attempted: bool
    execution_id: str
    reason: str
    cycle_result: PositionManagementCycleResult | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": bool(self.success),
            "attempted": bool(self.attempted),
            "execution_id": self.execution_id,
            "reason": self.reason,
            "cycle_result": (
                self.cycle_result.to_dict()
                if self.cycle_result is not None
                else None
            ),
            "diagnostics": dict(self.diagnostics),
        }


class PersistentPositionManagementCycleCoordinator:
    """
    Day 72 persistent idempotency wrapper.

    Extends Day 71 idempotency across process restart.

    Safety:
    - completed request key survives restart;
    - identical request after restart is blocked before broker call;
    - failed request is recorded but never marked completed;
    - StrategyContext is restored from persistent state.
    """

    def __init__(
        self,
        *,
        cycle: PositionManagementCycleCoordinator,
        store: PositionManagementStateStore,
    ) -> None:
        self.cycle = cycle
        self.store = store

    def execute(
        self,
        request: PositionManagementRequest,
        context: StrategyContext,
    ) -> PersistentPositionManagementCycleResult:
        execution_id = str(
            request.execution_id
        ).strip()

        if not execution_id:
            return PersistentPositionManagementCycleResult(
                success=False,
                attempted=False,
                execution_id="",
                reason="position_management_execution_id_missing",
                diagnostics={
                    "persistent_duplicate": False,
                    "broker_call_performed": False,
                },
            )

        request_key = self.cycle._request_key(
            request
        )

        persistent = self.store.get(
            execution_id
        )

        self._restore_context(
            context,
            persistent,
        )

        if (
            request_key
            in persistent.completed_request_keys
        ):
            return PersistentPositionManagementCycleResult(
                success=True,
                attempted=False,
                execution_id=execution_id,
                reason="position_management_request_already_completed_persisted",
                diagnostics={
                    "persistent_duplicate": True,
                    "request_key": request_key,
                    "broker_call_performed": False,
                    "resubmission_performed": False,
                },
            )

        result = self.cycle.execute(
            request,
            context,
        )

        if result.success:
            persistent = self.store.mark_completed(
                execution_id=execution_id,
                request_key=request_key,
                reason=result.reason,
                success=result.success,
                attempted=result.attempted,
            )
        else:
            persistent = self.store.record_attempt(
                execution_id=execution_id,
                request_key=request_key,
                reason=result.reason,
                success=result.success,
                attempted=result.attempted,
            )

        self._restore_context(
            context,
            persistent,
        )

        return PersistentPositionManagementCycleResult(
            success=bool(result.success),
            attempted=bool(result.attempted),
            execution_id=execution_id,
            reason=result.reason,
            cycle_result=result,
            diagnostics={
                "persistent_duplicate": False,
                "request_key": request_key,
                "broker_call_performed": bool(
                    result.attempted
                ),
                "resubmission_performed": False,
            },
        )

    @staticmethod
    def _restore_context(
        context: StrategyContext,
        persistent: Any,
    ) -> None:
        context.trade[
            "position_management_cycle"
        ] = {
            "completed_request_keys": list(
                persistent.completed_request_keys
            ),
            "last_request_key": (
                persistent.last_request_key
            ),
            "last_reason": persistent.last_reason,
            "last_success": (
                persistent.last_success
            ),
            "last_attempted": (
                persistent.last_attempted
            ),
        }