from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.execution_state import (
    ExecutionSnapshot,
)


class ReconciliationIssueType(str, Enum):
    ORDER_MISSING = "ORDER_MISSING"
    POSITION_MISSING = "POSITION_MISSING"
    UNKNOWN_ORDER = "UNKNOWN_ORDER"
    UNKNOWN_POSITION = "UNKNOWN_POSITION"
    DUPLICATE_ORDER = "DUPLICATE_ORDER"
    DUPLICATE_POSITION = "DUPLICATE_POSITION"


@dataclass(slots=True)
class ReconciliationIssue:
    issue_type: ReconciliationIssueType
    broker_id: str
    message: str
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "issue_type": self.issue_type.value,
            "broker_id": self.broker_id,
            "message": self.message,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class ReconciliationResult:
    synchronized: bool
    issues: list[ReconciliationIssue] = field(
        default_factory=list
    )
    known_order_ids: set[str] = field(
        default_factory=set
    )
    known_position_ids: set[str] = field(
        default_factory=set
    )
    broker_order_ids: set[str] = field(
        default_factory=set
    )
    broker_position_ids: set[str] = field(
        default_factory=set
    )

    @property
    def clean(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict[str, Any]:
        return {
            "synchronized": self.synchronized,
            "clean": self.clean,
            "issues": [
                issue.to_dict()
                for issue in self.issues
            ],
            "known_order_ids": sorted(
                self.known_order_ids
            ),
            "known_position_ids": sorted(
                self.known_position_ids
            ),
            "broker_order_ids": sorted(
                self.broker_order_ids
            ),
            "broker_position_ids": sorted(
                self.broker_position_ids
            ),
        }


class ExecutionStateReconciler:
    """
    Compares bot-known broker IDs with a fresh broker snapshot.

    It does not send/modify/cancel any broker orders.
    """

    def reconcile(
        self,
        *,
        snapshot: ExecutionSnapshot,
        known_order_ids: set[str] | None = None,
        known_position_ids: set[str] | None = None,
    ) -> ReconciliationResult:
        expected_orders = {
            str(value)
            for value in (
                known_order_ids or set()
            )
        }
        expected_positions = {
            str(value)
            for value in (
                known_position_ids or set()
            )
        }

        broker_orders = [
            str(order.broker_order_id)
            for order in snapshot.orders
        ]
        broker_positions = [
            str(position.broker_position_id)
            for position in snapshot.positions
        ]

        broker_order_ids = set(
            broker_orders
        )
        broker_position_ids = set(
            broker_positions
        )

        issues: list[
            ReconciliationIssue
        ] = []

        self._find_duplicates(
            values=broker_orders,
            issue_type=(
                ReconciliationIssueType
                .DUPLICATE_ORDER
            ),
            label="order",
            issues=issues,
        )

        self._find_duplicates(
            values=broker_positions,
            issue_type=(
                ReconciliationIssueType
                .DUPLICATE_POSITION
            ),
            label="position",
            issues=issues,
        )

        for broker_id in sorted(
            expected_orders
            - broker_order_ids
        ):
            issues.append(
                ReconciliationIssue(
                    issue_type=(
                        ReconciliationIssueType
                        .ORDER_MISSING
                    ),
                    broker_id=broker_id,
                    message=(
                        "Known order is missing "
                        "from broker snapshot."
                    ),
                )
            )

        for broker_id in sorted(
            expected_positions
            - broker_position_ids
        ):
            issues.append(
                ReconciliationIssue(
                    issue_type=(
                        ReconciliationIssueType
                        .POSITION_MISSING
                    ),
                    broker_id=broker_id,
                    message=(
                        "Known position is missing "
                        "from broker snapshot."
                    ),
                )
            )

        for broker_id in sorted(
            broker_order_ids
            - expected_orders
        ):
            issues.append(
                ReconciliationIssue(
                    issue_type=(
                        ReconciliationIssueType
                        .UNKNOWN_ORDER
                    ),
                    broker_id=broker_id,
                    message=(
                        "Broker order is unknown "
                        "to bot state."
                    ),
                )
            )

        for broker_id in sorted(
            broker_position_ids
            - expected_positions
        ):
            issues.append(
                ReconciliationIssue(
                    issue_type=(
                        ReconciliationIssueType
                        .UNKNOWN_POSITION
                    ),
                    broker_id=broker_id,
                    message=(
                        "Broker position is unknown "
                        "to bot state."
                    ),
                )
            )

        return ReconciliationResult(
            synchronized=not issues,
            issues=issues,
            known_order_ids=expected_orders,
            known_position_ids=(
                expected_positions
            ),
            broker_order_ids=(
                broker_order_ids
            ),
            broker_position_ids=(
                broker_position_ids
            ),
        )

    @staticmethod
    def _find_duplicates(
        *,
        values: list[str],
        issue_type: ReconciliationIssueType,
        label: str,
        issues: list[ReconciliationIssue],
    ) -> None:
        seen: set[str] = set()
        duplicates: set[str] = set()

        for value in values:
            if value in seen:
                duplicates.add(value)
            seen.add(value)

        for broker_id in sorted(
            duplicates
        ):
            issues.append(
                ReconciliationIssue(
                    issue_type=issue_type,
                    broker_id=broker_id,
                    message=(
                        f"Duplicate broker {label} "
                        "ID detected in snapshot."
                    ),
                )
            )