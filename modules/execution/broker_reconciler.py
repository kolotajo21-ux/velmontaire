from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.execution_state import ExecutionSnapshot
from execution_state.execution_state_reconciler import (
    ExecutionStateReconciler,
    ReconciliationIssueType,
    ReconciliationResult,
)


@dataclass(slots=True)
class BrokerReconciliationReport:
    reconciliation: ReconciliationResult

    candidate_execution_id: str | None = None
    duplicate_execution: bool = False

    matching_broker_order_ids: set[str] = field(
        default_factory=set
    )
    matching_broker_position_ids: set[str] = field(
        default_factory=set
    )

    persisted_order_ids: set[str] = field(
        default_factory=set
    )
    persisted_position_ids: set[str] = field(
        default_factory=set
    )

    @property
    def requires_recovery(self) -> bool:
        return not self.reconciliation.synchronized

    @property
    def broker_duplicate_detected(self) -> bool:
        dangerous = {
            ReconciliationIssueType.DUPLICATE_ORDER,
            ReconciliationIssueType.DUPLICATE_POSITION,
        }

        return any(
            issue.issue_type in dangerous
            for issue in self.reconciliation.issues
        )

    @property
    def can_submit_candidate(self) -> bool:
        return (
            not self.duplicate_execution
            and not self.broker_duplicate_detected
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "reconciliation": self.reconciliation.to_dict(),
            "candidate_execution_id": self.candidate_execution_id,
            "duplicate_execution": self.duplicate_execution,
            "can_submit_candidate": self.can_submit_candidate,
            "requires_recovery": self.requires_recovery,
            "broker_duplicate_detected": self.broker_duplicate_detected,
            "matching_broker_order_ids": sorted(
                self.matching_broker_order_ids
            ),
            "matching_broker_position_ids": sorted(
                self.matching_broker_position_ids
            ),
            "persisted_order_ids": sorted(
                self.persisted_order_ids
            ),
            "persisted_position_ids": sorted(
                self.persisted_position_ids
            ),
        }


class BrokerReconciler:
    """
    High-level broker reconciliation + duplicate submission protection.

    Reuses ExecutionStateReconciler for broker-ID reconciliation.

    It never sends, modifies, or cancels broker orders.
    """

    def __init__(
        self,
        reconciler: ExecutionStateReconciler | None = None,
    ) -> None:
        self.reconciler = (
            reconciler
            if reconciler is not None
            else ExecutionStateReconciler()
        )

    def reconcile(
        self,
        *,
        persisted_snapshot: dict[str, Any] | None,
        fresh_snapshot: ExecutionSnapshot,
        candidate_execution_id: str | None = None,
    ) -> BrokerReconciliationReport:
        persisted_order_ids = (
            self._broker_ids_from_snapshot_dict(
                persisted_snapshot,
                collection="orders",
                id_key="broker_order_id",
            )
        )

        persisted_position_ids = (
            self._broker_ids_from_snapshot_dict(
                persisted_snapshot,
                collection="positions",
                id_key="broker_position_id",
            )
        )

        reconciliation = self.reconciler.reconcile(
            snapshot=fresh_snapshot,
            known_order_ids=persisted_order_ids,
            known_position_ids=persisted_position_ids,
        )

        duplicate_execution = False
        matching_order_ids: set[str] = set()
        matching_position_ids: set[str] = set()

        normalized_candidate = self._normalize(
            candidate_execution_id
        )

        if normalized_candidate:
            for order in fresh_snapshot.orders:
                execution_id = self._normalize(
                    order.execution_id
                )

                if execution_id == normalized_candidate:
                    duplicate_execution = True
                    matching_order_ids.add(
                        str(order.broker_order_id)
                    )

            for position in fresh_snapshot.positions:
                position_execution_id = (
                    self._execution_id_from_metadata(
                        position.metadata
                    )
                )

                if (
                    position_execution_id
                    == normalized_candidate
                ):
                    duplicate_execution = True
                    matching_position_ids.add(
                        str(position.broker_position_id)
                    )

            persisted_execution_ids = (
                self._execution_ids_from_snapshot_dict(
                    persisted_snapshot
                )
            )

            if (
                normalized_candidate
                in persisted_execution_ids
            ):
                duplicate_execution = True

        return BrokerReconciliationReport(
            reconciliation=reconciliation,
            candidate_execution_id=(
                candidate_execution_id
            ),
            duplicate_execution=duplicate_execution,
            matching_broker_order_ids=(
                matching_order_ids
            ),
            matching_broker_position_ids=(
                matching_position_ids
            ),
            persisted_order_ids=(
                persisted_order_ids
            ),
            persisted_position_ids=(
                persisted_position_ids
            ),
        )

    @staticmethod
    def _broker_ids_from_snapshot_dict(
        snapshot: dict[str, Any] | None,
        *,
        collection: str,
        id_key: str,
    ) -> set[str]:
        if not isinstance(snapshot, dict):
            return set()

        items = snapshot.get(collection, [])

        if not isinstance(items, list):
            return set()

        result: set[str] = set()

        for item in items:
            if not isinstance(item, dict):
                continue

            if not BrokerReconciler._is_active(item):
                continue

            broker_id = item.get(id_key)

            if broker_id is None:
                continue

            normalized = str(broker_id).strip()

            if normalized:
                result.add(normalized)

        return result

    @staticmethod
    def _execution_ids_from_snapshot_dict(
        snapshot: dict[str, Any] | None,
    ) -> set[str]:
        if not isinstance(snapshot, dict):
            return set()

        result: set[str] = set()

        for collection in ("orders", "positions"):
            items = snapshot.get(collection, [])

            if not isinstance(items, list):
                continue

            for item in items:
                if not isinstance(item, dict):
                    continue

                if not BrokerReconciler._is_active(item):
                    continue

                execution_id = (
                    BrokerReconciler
                    ._execution_id_from_item(item)
                )

                if execution_id:
                    result.add(execution_id)

        return result

    @staticmethod
    def _execution_id_from_item(
        item: dict[str, Any],
    ) -> str | None:
        direct = BrokerReconciler._normalize(
            item.get("execution_id")
        )

        if direct:
            return direct

        metadata = item.get("metadata")

        if isinstance(metadata, dict):
            return (
                BrokerReconciler
                ._execution_id_from_metadata(metadata)
            )

        return None

    @staticmethod
    def _execution_id_from_metadata(
        metadata: dict[str, Any] | None,
    ) -> str | None:
        if not isinstance(metadata, dict):
            return None

        for key in (
            "execution_id",
            "source_execution_id",
            "client_execution_id",
        ):
            value = BrokerReconciler._normalize(
                metadata.get(key)
            )

            if value:
                return value

        comment = BrokerReconciler._normalize(
            metadata.get("comment")
        )

        if comment:
            marker = "execution_id="

            if marker in comment:
                value = comment.split(
                    marker,
                    1,
                )[1].strip()

                if value:
                    return value

        return None

    @staticmethod
    def _is_active(
        item: dict[str, Any],
    ) -> bool:
        active = item.get("active")

        if active is not None:
            return bool(active)

        status = str(
            item.get("status", "")
        ).upper()

        terminal = {
            "FILLED",
            "CANCELLED",
            "REJECTED",
            "EXPIRED",
            "CLOSED",
        }

        return status not in terminal

    @staticmethod
    def _normalize(
        value: Any,
    ) -> str | None:
        if value is None:
            return None

        normalized = str(value).strip()

        return normalized if normalized else None