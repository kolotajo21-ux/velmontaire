from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.context import StrategyContext
from .position_management import PositionManagementRequest
from .position_management_cycle import (
    PositionManagementCycleCoordinator,
    PositionManagementCycleResult,
)
from .position_management_journal import (
    PositionManagementJournal,
    PositionManagementJournalStatus,
)


@dataclass(slots=True)
class JournaledPositionManagementCycleResult:
    success: bool
    attempted: bool
    execution_id: str
    reason: str
    cycle_result: PositionManagementCycleResult | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)


class JournaledPositionManagementCycleCoordinator:
    """
    Day 73 crash-window protection.

    Day 75 extension:
    the durable INTENT now also stores enough request data to reconstruct
    the management request during startup recovery.

    Critical order:
        1. persist INTENT
        2. call Day 71 management cycle
        3. persist COMPLETED / FAILED
    """

    def __init__(
        self,
        *,
        cycle: PositionManagementCycleCoordinator,
        journal: PositionManagementJournal,
    ) -> None:
        self.cycle = cycle
        self.journal = journal

    def execute(
        self,
        request: PositionManagementRequest,
        context: StrategyContext,
    ) -> JournaledPositionManagementCycleResult:
        execution_id = str(request.execution_id).strip()

        if not execution_id:
            return self._blocked(
                "",
                "position_management_execution_id_missing",
                request_key=None,
            )

        request_key = self.cycle._request_key(request)
        existing = self.journal.get(request_key)

        if existing is not None:
            if existing.status == PositionManagementJournalStatus.COMPLETED:
                return self._blocked(
                    execution_id,
                    "position_management_request_already_completed_journaled",
                    request_key=request_key,
                    success=True,
                )

            if existing.status == PositionManagementJournalStatus.INTENT:
                return self._blocked(
                    execution_id,
                    "position_management_unresolved_intent_requires_reconciliation",
                    request_key=request_key,
                )

            # FAILED remains explicitly retryable.
            existing.status = PositionManagementJournalStatus.INTENT
            existing.metadata.update(
                self._request_metadata(request)
            )

            data = self.journal._load()
            data[request_key] = existing.to_dict()
            self.journal._atomic_write(data)

        else:
            self.journal.begin(
                request_key=request_key,
                execution_id=execution_id,
                action=request.action.value,
                metadata=self._request_metadata(
                    request
                ),
            )

        result = self.cycle.execute(
            request,
            context,
        )

        if result.success:
            self.journal.mark_completed(
                request_key=request_key,
                metadata={
                    "reason": result.reason,
                    "success": True,
                },
            )
        else:
            self.journal.mark_failed(
                request_key=request_key,
                metadata={
                    "reason": result.reason,
                    "success": False,
                },
            )

        context.trade["position_management_journal"] = {
            "request_key": request_key,
            "status": (
                PositionManagementJournalStatus.COMPLETED.value
                if result.success
                else PositionManagementJournalStatus.FAILED.value
            ),
        }

        return JournaledPositionManagementCycleResult(
            success=bool(result.success),
            attempted=bool(result.attempted),
            execution_id=execution_id,
            reason=result.reason,
            cycle_result=result,
            diagnostics={
                "request_key": request_key,
                "journal_intent_written_before_broker": True,
                "broker_call_performed": bool(result.attempted),
                "resubmission_performed": False,
            },
        )

    @staticmethod
    def _request_metadata(
        request: PositionManagementRequest,
    ) -> dict[str, Any]:
        return {
            "symbol": request.symbol,
            "broker_position_id": request.broker_position_id,
            "stop_loss": request.stop_loss,
            "take_profit": request.take_profit,
            "reason": request.reason,
            "request_metadata": dict(
                request.metadata
            ),
        }

    @staticmethod
    def _blocked(
        execution_id: str,
        reason: str,
        *,
        request_key: str | None,
        success: bool = False,
    ) -> JournaledPositionManagementCycleResult:
        return JournaledPositionManagementCycleResult(
            success=success,
            attempted=False,
            execution_id=execution_id,
            reason=reason,
            diagnostics={
                "request_key": request_key,
                "broker_call_performed": False,
                "resubmission_performed": False,
            },
        )