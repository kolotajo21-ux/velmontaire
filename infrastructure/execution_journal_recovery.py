from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.execution_state import ExecutionSnapshot
from infrastructure.execution_journal import (
    ExecutionJournal,
    ExecutionJournalEntry,
    ExecutionJournalStatus,
)


@dataclass(slots=True)
class JournalRecoveryItem:
    execution_id: str
    previous_status: str

    found_order_ids: list[str] = field(
        default_factory=list
    )
    found_position_ids: list[str] = field(
        default_factory=list
    )

    confirmed: bool = False
    retry_allowed: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "previous_status": self.previous_status,
            "found_order_ids": list(
                self.found_order_ids
            ),
            "found_position_ids": list(
                self.found_position_ids
            ),
            "confirmed": self.confirmed,
            "retry_allowed": self.retry_allowed,
            "error": self.error,
        }


@dataclass(slots=True)
class JournalRecoveryReport:
    items: list[JournalRecoveryItem] = field(
        default_factory=list
    )

    @property
    def unresolved_count(self) -> int:
        return len(self.items)

    @property
    def confirmed_count(self) -> int:
        return sum(
            1
            for item in self.items
            if item.confirmed
        )

    @property
    def retry_allowed_count(self) -> int:
        return sum(
            1
            for item in self.items
            if item.retry_allowed
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "unresolved_count": (
                self.unresolved_count
            ),
            "confirmed_count": (
                self.confirmed_count
            ),
            "retry_allowed_count": (
                self.retry_allowed_count
            ),
            "items": [
                item.to_dict()
                for item in self.items
            ],
        }


class ExecutionJournalRecovery:
    """
    Resolves unresolved write-ahead journal entries
    against an authoritative fresh broker snapshot.

    Rules:
    - matching broker order -> CONFIRMED;
    - matching broker position -> CONFIRMED;
    - no match after fresh synchronization -> REJECTED,
      which makes that execution_id retryable.

    This class never calls order_send().
    """

    def __init__(
        self,
        *,
        journal: ExecutionJournal,
    ) -> None:
        self.journal = journal

    def recover(
        self,
        *,
        snapshot: ExecutionSnapshot,
    ) -> JournalRecoveryReport:
        items: list[
            JournalRecoveryItem
        ] = []

        for entry in self.journal.unresolved():
            item = self._recover_entry(
                entry=entry,
                snapshot=snapshot,
            )

            items.append(
                item
            )

        return JournalRecoveryReport(
            items=items
        )

    def _recover_entry(
        self,
        *,
        entry: ExecutionJournalEntry,
        snapshot: ExecutionSnapshot,
    ) -> JournalRecoveryItem:
        execution_id = (
            entry.execution_id
        )

        order_ids = self._matching_order_ids(
            execution_id=execution_id,
            snapshot=snapshot,
        )

        position_ids = (
            self._matching_position_ids(
                execution_id=execution_id,
                snapshot=snapshot,
            )
        )

        if order_ids or position_ids:
            broker_order_id = (
                order_ids[0]
                if order_ids
                else entry.broker_order_id
            )

            broker_position_id = (
                position_ids[0]
                if position_ids
                else None
            )

            self.journal.mark_confirmed(
                execution_id=execution_id,
                broker_order_id=(
                    broker_order_id
                ),
                metadata={
                    "recovered_after_restart": True,
                    "broker_position_id": (
                        broker_position_id
                    ),
                    "recovery_source": (
                        "fresh_execution_snapshot"
                    ),
                },
            )

            return JournalRecoveryItem(
                execution_id=execution_id,
                previous_status=(
                    entry.status.value
                ),
                found_order_ids=order_ids,
                found_position_ids=(
                    position_ids
                ),
                confirmed=True,
                retry_allowed=False,
            )

        self.journal.mark_rejected(
            execution_id=execution_id,
            error=(
                "execution_not_found_after_"
                "fresh_broker_sync"
            ),
            metadata={
                "recovered_after_restart": True,
                "recovery_source": (
                    "fresh_execution_snapshot"
                ),
            },
        )

        return JournalRecoveryItem(
            execution_id=execution_id,
            previous_status=(
                entry.status.value
            ),
            found_order_ids=[],
            found_position_ids=[],
            confirmed=False,
            retry_allowed=True,
            error=(
                "execution_not_found_after_"
                "fresh_broker_sync"
            ),
        )

    @staticmethod
    def _matching_order_ids(
        *,
        execution_id: str,
        snapshot: ExecutionSnapshot,
    ) -> list[str]:
        matches: list[str] = []

        for order in snapshot.orders:
            candidate = str(
                order.execution_id
            ).strip()

            if candidate == execution_id:
                matches.append(
                    str(
                        order.broker_order_id
                    )
                )

        return matches

    @staticmethod
    def _matching_position_ids(
        *,
        execution_id: str,
        snapshot: ExecutionSnapshot,
    ) -> list[str]:
        matches: list[str] = []

        for position in snapshot.positions:
            candidate = (
                ExecutionJournalRecovery
                ._execution_id_from_metadata(
                    position.metadata
                )
            )

            if candidate == execution_id:
                matches.append(
                    str(
                        position.broker_position_id
                    )
                )

        return matches

    @staticmethod
    def _execution_id_from_metadata(
        metadata: dict[str, Any] | None,
    ) -> str | None:
        if not isinstance(
            metadata,
            dict,
        ):
            return None

        for key in (
            "execution_id",
            "source_execution_id",
            "client_execution_id",
        ):
            value = metadata.get(
                key
            )

            if value is not None:
                normalized = str(
                    value
                ).strip()

                if normalized:
                    return normalized

        comment = metadata.get(
            "comment"
        )

        if comment is None:
            return None

        comment = str(
            comment
        )

        marker = "execution_id="

        if marker not in comment:
            return None

        value = comment.split(
            marker,
            1,
        )[1].strip()

        return (
            value
            if value
            else None
        )