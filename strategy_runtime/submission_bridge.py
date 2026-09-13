from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.context import StrategyContext
from core.execution_order import ExecutionOrder


@dataclass(slots=True)
class RuntimeSubmissionResult:
    success: bool
    attempted: bool
    blocked: bool
    execution_id: str
    journal_status: str | None = None
    reason: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": bool(self.success),
            "attempted": bool(self.attempted),
            "blocked": bool(self.blocked),
            "execution_id": self.execution_id,
            "journal_status": self.journal_status,
            "reason": self.reason,
            "diagnostics": dict(self.diagnostics),
        }


class GenericRuntimeSubmissionBridge:
    """
    Day 55 ExecutionOrder -> JournaledExecutionSubmitter bridge.

    This class does not bypass the existing crash-safe execution layer.
    All submissions must go through the supplied journaled submitter.
    """

    def __init__(
        self,
        *,
        submitter: Any,
    ) -> None:
        self.submitter = submitter

    def submit(
        self,
        order: ExecutionOrder,
        context: StrategyContext,
    ) -> RuntimeSubmissionResult:
        if not isinstance(order, ExecutionOrder):
            return self._fail(
                "",
                "execution_order_required",
            )

        valid, reason = order.validate()
        if not valid:
            return self._fail(
                order.execution_id,
                f"execution_order_invalid:{reason}",
            )

        if (
            str(context.symbol).strip().upper()
            != str(order.symbol).strip().upper()
        ):
            return self._fail(
                order.execution_id,
                "execution_order_symbol_context_mismatch",
            )

        strategy_id = str(
            order.metadata.get(
                "strategy_id",
                "",
            )
        ).strip()

        if (
            strategy_id
            and strategy_id
            != context.strategy.metadata.strategy_id
        ):
            return self._fail(
                order.execution_id,
                "execution_order_strategy_context_mismatch",
            )

        try:
            submission = self.submitter.submit(
                order
            )
        except Exception as exc:
            context.add_error(
                "journaled_execution_submitter",
                (
                    f"{type(exc).__name__}:"
                    f"{exc}"
                ),
            )
            return RuntimeSubmissionResult(
                success=False,
                attempted=True,
                blocked=False,
                execution_id=order.execution_id,
                journal_status=None,
                reason="journaled_submission_exception",
                diagnostics={
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                },
            )

        broker_result = getattr(
            submission,
            "broker_result",
            None,
        )

        broker_success = bool(
            getattr(
                broker_result,
                "success",
                False,
            )
        )

        blocked = bool(
            getattr(
                submission,
                "blocked_by_journal",
                False,
            )
        )

        attempted = bool(
            getattr(
                submission,
                "attempted",
                False,
            )
        )

        journal_status = getattr(
            submission,
            "journal_status",
            None,
        )

        context.trade[
            "journaled_submission"
        ] = (
            submission.to_dict()
            if hasattr(
                submission,
                "to_dict",
            )
            else {
                "execution_id": (
                    order.execution_id
                ),
                "attempted": attempted,
                "blocked_by_journal": blocked,
                "journal_status": journal_status,
            }
        )

        if blocked:
            return RuntimeSubmissionResult(
                success=False,
                attempted=False,
                blocked=True,
                execution_id=order.execution_id,
                journal_status=journal_status,
                reason="execution_journal_blocked",
                diagnostics={
                    "broker_called": False,
                },
            )

        if not attempted:
            return RuntimeSubmissionResult(
                success=False,
                attempted=False,
                blocked=False,
                execution_id=order.execution_id,
                journal_status=journal_status,
                reason="execution_not_attempted",
                diagnostics={
                    "broker_called": False,
                },
            )

        if broker_success:
            return RuntimeSubmissionResult(
                success=True,
                attempted=True,
                blocked=False,
                execution_id=order.execution_id,
                journal_status=journal_status,
                reason="execution_submitted",
                diagnostics={
                    "broker_called": True,
                },
            )

        return RuntimeSubmissionResult(
            success=False,
            attempted=True,
            blocked=False,
            execution_id=order.execution_id,
            journal_status=journal_status,
            reason="broker_rejected",
            diagnostics={
                "broker_called": True,
            },
        )

    @staticmethod
    def _fail(
        execution_id: str,
        reason: str,
    ) -> RuntimeSubmissionResult:
        return RuntimeSubmissionResult(
            success=False,
            attempted=False,
            blocked=False,
            execution_id=str(
                execution_id
            ),
            journal_status=None,
            reason=reason,
            diagnostics={
                "broker_called": False,
            },
        )