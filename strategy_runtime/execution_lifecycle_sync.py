from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.context import StrategyContext
from core.execution_adapter import AdapterExecutionStatus
from infrastructure.execution_journal import ExecutionJournalStatus
from .execution_lifecycle import (
    ExecutionLifecycleResult,
    GenericExecutionLifecycle,
)


@dataclass(slots=True)
class BrokerExecutionSnapshot:
    found: bool
    status: AdapterExecutionStatus | None = None
    broker_order_id: str | None = None
    broker_deal_id: str | None = None
    message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "found": bool(self.found),
            "status": (
                self.status.value
                if self.status is not None
                else None
            ),
            "broker_order_id": self.broker_order_id,
            "broker_deal_id": self.broker_deal_id,
            "message": self.message,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class ExecutionLifecycleSyncResult:
    success: bool
    resolved: bool
    execution_id: str
    reason: str
    snapshot: BrokerExecutionSnapshot | None = None
    lifecycle_result: ExecutionLifecycleResult | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": bool(self.success),
            "resolved": bool(self.resolved),
            "execution_id": self.execution_id,
            "reason": self.reason,
            "snapshot": (
                self.snapshot.to_dict()
                if self.snapshot is not None
                else None
            ),
            "lifecycle_result": (
                self.lifecycle_result.to_dict()
                if self.lifecycle_result is not None
                else None
            ),
            "diagnostics": dict(self.diagnostics),
        }


class GenericExecutionLifecycleSynchronizer:
    """
    Day 65 broker -> runtime lifecycle synchronization.

    broker_reader contract:
        get_execution(
            execution_id=...,
            broker_order_id=...,
        ) -> BrokerExecutionSnapshot | None

    Safety:
    - unknown broker state never advances lifecycle;
    - duplicate/resubmission path is never called;
    - only GenericExecutionLifecycle mutates journal lifecycle state.
    """

    def __init__(
        self,
        *,
        lifecycle: GenericExecutionLifecycle,
        broker_reader: Any,
    ) -> None:
        self.lifecycle = lifecycle
        self.broker_reader = broker_reader

    def sync(
        self,
        *,
        execution_id: str,
        context: StrategyContext | None = None,
    ) -> ExecutionLifecycleSyncResult:
        entry = self.lifecycle.journal.get(
            execution_id
        )

        if entry is None:
            return self._blocked(
                execution_id,
                "execution_not_found_in_journal",
            )

        broker_order_id = entry.broker_order_id

        try:
            snapshot = self.broker_reader.get_execution(
                execution_id=execution_id,
                broker_order_id=broker_order_id,
            )
        except Exception as exc:
            if context is not None:
                context.add_error(
                    "execution_lifecycle_sync",
                    f"{type(exc).__name__}:{exc}",
                )

            return self._blocked(
                execution_id,
                "broker_execution_lookup_failed",
                diagnostics={
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                },
            )

        if snapshot is None:
            return self._blocked(
                execution_id,
                "broker_execution_state_unknown",
            )

        if not isinstance(
            snapshot,
            BrokerExecutionSnapshot,
        ):
            return self._blocked(
                execution_id,
                "broker_execution_snapshot_invalid",
            )

        if (
            not snapshot.found
            or snapshot.status is None
        ):
            return self._blocked(
                execution_id,
                "broker_execution_state_unknown",
                snapshot=snapshot,
            )

        lifecycle_result = (
            self.lifecycle.apply_broker_status(
                execution_id=execution_id,
                broker_status=snapshot.status,
                broker_order_id=(
                    snapshot.broker_order_id
                    or entry.broker_order_id
                ),
                broker_deal_id=(
                    snapshot.broker_deal_id
                    or entry.broker_deal_id
                ),
                message=snapshot.message,
                context=context,
                metadata={
                    "lifecycle_sync": True,
                    **dict(snapshot.metadata),
                },
            )
        )

        if not lifecycle_result.accepted:
            return ExecutionLifecycleSyncResult(
                success=False,
                resolved=False,
                execution_id=execution_id,
                reason=lifecycle_result.reason,
                snapshot=snapshot,
                lifecycle_result=lifecycle_result,
                diagnostics={
                    "broker_call_performed": False,
                    "resubmission_performed": False,
                },
            )

        if context is not None:
            context.trade[
                "execution_lifecycle_sync"
            ] = {
                "execution_id": execution_id,
                "broker_snapshot": snapshot.to_dict(),
                "runtime_state": (
                    lifecycle_result
                    .new_state
                    .value
                ),
            }

        return ExecutionLifecycleSyncResult(
            success=True,
            resolved=True,
            execution_id=execution_id,
            reason="execution_lifecycle_synchronized",
            snapshot=snapshot,
            lifecycle_result=lifecycle_result,
            diagnostics={
                "broker_call_performed": False,
                "resubmission_performed": False,
            },
        )

    @staticmethod
    def _blocked(
        execution_id: str,
        reason: str,
        snapshot: BrokerExecutionSnapshot | None = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> ExecutionLifecycleSyncResult:
        return ExecutionLifecycleSyncResult(
            success=False,
            resolved=False,
            execution_id=execution_id,
            reason=reason,
            snapshot=snapshot,
            lifecycle_result=None,
            diagnostics={
                "broker_call_performed": False,
                "resubmission_performed": False,
                **dict(diagnostics or {}),
            },
        )