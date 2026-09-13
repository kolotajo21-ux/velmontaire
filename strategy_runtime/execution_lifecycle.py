from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.context import StrategyContext
from core.execution_adapter import AdapterExecutionStatus
from infrastructure.execution_journal import (
    ExecutionJournal,
    ExecutionJournalStatus,
)


class RuntimeExecutionState(str, Enum):
    READY = "READY"
    SUBMISSION_INTENT = "SUBMISSION_INTENT"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


@dataclass(slots=True)
class ExecutionLifecycleResult:
    execution_id: str
    previous_state: RuntimeExecutionState
    new_state: RuntimeExecutionState
    accepted: bool
    terminal: bool
    reason: str
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "previous_state": self.previous_state.value,
            "new_state": self.new_state.value,
            "accepted": bool(self.accepted),
            "terminal": bool(self.terminal),
            "reason": self.reason,
            "diagnostics": dict(self.diagnostics),
        }


class GenericExecutionLifecycle:
    """
    Day 57 generic execution lifecycle.

    Tracks broker-facing execution state without re-submitting orders.

    Journal remains the crash-safe source of truth:
    - SUBMISSION_INTENT stays blocking;
    - SUBMITTED stays unresolved/blocking;
    - broker terminal success -> CONFIRMED;
    - broker terminal failure -> REJECTED;
    - detailed runtime state is persisted in journal metadata.
    """

    TERMINAL_STATES = {
        RuntimeExecutionState.FILLED,
        RuntimeExecutionState.CANCELLED,
        RuntimeExecutionState.REJECTED,
        RuntimeExecutionState.FAILED,
    }

    ALLOWED: dict[RuntimeExecutionState, set[RuntimeExecutionState]] = {
        RuntimeExecutionState.READY: {
            RuntimeExecutionState.SUBMISSION_INTENT,
        },
        RuntimeExecutionState.SUBMISSION_INTENT: {
            RuntimeExecutionState.SUBMITTED,
            RuntimeExecutionState.PARTIALLY_FILLED,
            RuntimeExecutionState.FILLED,
            RuntimeExecutionState.REJECTED,
            RuntimeExecutionState.FAILED,
        },
        RuntimeExecutionState.SUBMITTED: {
            RuntimeExecutionState.SUBMITTED,
            RuntimeExecutionState.PARTIALLY_FILLED,
            RuntimeExecutionState.FILLED,
            RuntimeExecutionState.CANCELLED,
            RuntimeExecutionState.REJECTED,
            RuntimeExecutionState.FAILED,
        },
        RuntimeExecutionState.PARTIALLY_FILLED: {
            RuntimeExecutionState.PARTIALLY_FILLED,
            RuntimeExecutionState.FILLED,
            RuntimeExecutionState.CANCELLED,
            RuntimeExecutionState.FAILED,
        },
        RuntimeExecutionState.FILLED: {
            RuntimeExecutionState.FILLED,
        },
        RuntimeExecutionState.CANCELLED: {
            RuntimeExecutionState.CANCELLED,
        },
        RuntimeExecutionState.REJECTED: {
            RuntimeExecutionState.REJECTED,
        },
        RuntimeExecutionState.FAILED: {
            RuntimeExecutionState.FAILED,
        },
        RuntimeExecutionState.UNKNOWN: set(),
    }

    def __init__(self, *, journal: ExecutionJournal) -> None:
        self.journal = journal

    def state(self, execution_id: str) -> RuntimeExecutionState:
        entry = self.journal.get(execution_id)
        if entry is None:
            return RuntimeExecutionState.READY

        metadata = entry.metadata or {}
        runtime_state = metadata.get("runtime_execution_state")

        if runtime_state is not None:
            try:
                return RuntimeExecutionState(str(runtime_state))
            except ValueError:
                return RuntimeExecutionState.UNKNOWN

        if entry.status == ExecutionJournalStatus.SUBMISSION_INTENT:
            return RuntimeExecutionState.SUBMISSION_INTENT
        if entry.status == ExecutionJournalStatus.SUBMITTED:
            return RuntimeExecutionState.SUBMITTED
        if entry.status == ExecutionJournalStatus.REJECTED:
            return RuntimeExecutionState.REJECTED
        if entry.status == ExecutionJournalStatus.CONFIRMED:
            broker_status = str(metadata.get("broker_status", "")).upper()
            if broker_status == AdapterExecutionStatus.FILLED.value:
                return RuntimeExecutionState.FILLED
            if broker_status == AdapterExecutionStatus.PARTIALLY_FILLED.value:
                return RuntimeExecutionState.PARTIALLY_FILLED
            return RuntimeExecutionState.SUBMITTED

        return RuntimeExecutionState.UNKNOWN

    def apply_broker_status(
        self,
        *,
        execution_id: str,
        broker_status: AdapterExecutionStatus,
        broker_order_id: str | None = None,
        broker_deal_id: str | None = None,
        message: str | None = None,
        context: StrategyContext | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ExecutionLifecycleResult:
        previous = self.state(execution_id)
        new_state = self._map_broker_status(broker_status)

        if new_state not in self.ALLOWED.get(previous, set()):
            return ExecutionLifecycleResult(
                execution_id=execution_id,
                previous_state=previous,
                new_state=previous,
                accepted=False,
                terminal=previous in self.TERMINAL_STATES,
                reason=(
                    "invalid_execution_state_transition:"
                    f"{previous.value}->{new_state.value}"
                ),
            )

        merged_metadata = {
            "runtime_execution_state": new_state.value,
            "broker_status": broker_status.value,
            **dict(metadata or {}),
        }

        if new_state in {
            RuntimeExecutionState.FILLED,
        }:
            self.journal.mark_confirmed(
                execution_id=execution_id,
                broker_order_id=broker_order_id,
                broker_deal_id=broker_deal_id,
                metadata=merged_metadata,
            )

        elif new_state in {
            RuntimeExecutionState.CANCELLED,
            RuntimeExecutionState.REJECTED,
            RuntimeExecutionState.FAILED,
        }:
            self.journal.mark_rejected(
                execution_id=execution_id,
                error=message or f"broker_status:{broker_status.value}",
                metadata=merged_metadata,
            )

        else:
            self.journal.mark_submitted(
                execution_id=execution_id,
                broker_order_id=broker_order_id,
                broker_deal_id=broker_deal_id,
                metadata=merged_metadata,
            )

        if context is not None:
            context.trade["execution_lifecycle"] = {
                "execution_id": execution_id,
                "state": new_state.value,
                "broker_status": broker_status.value,
                "broker_order_id": broker_order_id,
                "broker_deal_id": broker_deal_id,
            }

        return ExecutionLifecycleResult(
            execution_id=execution_id,
            previous_state=previous,
            new_state=new_state,
            accepted=True,
            terminal=new_state in self.TERMINAL_STATES,
            reason="execution_state_updated",
            diagnostics={
                "broker_call_performed": False,
            },
        )

    @staticmethod
    def _map_broker_status(
        status: AdapterExecutionStatus,
    ) -> RuntimeExecutionState:
        mapping = {
            AdapterExecutionStatus.ACCEPTED: RuntimeExecutionState.SUBMITTED,
            AdapterExecutionStatus.SUBMITTED: RuntimeExecutionState.SUBMITTED,
            AdapterExecutionStatus.PARTIALLY_FILLED: RuntimeExecutionState.PARTIALLY_FILLED,
            AdapterExecutionStatus.FILLED: RuntimeExecutionState.FILLED,
            AdapterExecutionStatus.CANCELLED: RuntimeExecutionState.CANCELLED,
            AdapterExecutionStatus.REJECTED: RuntimeExecutionState.REJECTED,
            AdapterExecutionStatus.FAILED: RuntimeExecutionState.FAILED,
        }
        return mapping[status]