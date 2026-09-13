from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.execution_adapter import (
    AdapterExecutionResult,
)
from core.execution_order import (
    ExecutionOrder,
)
from infrastructure.execution_journal import (
    ExecutionJournal,
)


@dataclass(slots=True)
class JournaledSubmissionResult:
    execution_id: str
    attempted: bool
    blocked_by_journal: bool
    journal_status: str | None
    broker_result: AdapterExecutionResult | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "attempted": self.attempted,
            "blocked_by_journal": (
                self.blocked_by_journal
            ),
            "journal_status": (
                self.journal_status
            ),
            "broker_result": (
                self.broker_result.to_dict()
                if (
                    self.broker_result
                    is not None
                    and hasattr(
                        self.broker_result,
                        "to_dict",
                    )
                )
                else None
            ),
        }


class JournaledExecutionSubmitter:
    """
    Crash-safe wrapper around ExecutionAdapter.submit().

    Order of operations:
        1. refuse already-blocked execution_id
        2. persist SUBMISSION_INTENT
        3. call adapter.submit()
        4. persist SUBMITTED or REJECTED

    Important:
    - SUBMISSION_INTENT is always written before submit();
    - if process crashes after intent but before result persistence,
      blocks_submission() prevents blind repeat submission.
    """

    def __init__(
        self,
        *,
        adapter: Any,
        journal: ExecutionJournal,
    ) -> None:
        self.adapter = adapter
        self.journal = journal

    def submit(
        self,
        order: ExecutionOrder,
    ) -> JournaledSubmissionResult:
        execution_id = str(
            order.execution_id
        )

        if self.journal.blocks_submission(
            execution_id
        ):
            existing = self.journal.get(
                execution_id
            )

            return JournaledSubmissionResult(
                execution_id=execution_id,
                attempted=False,
                blocked_by_journal=True,
                journal_status=(
                    existing.status.value
                    if existing is not None
                    else None
                ),
                broker_result=None,
            )

        self.journal.record_intent(
            execution_id=execution_id,
            symbol=order.symbol,
            metadata={
                "provider": order.provider,
                "created_time": (
                    int(order.created_time)
                ),
                "order_type": (
                    order.order_type.value
                ),
                "direction": (
                    order.direction.value
                ),
                "volume": float(
                    order.volume
                ),
                "entry_price": float(
                    order.entry_price
                ),
                "stop_loss": float(
                    order.stop_loss
                ),
                "take_profit": float(
                    order.take_profit
                ),
            },
        )

        try:
            broker_result = (
                self.adapter.submit(
                    order
                )
            )
        except Exception as exc:
            self.journal.mark_rejected(
                execution_id=execution_id,
                error=(
                    f"adapter_submit_exception:"
                    f"{exc.__class__.__name__}:"
                    f"{exc}"
                ),
            )

            raise

        if broker_result.success:
            self.journal.mark_submitted(
                execution_id=execution_id,
                broker_order_id=(
                    broker_result
                    .broker_order_id
                ),
                broker_deal_id=(
                    getattr(
                        broker_result,
                        "broker_deal_id",
                        None,
                    )
                ),
                metadata={
                    "adapter": (
                        broker_result.adapter
                    ),
                    "status": (
                        broker_result
                        .status.value
                    ),
                    "error_code": (
                        broker_result
                        .error_code
                    ),
                },
            )

            status = "SUBMITTED"

        else:
            self.journal.mark_rejected(
                execution_id=execution_id,
                error=(
                    broker_result.message
                    or "broker_rejected"
                ),
                metadata={
                    "adapter": (
                        broker_result.adapter
                    ),
                    "status": (
                        broker_result
                        .status.value
                    ),
                    "error_code": (
                        broker_result
                        .error_code
                    ),
                },
            )

            status = "REJECTED"

        return JournaledSubmissionResult(
            execution_id=execution_id,
            attempted=True,
            blocked_by_journal=False,
            journal_status=status,
            broker_result=broker_result,
        )