from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.context import StrategyContext
from .bound_position_management import (
    BoundPositionManagementExecutor,
    BoundPositionManagementResult,
)
from .position_management import PositionManagementRequest


@dataclass(slots=True)
class LivePositionManagementRuntimeResult:
    success: bool
    attempted: bool
    execution_id: str
    broker_position_id: str | None
    reason: str
    management_result: BoundPositionManagementResult | None = None
    reconciliation_performed: bool = False
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": bool(self.success),
            "attempted": bool(self.attempted),
            "execution_id": self.execution_id,
            "broker_position_id": self.broker_position_id,
            "reason": self.reason,
            "management_result": (
                self.management_result.to_dict()
                if self.management_result is not None
                else None
            ),
            "reconciliation_performed": bool(
                self.reconciliation_performed
            ),
            "diagnostics": dict(self.diagnostics),
        }


class LivePositionManagementRuntime:
    """
    Day 70 unified live position-management runtime.

    Pipeline:
        verified binding
        -> broker management action
        -> read-only broker position reconciliation

    Safety:
    - Day 69 binding gate remains authoritative.
    - No reconciliation is attempted if no broker call occurred.
    - A successful broker action is not treated as final truth until
      the broker position is read back.
    - Reconciliation never submits/resubmits an execution.
    """

    def __init__(
        self,
        *,
        management_executor: BoundPositionManagementExecutor,
        position_reconciler: Any,
    ) -> None:
        self.management_executor = management_executor
        self.position_reconciler = position_reconciler

    def execute(
        self,
        request: PositionManagementRequest,
        context: StrategyContext,
    ) -> LivePositionManagementRuntimeResult:
        management = self.management_executor.execute(
            request,
            context,
        )

        if not management.attempted:
            return LivePositionManagementRuntimeResult(
                success=False,
                attempted=False,
                execution_id=management.execution_id,
                broker_position_id=management.broker_position_id,
                reason=management.reason,
                management_result=management,
                reconciliation_performed=False,
                diagnostics={
                    "broker_call_performed": False,
                    "resubmission_performed": False,
                },
            )

        if not management.success:
            return LivePositionManagementRuntimeResult(
                success=False,
                attempted=True,
                execution_id=management.execution_id,
                broker_position_id=management.broker_position_id,
                reason=management.reason,
                management_result=management,
                reconciliation_performed=False,
                diagnostics={
                    "broker_call_performed": True,
                    "resubmission_performed": False,
                },
            )

        try:
            reconciliation = self.position_reconciler.reconcile(
                context
            )
        except Exception as exc:
            context.add_error(
                "position_management_reconciliation",
                f"{type(exc).__name__}:{exc}",
            )
            return LivePositionManagementRuntimeResult(
                success=False,
                attempted=True,
                execution_id=management.execution_id,
                broker_position_id=management.broker_position_id,
                reason="post_management_reconciliation_exception",
                management_result=management,
                reconciliation_performed=True,
                diagnostics={
                    "broker_call_performed": True,
                    "resubmission_performed": False,
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                },
            )

        reconciliation_success = bool(
            getattr(reconciliation, "success", False)
        )

        context.trade[
            "live_position_management_runtime"
        ] = {
            "execution_id": management.execution_id,
            "broker_position_id": management.broker_position_id,
            "management_success": True,
            "reconciliation_success": reconciliation_success,
            "reconciliation_reason": getattr(
                reconciliation,
                "reason",
                None,
            ),
        }

        if not reconciliation_success:
            return LivePositionManagementRuntimeResult(
                success=False,
                attempted=True,
                execution_id=management.execution_id,
                broker_position_id=management.broker_position_id,
                reason="post_management_reconciliation_failed",
                management_result=management,
                reconciliation_performed=True,
                diagnostics={
                    "broker_call_performed": True,
                    "resubmission_performed": False,
                    "reconciliation_reason": getattr(
                        reconciliation,
                        "reason",
                        None,
                    ),
                },
            )

        return LivePositionManagementRuntimeResult(
            success=True,
            attempted=True,
            execution_id=management.execution_id,
            broker_position_id=management.broker_position_id,
            reason="position_management_applied_and_reconciled",
            management_result=management,
            reconciliation_performed=True,
            diagnostics={
                "broker_call_performed": True,
                "resubmission_performed": False,
                "reconciliation_reason": getattr(
                    reconciliation,
                    "reason",
                    None,
                ),
            },
        )