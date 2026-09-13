from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from execution_state.execution_state_reconciler import (
    ReconciliationIssue,
    ReconciliationIssueType,
    ReconciliationResult,
)


class RecoveryActionType(str, Enum):
    NO_ACTION = "NO_ACTION"
    PAUSE_NEW_ENTRIES = "PAUSE_NEW_ENTRIES"
    DROP_LOCAL_ORDER = "DROP_LOCAL_ORDER"
    DROP_LOCAL_POSITION = "DROP_LOCAL_POSITION"
    ADOPT_BROKER_ORDER = "ADOPT_BROKER_ORDER"
    ADOPT_BROKER_POSITION = "ADOPT_BROKER_POSITION"
    REQUIRE_MANUAL_REVIEW = "REQUIRE_MANUAL_REVIEW"


@dataclass(slots=True)
class RecoveryAction:
    action_type: RecoveryActionType
    broker_id: str | None = None
    reason: str = ""
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_type": (
                self.action_type.value
            ),
            "broker_id": self.broker_id,
            "reason": self.reason,
            "metadata": dict(
                self.metadata
            ),
        }


@dataclass(slots=True)
class RecoveryPlan:
    safe_to_continue: bool
    pause_new_entries: bool
    actions: list[RecoveryAction] = field(
        default_factory=list
    )

    @property
    def requires_manual_review(
        self,
    ) -> bool:
        return any(
            action.action_type
            == RecoveryActionType.REQUIRE_MANUAL_REVIEW
            for action in self.actions
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "safe_to_continue": (
                self.safe_to_continue
            ),
            "pause_new_entries": (
                self.pause_new_entries
            ),
            "requires_manual_review": (
                self.requires_manual_review
            ),
            "actions": [
                action.to_dict()
                for action in self.actions
            ],
        }


class RecoveryPolicy:
    """
    Conservative recovery policy for live trading.

    Default philosophy:
    - unknown broker positions are dangerous;
    - duplicate broker IDs are dangerous;
    - missing local references should be cleaned;
    - any dangerous mismatch pauses new entries.
    """

    def build_plan(
        self,
        reconciliation: ReconciliationResult,
    ) -> RecoveryPlan:
        if reconciliation.clean:
            return RecoveryPlan(
                safe_to_continue=True,
                pause_new_entries=False,
                actions=[
                    RecoveryAction(
                        action_type=(
                            RecoveryActionType.NO_ACTION
                        ),
                        reason=(
                            "broker_and_bot_state_are_synchronized"
                        ),
                    )
                ],
            )

        actions: list[
            RecoveryAction
        ] = []

        pause_new_entries = False
        safe_to_continue = True

        for issue in reconciliation.issues:
            mapped = self._map_issue(
                issue
            )

            actions.extend(
                mapped
            )

            if any(
                action.action_type
                in {
                    RecoveryActionType.PAUSE_NEW_ENTRIES,
                    RecoveryActionType.REQUIRE_MANUAL_REVIEW,
                }
                for action in mapped
            ):
                pause_new_entries = True

            if any(
                action.action_type
                == RecoveryActionType.REQUIRE_MANUAL_REVIEW
                for action in mapped
            ):
                safe_to_continue = False

        return RecoveryPlan(
            safe_to_continue=(
                safe_to_continue
            ),
            pause_new_entries=(
                pause_new_entries
            ),
            actions=actions,
        )

    def _map_issue(
        self,
        issue: ReconciliationIssue,
    ) -> list[RecoveryAction]:
        issue_type = issue.issue_type
        broker_id = issue.broker_id

        if (
            issue_type
            == ReconciliationIssueType.ORDER_MISSING
        ):
            return [
                RecoveryAction(
                    action_type=(
                        RecoveryActionType
                        .DROP_LOCAL_ORDER
                    ),
                    broker_id=broker_id,
                    reason=(
                        "known_order_missing_from_broker"
                    ),
                ),
            ]

        if (
            issue_type
            == ReconciliationIssueType.POSITION_MISSING
        ):
            return [
                RecoveryAction(
                    action_type=(
                        RecoveryActionType
                        .DROP_LOCAL_POSITION
                    ),
                    broker_id=broker_id,
                    reason=(
                        "known_position_missing_from_broker"
                    ),
                ),
            ]

        if (
            issue_type
            == ReconciliationIssueType.UNKNOWN_ORDER
        ):
            return [
                RecoveryAction(
                    action_type=(
                        RecoveryActionType
                        .PAUSE_NEW_ENTRIES
                    ),
                    broker_id=broker_id,
                    reason=(
                        "unknown_broker_order_detected"
                    ),
                ),
                RecoveryAction(
                    action_type=(
                        RecoveryActionType
                        .ADOPT_BROKER_ORDER
                    ),
                    broker_id=broker_id,
                    reason=(
                        "adopt_unknown_order_into_local_state"
                    ),
                ),
            ]

        if (
            issue_type
            == ReconciliationIssueType.UNKNOWN_POSITION
        ):
            return [
                RecoveryAction(
                    action_type=(
                        RecoveryActionType
                        .PAUSE_NEW_ENTRIES
                    ),
                    broker_id=broker_id,
                    reason=(
                        "unknown_broker_position_detected"
                    ),
                ),
                RecoveryAction(
                    action_type=(
                        RecoveryActionType
                        .REQUIRE_MANUAL_REVIEW
                    ),
                    broker_id=broker_id,
                    reason=(
                        "unknown_live_position_requires_review"
                    ),
                ),
            ]

        if issue_type in {
            ReconciliationIssueType.DUPLICATE_ORDER,
            ReconciliationIssueType.DUPLICATE_POSITION,
        }:
            return [
                RecoveryAction(
                    action_type=(
                        RecoveryActionType
                        .PAUSE_NEW_ENTRIES
                    ),
                    broker_id=broker_id,
                    reason=(
                        "duplicate_broker_identity_detected"
                    ),
                ),
                RecoveryAction(
                    action_type=(
                        RecoveryActionType
                        .REQUIRE_MANUAL_REVIEW
                    ),
                    broker_id=broker_id,
                    reason=(
                        "duplicate_broker_identity_requires_review"
                    ),
                ),
            ]

        return [
            RecoveryAction(
                action_type=(
                    RecoveryActionType
                    .REQUIRE_MANUAL_REVIEW
                ),
                broker_id=broker_id,
                reason=(
                    "unhandled_reconciliation_issue"
                ),
            ),
        ]