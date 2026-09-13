from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.execution_adapter import AdapterExecutionStatus
from infrastructure.execution_journal import (
    ExecutionJournal,
    ExecutionJournalEntry,
    ExecutionJournalStatus,
)


@dataclass(slots=True)
class BrokerReconciliationState:
    found: bool
    status: AdapterExecutionStatus | None = None
    broker_order_id: str | None = None
    broker_deal_id: str | None = None
    message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RecoveryItemResult:
    execution_id: str
    previous_status: str
    action: str
    final_status: str
    resolved: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "previous_status": self.previous_status,
            "action": self.action,
            "final_status": self.final_status,
            "resolved": self.resolved,
            "reason": self.reason,
        }


@dataclass(slots=True)
class RecoveryReport:
    scanned: int = 0
    confirmed: int = 0
    rejected: int = 0
    unresolved: int = 0
    results: list[RecoveryItemResult] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.unresolved == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "scanned": self.scanned,
            "confirmed": self.confirmed,
            "rejected": self.rejected,
            "unresolved": self.unresolved,
            "results": [x.to_dict() for x in self.results],
        }


class ExecutionRecoveryReconciler:
    """
    Day 56 crash recovery/reconciliation.

    The broker lookup object must expose:
        lookup_execution(
            execution_id=...,
            broker_order_id=...,
            symbol=...,
        )

    It must return BrokerReconciliationState (or None).

    Safety rule:
    unknown/ambiguous broker state is NEVER converted into permission
    to submit the same execution_id again.
    """

    def __init__(
        self,
        *,
        journal: ExecutionJournal,
        broker_lookup: Any,
    ) -> None:
        self.journal = journal
        self.broker_lookup = broker_lookup

    def reconcile(self) -> RecoveryReport:
        report = RecoveryReport()

        for entry in self.journal.unresolved():
            report.scanned += 1
            item = self._reconcile_entry(entry)
            report.results.append(item)

            if item.final_status == ExecutionJournalStatus.CONFIRMED.value:
                report.confirmed += 1
            elif item.final_status == ExecutionJournalStatus.REJECTED.value:
                report.rejected += 1
            else:
                report.unresolved += 1

        return report

    def _reconcile_entry(
        self,
        entry: ExecutionJournalEntry,
    ) -> RecoveryItemResult:
        state = self.broker_lookup.lookup_execution(
            execution_id=entry.execution_id,
            broker_order_id=entry.broker_order_id,
            symbol=entry.symbol,
        )

        # No trustworthy broker evidence: fail closed.
        if state is None or not state.found or state.status is None:
            return self._unchanged(
                entry,
                "broker_state_unknown_fail_closed",
            )

        if state.status in {
            AdapterExecutionStatus.ACCEPTED,
            AdapterExecutionStatus.SUBMITTED,
            AdapterExecutionStatus.FILLED,
            AdapterExecutionStatus.PARTIALLY_FILLED,
        }:
            self.journal.mark_confirmed(
                execution_id=entry.execution_id,
                broker_order_id=(
                    state.broker_order_id
                    or entry.broker_order_id
                ),
                broker_deal_id=state.broker_deal_id,
                metadata={
                    "reconciled": True,
                    "broker_status": state.status.value,
                    **dict(state.metadata),
                },
            )
            return RecoveryItemResult(
                execution_id=entry.execution_id,
                previous_status=entry.status.value,
                action="CONFIRM",
                final_status=ExecutionJournalStatus.CONFIRMED.value,
                resolved=True,
                reason=f"broker_execution_found:{state.status.value}",
            )

        if state.status in {
            AdapterExecutionStatus.REJECTED,
            AdapterExecutionStatus.CANCELLED,
            AdapterExecutionStatus.FAILED,
        }:
            self.journal.mark_rejected(
                execution_id=entry.execution_id,
                error=(
                    state.message
                    or f"broker_status:{state.status.value}"
                ),
                metadata={
                    "reconciled": True,
                    "broker_status": state.status.value,
                    **dict(state.metadata),
                },
            )
            return RecoveryItemResult(
                execution_id=entry.execution_id,
                previous_status=entry.status.value,
                action="REJECT",
                final_status=ExecutionJournalStatus.REJECTED.value,
                resolved=True,
                reason=f"broker_terminal_state:{state.status.value}",
            )

        return self._unchanged(
            entry,
            "unsupported_broker_state_fail_closed",
        )

    @staticmethod
    def _unchanged(
        entry: ExecutionJournalEntry,
        reason: str,
    ) -> RecoveryItemResult:
        return RecoveryItemResult(
            execution_id=entry.execution_id,
            previous_status=entry.status.value,
            action="KEEP_BLOCKED",
            final_status=entry.status.value,
            resolved=False,
            reason=reason,
        )