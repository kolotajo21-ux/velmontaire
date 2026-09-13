from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.context import StrategyContext
from .position_management import PositionManagementRequest
from .position_management_execution import (
    GenericPositionManagementExecutionBridge,
    PositionManagementExecutionResult,
)


@dataclass(slots=True)
class BoundPositionManagementResult:
    success: bool
    attempted: bool
    execution_id: str
    broker_position_id: str | None
    reason: str
    execution_result: PositionManagementExecutionResult | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": bool(self.success),
            "attempted": bool(self.attempted),
            "execution_id": self.execution_id,
            "broker_position_id": self.broker_position_id,
            "reason": self.reason,
            "execution_result": (
                self.execution_result.to_dict()
                if self.execution_result is not None
                else None
            ),
            "diagnostics": dict(self.diagnostics),
        }


class BoundPositionManagementExecutor:
    """
    Day 69 safety gate for live position management.

    Position-management actions are allowed only when StrategyContext
    contains a verified execution -> broker position binding produced
    by Day 68.

    Safety:
    - execution_id must match the bound execution;
    - broker_position_id must match the bound position;
    - position must still be OPEN;
    - position management must not be explicitly disabled;
    - no broker call occurs when any binding check fails.
    """

    def __init__(
        self,
        *,
        bridge: GenericPositionManagementExecutionBridge,
    ) -> None:
        self.bridge = bridge

    def execute(
        self,
        request: PositionManagementRequest,
        context: StrategyContext,
    ) -> BoundPositionManagementResult:
        if not isinstance(
            request,
            PositionManagementRequest,
        ):
            return self._blocked(
                execution_id="",
                broker_position_id=None,
                reason="position_management_request_required",
            )

        bound_execution_id = str(
            context.trade.get(
                "execution_id",
                "",
            )
        ).strip()

        bound_position_id = str(
            context.trade.get(
                "broker_position_id",
                "",
            )
        ).strip()

        binding_verified = (
            context.trade.get(
                "position_binding_verified"
            )
            is True
        )

        if not binding_verified:
            return self._blocked(
                execution_id=request.execution_id,
                broker_position_id=request.broker_position_id,
                reason="position_binding_not_verified",
            )

        if not bound_execution_id:
            return self._blocked(
                execution_id=request.execution_id,
                broker_position_id=request.broker_position_id,
                reason="bound_execution_id_missing",
            )

        if request.execution_id != bound_execution_id:
            return self._blocked(
                execution_id=request.execution_id,
                broker_position_id=request.broker_position_id,
                reason="bound_execution_id_mismatch",
            )

        if not bound_position_id:
            return self._blocked(
                execution_id=request.execution_id,
                broker_position_id=request.broker_position_id,
                reason="bound_broker_position_id_missing",
            )

        if not request.broker_position_id:
            return self._blocked(
                execution_id=request.execution_id,
                broker_position_id=None,
                reason="request_broker_position_id_missing",
            )

        if str(
            request.broker_position_id
        ).strip() != bound_position_id:
            return self._blocked(
                execution_id=request.execution_id,
                broker_position_id=request.broker_position_id,
                reason="bound_broker_position_id_mismatch",
            )

        position_state = str(
            context.trade.get(
                "position_state",
                "",
            )
        ).strip().upper()

        if position_state != "OPEN":
            return self._blocked(
                execution_id=request.execution_id,
                broker_position_id=request.broker_position_id,
                reason="bound_position_not_open",
            )

        if (
            context.trade.get(
                "position_management_allowed"
            )
            is False
        ):
            return self._blocked(
                execution_id=request.execution_id,
                broker_position_id=request.broker_position_id,
                reason="position_management_disabled",
            )

        execution_result = self.bridge.execute(
            request,
            context,
        )

        context.trade[
            "bound_position_management"
        ] = {
            "execution_id": request.execution_id,
            "broker_position_id": request.broker_position_id,
            "binding_verified": True,
            "attempted": bool(
                execution_result.attempted
            ),
            "success": bool(
                execution_result.success
            ),
            "reason": execution_result.reason,
        }

        return BoundPositionManagementResult(
            success=bool(
                execution_result.success
            ),
            attempted=bool(
                execution_result.attempted
            ),
            execution_id=request.execution_id,
            broker_position_id=request.broker_position_id,
            reason=execution_result.reason,
            execution_result=execution_result,
            diagnostics={
                "binding_verified": True,
                "broker_call_performed": bool(
                    execution_result.diagnostics.get(
                        "broker_call_performed",
                        False,
                    )
                ),
            },
        )

    @staticmethod
    def _blocked(
        *,
        execution_id: str,
        broker_position_id: str | None,
        reason: str,
    ) -> BoundPositionManagementResult:
        return BoundPositionManagementResult(
            success=False,
            attempted=False,
            execution_id=execution_id,
            broker_position_id=broker_position_id,
            reason=reason,
            execution_result=None,
            diagnostics={
                "binding_verified": False,
                "broker_call_performed": False,
            },
        )