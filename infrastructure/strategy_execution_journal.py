from __future__ import annotations

from infrastructure.execution_journal import (
    ExecutionJournal,
    ExecutionJournalEntry,
    ExecutionJournalStatus,
)


class StrategyExecutionJournal(ExecutionJournal):
    """
    Strategy-scoped view over ExecutionJournal.

    The underlying journal format remains unchanged.
    Local execution_id values are namespaced as:

        <strategy_id>::<execution_id>

    This allows different strategies to use the same local execution_id
    without journal collisions.
    """

    def __init__(
        self,
        path,
        *,
        strategy_id: str,
    ) -> None:
        super().__init__(path)

        self.strategy_id = (
            self._normalize_strategy_id(
                strategy_id
            )
        )

    def _key(
        self,
        execution_id: str,
    ) -> str:
        value = str(
            execution_id
        ).strip()

        if not value:
            raise ValueError(
                "execution_id is required"
            )

        return (
            f"{self.strategy_id}::{value}"
        )

    def record_intent(
        self,
        *,
        execution_id,
        symbol=None,
        metadata=None,
    ):
        metadata = dict(
            metadata or {}
        )

        metadata.setdefault(
            "strategy_id",
            self.strategy_id,
        )
        metadata.setdefault(
            "local_execution_id",
            str(execution_id),
        )

        return super().record_intent(
            execution_id=self._key(
                execution_id
            ),
            symbol=symbol,
            metadata=metadata,
        )

    def mark_submitted(
        self,
        *,
        execution_id,
        broker_order_id=None,
        broker_deal_id=None,
        metadata=None,
    ):
        return super().mark_submitted(
            execution_id=self._key(
                execution_id
            ),
            broker_order_id=(
                broker_order_id
            ),
            broker_deal_id=(
                broker_deal_id
            ),
            metadata=metadata,
        )

    def mark_rejected(
        self,
        *,
        execution_id,
        error,
        metadata=None,
    ):
        return super().mark_rejected(
            execution_id=self._key(
                execution_id
            ),
            error=error,
            metadata=metadata,
        )

    def mark_confirmed(
        self,
        *,
        execution_id,
        broker_order_id=None,
        broker_deal_id=None,
        metadata=None,
    ):
        return super().mark_confirmed(
            execution_id=self._key(
                execution_id
            ),
            broker_order_id=(
                broker_order_id
            ),
            broker_deal_id=(
                broker_deal_id
            ),
            metadata=metadata,
        )

    def get(
        self,
        execution_id,
    ) -> ExecutionJournalEntry | None:
        # IMPORTANT:
        # Call the base get() directly with exactly one namespace.
        # Do not route through another overridden method.
        return ExecutionJournal.get(
            self,
            self._key(
                execution_id
            ),
        )

    def blocks_submission(
        self,
        execution_id,
    ) -> bool:
        # Do NOT call super().blocks_submission().
        # Base blocks_submission() internally calls self.get(),
        # which would namespace the already-namespaced ID again.
        entry = self.get(
            execution_id
        )

        if entry is None:
            return False

        return entry.status in {
            ExecutionJournalStatus
            .SUBMISSION_INTENT,
            ExecutionJournalStatus
            .SUBMITTED,
            ExecutionJournalStatus
            .CONFIRMED,
        }

    def all(
        self,
    ) -> list[ExecutionJournalEntry]:
        prefix = (
            f"{self.strategy_id}::"
        )

        # Base all() reads raw entries directly, so no double namespace.
        return [
            entry
            for entry in ExecutionJournal.all(
                self
            )
            if entry.execution_id.startswith(
                prefix
            )
        ]

    def unresolved(
        self,
    ) -> list[ExecutionJournalEntry]:
        statuses = {
            ExecutionJournalStatus
            .SUBMISSION_INTENT,
            ExecutionJournalStatus
            .SUBMITTED,
        }

        return [
            entry
            for entry in self.all()
            if entry.status in statuses
        ]

    @staticmethod
    def _normalize_strategy_id(
        strategy_id: str,
    ) -> str:
        value = str(
            strategy_id
        ).strip()

        if not value:
            raise ValueError(
                "strategy_id is required"
            )

        return value