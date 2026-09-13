from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.context import StrategyContext
from .position_management import PositionManagementRequest
from .position_management_cycle import (
    PositionManagementCycleCoordinator,
)
from .position_management_journal import (
    PositionManagementJournal,
    PositionManagementJournalStatus,
)


class ManagementRecoveryState(str, Enum):
    NO_INTENT = "NO_INTENT"
    ALREADY_COMPLETED = "ALREADY_COMPLETED"
    RETRYABLE_FAILED = "RETRYABLE_FAILED"
    RECONCILED_COMPLETED = "RECONCILED_COMPLETED"
    RECONCILED_RETRYABLE = "RECONCILED_RETRYABLE"
    BLOCKED_UNKNOWN = "BLOCKED_UNKNOWN"


@dataclass(slots=True)
class ManagementRecoveryResult:
    success: bool
    retry_allowed: bool
    broker_call_performed: bool
    execution_id: str
    request_key: str
    state: ManagementRecoveryState
    reason: str
    diagnostics: dict[str, Any] = field(default_factory=dict)


class PositionManagementIntentRecovery:
    """
    Day 74 recovery for Day 73 unresolved management INTENTs.

    It NEVER repeats the original management action.

    Recovery asks a read-only verifier whether the intended post-condition
    is already true at the broker. Only a definite answer may resolve INTENT:
      True  -> COMPLETED
      False -> FAILED/retryable
      None  -> remain INTENT/fail closed
    """

    def __init__(
        self,
        *,
        journal: PositionManagementJournal,
        cycle: PositionManagementCycleCoordinator,
        verifier: Any,
    ) -> None:
        self.journal = journal
        self.cycle = cycle
        self.verifier = verifier

    def recover(
        self,
        request: PositionManagementRequest,
        context: StrategyContext,
    ) -> ManagementRecoveryResult:
        execution_id = str(request.execution_id).strip()
        request_key = self.cycle._request_key(request)

        entry = self.journal.get(request_key)

        if entry is None:
            return self._result(
                execution_id,
                request_key,
                ManagementRecoveryState.NO_INTENT,
                False,
                False,
                "position_management_intent_not_found",
            )

        if entry.status == PositionManagementJournalStatus.COMPLETED:
            return self._result(
                execution_id,
                request_key,
                ManagementRecoveryState.ALREADY_COMPLETED,
                True,
                False,
                "position_management_already_completed",
            )

        if entry.status == PositionManagementJournalStatus.FAILED:
            return self._result(
                execution_id,
                request_key,
                ManagementRecoveryState.RETRYABLE_FAILED,
                True,
                True,
                "position_management_failed_request_retryable",
            )

        try:
            verified = self.verifier.verify(
                request=request,
                context=context,
            )
        except Exception as exc:
            return self._result(
                execution_id,
                request_key,
                ManagementRecoveryState.BLOCKED_UNKNOWN,
                False,
                False,
                "position_management_recovery_verifier_exception",
                {
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                },
            )

        if verified is True:
            self.journal.mark_completed(
                request_key=request_key,
                metadata={
                    "recovered": True,
                    "recovery_verdict": "post_condition_satisfied",
                },
            )
            self._persist_context(
                context,
                request_key,
                "COMPLETED",
            )
            return self._result(
                execution_id,
                request_key,
                ManagementRecoveryState.RECONCILED_COMPLETED,
                True,
                False,
                "position_management_intent_reconciled_completed",
            )

        if verified is False:
            self.journal.mark_failed(
                request_key=request_key,
                metadata={
                    "recovered": True,
                    "recovery_verdict": "post_condition_not_satisfied",
                },
            )
            self._persist_context(
                context,
                request_key,
                "FAILED",
            )
            return self._result(
                execution_id,
                request_key,
                ManagementRecoveryState.RECONCILED_RETRYABLE,
                True,
                True,
                "position_management_intent_reconciled_retryable",
            )

        return self._result(
            execution_id,
            request_key,
            ManagementRecoveryState.BLOCKED_UNKNOWN,
            False,
            False,
            "position_management_recovery_unknown_fail_closed",
        )

    @staticmethod
    def _persist_context(
        context: StrategyContext,
        request_key: str,
        status: str,
    ) -> None:
        context.trade["position_management_recovery"] = {
            "request_key": request_key,
            "status": status,
        }

    @staticmethod
    def _result(
        execution_id: str,
        request_key: str,
        state: ManagementRecoveryState,
        success: bool,
        retry_allowed: bool,
        reason: str,
        extra: dict[str, Any] | None = None,
    ) -> ManagementRecoveryResult:
        diagnostics = {
            "original_management_resubmitted": False,
            "broker_call_performed": False,
        }
        diagnostics.update(dict(extra or {}))

        return ManagementRecoveryResult(
            success=success,
            retry_allowed=retry_allowed,
            broker_call_performed=False,
            execution_id=execution_id,
            request_key=request_key,
            state=state,
            reason=reason,
            diagnostics=diagnostics,
        )