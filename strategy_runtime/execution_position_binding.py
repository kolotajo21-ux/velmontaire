from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.context import StrategyContext
from infrastructure.execution_journal import ExecutionJournal
from strategy_runtime.position_reconciliation import (
    BrokerPositionSnapshot,
    BrokerPositionStatus,
)


@dataclass(slots=True)
class ExecutionPositionBindingResult:
    success: bool
    bound: bool
    execution_id: str
    broker_order_id: str | None
    broker_deal_id: str | None
    broker_position_id: str | None
    reason: str
    snapshot: BrokerPositionSnapshot | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": bool(self.success),
            "bound": bool(self.bound),
            "execution_id": self.execution_id,
            "broker_order_id": self.broker_order_id,
            "broker_deal_id": self.broker_deal_id,
            "broker_position_id": self.broker_position_id,
            "reason": self.reason,
            "snapshot": (
                self.snapshot.to_dict()
                if self.snapshot is not None
                else None
            ),
            "diagnostics": dict(self.diagnostics),
        }


class MT5ExecutionPositionBinder:
    """
    Day 68 execution -> live position binding.

    position_lookup contract:
        resolve_position_id(
            execution_id=...,
            broker_order_id=...,
            broker_deal_id=...,
            symbol=...,
        ) -> str | int | None

    position_reader contract:
        get_position(
            broker_position_id=...,
            symbol=...,
        ) -> BrokerPositionSnapshot | None

    Safety:
    - never guesses by symbol alone;
    - journal IDs are the source binding evidence;
    - missing/ambiguous identity fails closed;
    - only OPEN broker position can be bound.
    """

    def __init__(
        self,
        *,
        journal: ExecutionJournal,
        position_lookup: Any,
        position_reader: Any,
    ) -> None:
        self.journal = journal
        self.position_lookup = position_lookup
        self.position_reader = position_reader

    def bind(
        self,
        *,
        execution_id: str,
        context: StrategyContext,
    ) -> ExecutionPositionBindingResult:
        execution_id = str(execution_id).strip()

        if not execution_id:
            raise ValueError("execution_id is required")

        entry = self.journal.get(execution_id)

        if entry is None:
            return self._fail(
                execution_id=execution_id,
                reason="execution_not_found_in_journal",
            )

        broker_order_id = entry.broker_order_id
        broker_deal_id = entry.broker_deal_id

        if not broker_order_id and not broker_deal_id:
            return self._fail(
                execution_id=execution_id,
                reason="execution_has_no_broker_identity",
            )

        try:
            resolved = self.position_lookup.resolve_position_id(
                execution_id=execution_id,
                broker_order_id=broker_order_id,
                broker_deal_id=broker_deal_id,
                symbol=context.symbol,
            )
        except Exception as exc:
            return self._fail(
                execution_id=execution_id,
                reason="position_id_resolution_failed",
                broker_order_id=broker_order_id,
                broker_deal_id=broker_deal_id,
                diagnostics={
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                },
            )

        if resolved in (None, "", 0, "0"):
            return self._fail(
                execution_id=execution_id,
                reason="broker_position_id_unresolved",
                broker_order_id=broker_order_id,
                broker_deal_id=broker_deal_id,
            )

        broker_position_id = str(resolved)

        try:
            snapshot = self.position_reader.get_position(
                broker_position_id=broker_position_id,
                symbol=context.symbol,
            )
        except Exception as exc:
            return self._fail(
                execution_id=execution_id,
                reason="broker_position_read_failed",
                broker_order_id=broker_order_id,
                broker_deal_id=broker_deal_id,
                broker_position_id=broker_position_id,
                diagnostics={
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                },
            )

        if snapshot is None:
            return self._fail(
                execution_id=execution_id,
                reason="broker_position_snapshot_missing",
                broker_order_id=broker_order_id,
                broker_deal_id=broker_deal_id,
                broker_position_id=broker_position_id,
            )

        if not isinstance(snapshot, BrokerPositionSnapshot):
            return self._fail(
                execution_id=execution_id,
                reason="broker_position_snapshot_invalid",
                broker_order_id=broker_order_id,
                broker_deal_id=broker_deal_id,
                broker_position_id=broker_position_id,
            )

        if snapshot.status != BrokerPositionStatus.OPEN or not snapshot.found:
            return self._fail(
                execution_id=execution_id,
                reason="broker_position_not_open",
                broker_order_id=broker_order_id,
                broker_deal_id=broker_deal_id,
                broker_position_id=broker_position_id,
                snapshot=snapshot,
            )

        if (
            snapshot.broker_position_id
            and str(snapshot.broker_position_id) != broker_position_id
        ):
            return self._fail(
                execution_id=execution_id,
                reason="broker_position_identity_mismatch",
                broker_order_id=broker_order_id,
                broker_deal_id=broker_deal_id,
                broker_position_id=broker_position_id,
                snapshot=snapshot,
            )

        if (
            snapshot.symbol
            and snapshot.symbol.strip().upper()
            != context.symbol.strip().upper()
        ):
            return self._fail(
                execution_id=execution_id,
                reason="broker_position_symbol_mismatch",
                broker_order_id=broker_order_id,
                broker_deal_id=broker_deal_id,
                broker_position_id=broker_position_id,
                snapshot=snapshot,
            )

        context.trade.update({
            "execution_id": execution_id,
            "broker_order_id": broker_order_id,
            "broker_deal_id": broker_deal_id,
            "broker_position_id": broker_position_id,
            "position_state": "OPEN",
            "position_binding_verified": True,
            "broker_position_state": snapshot.to_dict(),
        })

        return ExecutionPositionBindingResult(
            success=True,
            bound=True,
            execution_id=execution_id,
            broker_order_id=broker_order_id,
            broker_deal_id=broker_deal_id,
            broker_position_id=broker_position_id,
            reason="execution_position_bound",
            snapshot=snapshot,
            diagnostics={
                "guessed_by_symbol": False,
            },
        )

    @staticmethod
    def _fail(
        *,
        execution_id: str,
        reason: str,
        broker_order_id: str | None = None,
        broker_deal_id: str | None = None,
        broker_position_id: str | None = None,
        snapshot: BrokerPositionSnapshot | None = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> ExecutionPositionBindingResult:
        return ExecutionPositionBindingResult(
            success=False,
            bound=False,
            execution_id=execution_id,
            broker_order_id=broker_order_id,
            broker_deal_id=broker_deal_id,
            broker_position_id=broker_position_id,
            reason=reason,
            snapshot=snapshot,
            diagnostics={
                "guessed_by_symbol": False,
                **dict(diagnostics or {}),
            },
        )