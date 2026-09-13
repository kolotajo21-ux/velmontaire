from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.context import StrategyContext
from core.execution_adapter import AdapterExecutionStatus
from infrastructure.execution_journal import ExecutionJournal
from strategy_runtime.execution_lifecycle import (
    GenericExecutionLifecycle,
    RuntimeExecutionState,
)
from strategy_runtime.execution_lifecycle_sync import (
    BrokerExecutionSnapshot,
)


@dataclass(slots=True)
class MT5UnifiedStateSyncResult:
    execution_id: str

    success: bool
    found: bool

    previous_state: RuntimeExecutionState
    new_state: RuntimeExecutionState

    broker_status: AdapterExecutionStatus | None = None
    broker_order_id: str | None = None
    broker_deal_id: str | None = None

    reason: str = ""

    diagnostics: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "success": bool(self.success),
            "found": bool(self.found),
            "previous_state": self.previous_state.value,
            "new_state": self.new_state.value,
            "broker_status": (
                self.broker_status.value
                if self.broker_status is not None
                else None
            ),
            "broker_order_id": self.broker_order_id,
            "broker_deal_id": self.broker_deal_id,
            "reason": self.reason,
            "diagnostics": dict(
                self.diagnostics
            ),
        }


class MT5UnifiedStateSync:
    """
    Day 67 unified MT5 execution-state synchronization.

    Responsibilities:

    MT5ExecutionReader
        ->
    BrokerExecutionSnapshot
        ->
    GenericExecutionLifecycle
        ->
    ExecutionJournal
        ->
    StrategyContext

    Important safety rules:

    - read-only broker inspection;
    - never submits an execution;
    - never retries an execution;
    - unknown broker state fails closed;
    - invalid lifecycle transitions remain blocked;
    - journal remains the crash-safe source of truth.
    """

    def __init__(
        self,
        *,
        reader: Any,
        journal: ExecutionJournal,
        lifecycle: GenericExecutionLifecycle | None = None,
    ) -> None:
        self.reader = reader
        self.journal = journal

        self.lifecycle = (
            lifecycle
            if lifecycle is not None
            else GenericExecutionLifecycle(
                journal=journal
            )
        )

    def sync(
        self,
        *,
        execution_id: str,
        broker_order_id: str | None = None,
        context: StrategyContext | None = None,
    ) -> MT5UnifiedStateSyncResult:
        execution_id = str(
            execution_id
        ).strip()

        if not execution_id:
            raise ValueError(
                "execution_id is required"
            )

        previous_state = (
            self.lifecycle.state(
                execution_id
            )
        )

        snapshot = self._read_snapshot(
            execution_id=execution_id,
            broker_order_id=broker_order_id,
        )

        if snapshot is None:
            return self._blocked(
                execution_id=execution_id,
                previous_state=previous_state,
                reason="broker_snapshot_missing",
                broker_order_id=broker_order_id,
                context=context,
            )

        if not snapshot.found:
            return self._blocked(
                execution_id=execution_id,
                previous_state=previous_state,
                reason="broker_execution_not_found",
                broker_order_id=(
                    snapshot.broker_order_id
                    or broker_order_id
                ),
                context=context,
                diagnostics={
                    "snapshot_metadata": dict(
                        snapshot.metadata
                    ),
                },
            )

        if snapshot.status is None:
            return self._blocked(
                execution_id=execution_id,
                previous_state=previous_state,
                reason="broker_status_unknown",
                broker_order_id=(
                    snapshot.broker_order_id
                    or broker_order_id
                ),
                context=context,
                diagnostics={
                    "snapshot_metadata": dict(
                        snapshot.metadata
                    ),
                },
            )

        lifecycle_result = (
            self.lifecycle.apply_broker_status(
                execution_id=execution_id,
                broker_status=snapshot.status,
                broker_order_id=(
                    snapshot.broker_order_id
                    or broker_order_id
                ),
                broker_deal_id=(
                    snapshot.broker_deal_id
                ),
                context=context,
                metadata={
                    "mt5_state_sync": True,
                    **dict(snapshot.metadata),
                },
            )
        )

        if not lifecycle_result.accepted:
            return MT5UnifiedStateSyncResult(
                execution_id=execution_id,
                success=False,
                found=True,
                previous_state=previous_state,
                new_state=(
                    lifecycle_result.new_state
                ),
                broker_status=snapshot.status,
                broker_order_id=(
                    snapshot.broker_order_id
                    or broker_order_id
                ),
                broker_deal_id=(
                    snapshot.broker_deal_id
                ),
                reason=(
                    lifecycle_result.reason
                ),
                diagnostics={
                    "broker_call_performed": False,
                    "resubmission_performed": False,
                    "lifecycle_transition_accepted": False,
                    "snapshot_metadata": dict(
                        snapshot.metadata
                    ),
                },
            )

        new_state = self.lifecycle.state(
            execution_id
        )

        self._persist_context(
            context=context,
            execution_id=execution_id,
            found=True,
            previous_state=previous_state,
            new_state=new_state,
            broker_status=snapshot.status,
            broker_order_id=(
                snapshot.broker_order_id
                or broker_order_id
            ),
            broker_deal_id=(
                snapshot.broker_deal_id
            ),
            reason="mt5_execution_state_synchronized",
        )

        return MT5UnifiedStateSyncResult(
            execution_id=execution_id,
            success=True,
            found=True,
            previous_state=previous_state,
            new_state=new_state,
            broker_status=snapshot.status,
            broker_order_id=(
                snapshot.broker_order_id
                or broker_order_id
            ),
            broker_deal_id=(
                snapshot.broker_deal_id
            ),
            reason=(
                "mt5_execution_state_synchronized"
            ),
            diagnostics={
                "broker_call_performed": False,
                "resubmission_performed": False,
                "lifecycle_transition_accepted": True,
                "snapshot_metadata": dict(
                    snapshot.metadata
                ),
            },
        )

    def _read_snapshot(
        self,
        *,
        execution_id: str,
        broker_order_id: str | None,
    ) -> BrokerExecutionSnapshot | None:
        try:
            snapshot = self.reader.get_execution(
                execution_id=execution_id,
                broker_order_id=broker_order_id,
            )
        except Exception:
            return None

        if snapshot is None:
            return None

        if not isinstance(
            snapshot,
            BrokerExecutionSnapshot,
        ):
            return None

        return snapshot

    def _blocked(
        self,
        *,
        execution_id: str,
        previous_state: RuntimeExecutionState,
        reason: str,
        broker_order_id: str | None,
        context: StrategyContext | None,
        diagnostics: dict[str, Any] | None = None,
    ) -> MT5UnifiedStateSyncResult:
        self._persist_context(
            context=context,
            execution_id=execution_id,
            found=False,
            previous_state=previous_state,
            new_state=previous_state,
            broker_status=None,
            broker_order_id=broker_order_id,
            broker_deal_id=None,
            reason=reason,
        )

        return MT5UnifiedStateSyncResult(
            execution_id=execution_id,
            success=False,
            found=False,
            previous_state=previous_state,
            new_state=previous_state,
            broker_status=None,
            broker_order_id=broker_order_id,
            broker_deal_id=None,
            reason=reason,
            diagnostics={
                "broker_call_performed": False,
                "resubmission_performed": False,
                "fail_closed": True,
                **dict(diagnostics or {}),
            },
        )

    @staticmethod
    def _persist_context(
        *,
        context: StrategyContext | None,
        execution_id: str,
        found: bool,
        previous_state: RuntimeExecutionState,
        new_state: RuntimeExecutionState,
        broker_status: AdapterExecutionStatus | None,
        broker_order_id: str | None,
        broker_deal_id: str | None,
        reason: str,
    ) -> None:
        if context is None:
            return

        context.trade[
            "mt5_execution_state_sync"
        ] = {
            "execution_id": execution_id,
            "found": found,
            "previous_state": (
                previous_state.value
            ),
            "new_state": new_state.value,
            "broker_status": (
                broker_status.value
                if broker_status is not None
                else None
            ),
            "broker_order_id": (
                broker_order_id
            ),
            "broker_deal_id": (
                broker_deal_id
            ),
            "reason": reason,
        }