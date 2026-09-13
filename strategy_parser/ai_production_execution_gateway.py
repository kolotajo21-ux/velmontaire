from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.context import StrategyContext
from core.execution_order import ExecutionOrder
from infrastructure.production_safety_gate import (
    ProductionSafetyGate,
    ProductionSafetyGateResult,
)
from strategy_runtime.submission_bridge import (
    GenericRuntimeSubmissionBridge,
    RuntimeSubmissionResult,
)


class AIExecutionMode(str, Enum):
    PAPER = "PAPER"
    LIVE = "LIVE"


@dataclass(slots=True)
class AIProductionExecutionResult:
    success: bool
    attempted: bool
    blocked: bool
    mode: AIExecutionMode
    execution_id: str
    reason: str
    safety: ProductionSafetyGateResult | None = None
    submission: RuntimeSubmissionResult | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": bool(self.success),
            "attempted": bool(self.attempted),
            "blocked": bool(self.blocked),
            "mode": self.mode.value,
            "execution_id": self.execution_id,
            "reason": self.reason,
            "safety": self.safety.to_dict() if self.safety else None,
            "submission": self.submission.to_dict() if self.submission else None,
            "diagnostics": dict(self.diagnostics),
        }


class AIProductionExecutionGateway:
    """
    Day 91 guarded boundary before GenericRuntimeSubmissionBridge.

    PAPER:
      validates order + identity + production safety, but never calls submitter.

    LIVE:
      fail-closed by default. It requires BOTH:
        - allow_live_submission=True configured on this gateway;
        - explicit live_authorization=True for this call.
      Only after ProductionSafetyGate approves may the existing submission
      bridge be invoked.

    No broker adapter is called directly by this class.
    """

    def __init__(
        self,
        *,
        submission_bridge: GenericRuntimeSubmissionBridge,
        safety_gate: ProductionSafetyGate | None = None,
        allow_live_submission: bool = False,
    ) -> None:
        self.submission_bridge = submission_bridge
        self.safety_gate = safety_gate or ProductionSafetyGate()
        self.allow_live_submission = bool(allow_live_submission)

    def execute(
        self,
        *,
        order: ExecutionOrder,
        context: StrategyContext,
        runtime_result: Any,
        mode: AIExecutionMode | str = AIExecutionMode.PAPER,
        live_authorization: bool = False,
        lock_acquired: bool | None = None,
        lock_required: bool = False,
    ) -> AIProductionExecutionResult:
        resolved_mode = self._mode(mode)

        if resolved_mode is None:
            return self._blocked(
                mode=AIExecutionMode.PAPER,
                order=order,
                reason="execution_mode_invalid",
            )

        if not isinstance(order, ExecutionOrder):
            return self._blocked(
                mode=resolved_mode,
                order=order,
                reason="execution_order_required",
            )

        valid, reason = order.validate()
        if not valid:
            return self._blocked(
                mode=resolved_mode,
                order=order,
                reason=f"execution_order_invalid:{reason}",
            )

        if (
            str(order.symbol).strip().upper()
            != str(context.symbol).strip().upper()
        ):
            return self._blocked(
                mode=resolved_mode,
                order=order,
                reason="execution_order_symbol_context_mismatch",
            )

        strategy_id = str(
            order.metadata.get("strategy_id", "")
        ).strip()

        if (
            not strategy_id
            or strategy_id
            != context.strategy.metadata.strategy_id
        ):
            return self._blocked(
                mode=resolved_mode,
                order=order,
                reason="execution_order_strategy_context_mismatch",
            )

        safety = self.safety_gate.evaluate(
            context=context,
            runtime_result=runtime_result,
            lock_acquired=lock_acquired,
            lock_required=lock_required,
        )

        context.trade["ai_production_safety_gate"] = safety.to_dict()

        if not safety.allowed:
            return AIProductionExecutionResult(
                success=False,
                attempted=False,
                blocked=True,
                mode=resolved_mode,
                execution_id=order.execution_id,
                reason="production_safety_gate_blocked",
                safety=safety,
                diagnostics={
                    "submission_bridge_called": False,
                    "broker_call_performed": False,
                    "live_authorized": False,
                },
            )

        if resolved_mode == AIExecutionMode.PAPER:
            context.trade["ai_execution_boundary"] = {
                "mode": AIExecutionMode.PAPER.value,
                "execution_id": order.execution_id,
                "safety_allowed": True,
                "submission_performed": False,
                "broker_call_performed": False,
            }

            return AIProductionExecutionResult(
                success=True,
                attempted=False,
                blocked=False,
                mode=resolved_mode,
                execution_id=order.execution_id,
                reason="paper_execution_approved_no_submission",
                safety=safety,
                diagnostics={
                    "submission_bridge_called": False,
                    "broker_call_performed": False,
                    "live_authorized": False,
                },
            )

        if not self.allow_live_submission:
            return AIProductionExecutionResult(
                success=False,
                attempted=False,
                blocked=True,
                mode=resolved_mode,
                execution_id=order.execution_id,
                reason="live_submission_disabled",
                safety=safety,
                diagnostics={
                    "submission_bridge_called": False,
                    "broker_call_performed": False,
                    "live_authorized": False,
                },
            )

        if live_authorization is not True:
            return AIProductionExecutionResult(
                success=False,
                attempted=False,
                blocked=True,
                mode=resolved_mode,
                execution_id=order.execution_id,
                reason="explicit_live_authorization_required",
                safety=safety,
                diagnostics={
                    "submission_bridge_called": False,
                    "broker_call_performed": False,
                    "live_authorized": False,
                },
            )

        submission = self.submission_bridge.submit(
            order,
            context,
        )

        context.trade["ai_execution_boundary"] = {
            "mode": AIExecutionMode.LIVE.value,
            "execution_id": order.execution_id,
            "safety_allowed": True,
            "submission_performed": bool(submission.attempted),
            "broker_call_performed": bool(
                submission.diagnostics.get("broker_called", False)
            ),
        }

        return AIProductionExecutionResult(
            success=bool(submission.success),
            attempted=bool(submission.attempted),
            blocked=bool(submission.blocked),
            mode=resolved_mode,
            execution_id=order.execution_id,
            reason=submission.reason,
            safety=safety,
            submission=submission,
            diagnostics={
                "submission_bridge_called": True,
                "broker_call_performed": bool(
                    submission.diagnostics.get("broker_called", False)
                ),
                "live_authorized": True,
            },
        )

    @staticmethod
    def _mode(value: AIExecutionMode | str) -> AIExecutionMode | None:
        if isinstance(value, AIExecutionMode):
            return value

        try:
            return AIExecutionMode(str(value).strip().upper())
        except ValueError:
            return None

    @staticmethod
    def _blocked(
        *,
        mode: AIExecutionMode,
        order: Any,
        reason: str,
    ) -> AIProductionExecutionResult:
        return AIProductionExecutionResult(
            success=False,
            attempted=False,
            blocked=True,
            mode=mode,
            execution_id=str(
                getattr(order, "execution_id", "")
            ),
            reason=reason,
            diagnostics={
                "submission_bridge_called": False,
                "broker_call_performed": False,
                "live_authorized": False,
            },
        )