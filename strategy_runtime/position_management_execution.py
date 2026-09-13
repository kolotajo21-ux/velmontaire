from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.context import StrategyContext
from core.execution_adapter import AdapterExecutionResult
from .position_management import (
    PositionManagementAction,
    PositionManagementRequest,
)


@dataclass(slots=True)
class PositionManagementExecutionResult:
    success: bool
    attempted: bool
    action: str
    execution_id: str
    reason: str
    adapter_result: AdapterExecutionResult | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": bool(self.success),
            "attempted": bool(self.attempted),
            "action": self.action,
            "execution_id": self.execution_id,
            "reason": self.reason,
            "adapter_result": (
                self.adapter_result.to_dict()
                if self.adapter_result is not None
                else None
            ),
            "diagnostics": dict(self.diagnostics),
        }


class GenericPositionManagementExecutionBridge:
    """
    Day 60 position-management execution bridge.

    MOVE_TO_BE / MOVE_SL / UPDATE_TP -> adapter.modify()
    CLOSE -> adapter.close_position()

    Pending-order cancel() is never used to close a live position.
    """

    def __init__(self, *, adapter: Any) -> None:
        self.adapter = adapter

    def execute(
        self,
        request: PositionManagementRequest,
        context: StrategyContext,
    ) -> PositionManagementExecutionResult:
        if not isinstance(request, PositionManagementRequest):
            return self._fail("", "UNKNOWN", "position_management_request_required")

        action = request.action.value

        if str(request.symbol).strip().upper() != str(context.symbol).strip().upper():
            return self._fail(
                request.execution_id,
                action,
                "position_management_symbol_context_mismatch",
            )

        if not request.execution_id:
            return self._fail(
                "",
                action,
                "position_management_execution_id_missing",
            )

        if request.action == PositionManagementAction.CLOSE:
            if not request.broker_position_id:
                return self._fail(
                    request.execution_id,
                    action,
                    "broker_position_id_required_for_close",
                )

            try:
                adapter_result = self.adapter.close_position(
                    execution_id=request.execution_id,
                    broker_position_id=request.broker_position_id,
                    symbol=request.symbol,
                    metadata={
                        "reason": request.reason,
                        **dict(request.metadata),
                    },
                )
            except NotImplementedError:
                return self._fail(
                    request.execution_id,
                    action,
                    "close_position_not_supported_by_execution_adapter",
                )
            except Exception as exc:
                context.add_error(
                    "position_close_execution",
                    f"{type(exc).__name__}:{exc}",
                )
                return PositionManagementExecutionResult(
                    success=False,
                    attempted=True,
                    action=action,
                    execution_id=request.execution_id,
                    reason="position_close_adapter_exception",
                    diagnostics={
                        "exception_type": type(exc).__name__,
                        "exception_message": str(exc),
                    },
                )

            return self._persist(
                request=request,
                context=context,
                adapter_result=adapter_result,
                success_reason="position_close_applied",
                reject_reason="position_close_rejected",
            )

        if request.action == PositionManagementAction.NONE:
            return self._fail(
                request.execution_id,
                action,
                "position_management_action_none",
            )

        if request.action not in {
            PositionManagementAction.MOVE_TO_BE,
            PositionManagementAction.MOVE_SL,
            PositionManagementAction.UPDATE_TP,
        }:
            return self._fail(
                request.execution_id,
                action,
                "position_management_action_unsupported",
            )

        stop_loss = request.stop_loss
        take_profit = request.take_profit

        if request.action in {
            PositionManagementAction.MOVE_TO_BE,
            PositionManagementAction.MOVE_SL,
        }:
            if stop_loss is None or float(stop_loss) <= 0:
                return self._fail(
                    request.execution_id,
                    action,
                    "position_management_stop_loss_invalid",
                )

        if request.action == PositionManagementAction.UPDATE_TP:
            if take_profit is None or float(take_profit) <= 0:
                return self._fail(
                    request.execution_id,
                    action,
                    "position_management_take_profit_invalid",
                )

        try:
            adapter_result = self.adapter.modify(
                execution_id=request.execution_id,
                broker_position_id=request.broker_position_id,
                stop_loss=float(stop_loss) if stop_loss is not None else None,
                take_profit=float(take_profit) if take_profit is not None else None,
            )
        except Exception as exc:
            context.add_error(
                "position_management_execution",
                f"{type(exc).__name__}:{exc}",
            )
            return PositionManagementExecutionResult(
                success=False,
                attempted=True,
                action=action,
                execution_id=request.execution_id,
                reason="position_management_adapter_exception",
                diagnostics={
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                },
            )

        return self._persist(
            request=request,
            context=context,
            adapter_result=adapter_result,
            success_reason="position_management_applied",
            reject_reason="position_management_rejected",
        )

    @staticmethod
    def _persist(
        *,
        request: PositionManagementRequest,
        context: StrategyContext,
        adapter_result: AdapterExecutionResult,
        success_reason: str,
        reject_reason: str,
    ) -> PositionManagementExecutionResult:
        context.trade["position_management_execution"] = {
            "request": request.to_dict(),
            "adapter_result": (
                adapter_result.to_dict()
                if hasattr(adapter_result, "to_dict")
                else None
            ),
        }

        return PositionManagementExecutionResult(
            success=bool(adapter_result.success),
            attempted=True,
            action=request.action.value,
            execution_id=request.execution_id,
            reason=(
                success_reason
                if adapter_result.success
                else reject_reason
            ),
            adapter_result=adapter_result,
            diagnostics={
                "adapter": getattr(adapter_result, "adapter", None),
                "broker_call_performed": True,
            },
        )

    @staticmethod
    def _fail(
        execution_id: str,
        action: str,
        reason: str,
    ) -> PositionManagementExecutionResult:
        return PositionManagementExecutionResult(
            success=False,
            attempted=False,
            action=action,
            execution_id=execution_id,
            reason=reason,
            adapter_result=None,
            diagnostics={
                "broker_call_performed": False,
            },
        )