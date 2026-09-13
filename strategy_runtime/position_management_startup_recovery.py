from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from core.context import StrategyContext
from .position_management import (
    PositionManagementAction,
    PositionManagementRequest,
)
from .position_management_intent_recovery import (
    ManagementRecoveryResult,
    ManagementRecoveryState,
    PositionManagementIntentRecovery,
)
from .position_management_journal import (
    PositionManagementJournal,
    PositionManagementJournalEntry,
    PositionManagementJournalStatus,
)


@dataclass(slots=True)
class StartupRecoveryItem:
    request_key: str
    execution_id: str
    recovered: bool
    blocked: bool
    retry_allowed: bool
    reason: str
    recovery_state: str | None = None


@dataclass(slots=True)
class StartupRecoveryReport:
    scanned: int = 0
    unresolved_intents: int = 0
    completed: int = 0
    retryable: int = 0
    blocked: int = 0
    results: list[StartupRecoveryItem] = field(
        default_factory=list
    )

    @property
    def success(self) -> bool:
        return self.blocked == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "scanned": self.scanned,
            "unresolved_intents": self.unresolved_intents,
            "completed": self.completed,
            "retryable": self.retryable,
            "blocked": self.blocked,
            "results": [
                item.__dict__.copy()
                for item in self.results
            ],
        }


class PositionManagementStartupRecovery:
    """
    Day 75 automatic startup recovery.

    Startup sequence:
      1. scan management journal
      2. reconstruct unresolved INTENT requests
      3. run Day 74 read-only reconciliation
      4. never execute the original management action

    context_factory:
        (execution_id: str, symbol: str) -> StrategyContext
    """

    def __init__(
        self,
        *,
        journal: PositionManagementJournal,
        recovery: PositionManagementIntentRecovery,
        context_factory: Callable[
            [str, str],
            StrategyContext,
        ],
    ) -> None:
        self.journal = journal
        self.recovery = recovery
        self.context_factory = context_factory

    def run(self) -> StartupRecoveryReport:
        report = StartupRecoveryReport()

        entries = self._entries()

        for entry in entries:
            report.scanned += 1

            if entry.status != PositionManagementJournalStatus.INTENT:
                continue

            report.unresolved_intents += 1

            request = self._request_from_entry(
                entry
            )

            if request is None:
                report.blocked += 1
                report.results.append(
                    StartupRecoveryItem(
                        request_key=entry.request_key,
                        execution_id=entry.execution_id,
                        recovered=False,
                        blocked=True,
                        retry_allowed=False,
                        reason="startup_recovery_request_reconstruction_failed",
                    )
                )
                continue

            try:
                context = self.context_factory(
                    entry.execution_id,
                    request.symbol,
                )
            except Exception as exc:
                report.blocked += 1
                report.results.append(
                    StartupRecoveryItem(
                        request_key=entry.request_key,
                        execution_id=entry.execution_id,
                        recovered=False,
                        blocked=True,
                        retry_allowed=False,
                        reason=(
                            "startup_recovery_context_creation_failed:"
                            f"{type(exc).__name__}:{exc}"
                        ),
                    )
                )
                continue

            result = self.recovery.recover(
                request,
                context,
            )

            self._apply_result(
                report,
                entry,
                result,
            )

        return report

    def _entries(
        self,
    ) -> list[PositionManagementJournalEntry]:
        data = self.journal._load()

        return [
            PositionManagementJournalEntry.from_dict(
                raw
            )
            for raw in data.values()
        ]

    @staticmethod
    def _request_from_entry(
        entry: PositionManagementJournalEntry,
    ) -> PositionManagementRequest | None:
        metadata = dict(
            entry.metadata or {}
        )

        symbol = str(
            metadata.get(
                "symbol",
                "",
            )
        ).strip()

        broker_position_id = metadata.get(
            "broker_position_id"
        )

        if (
            not symbol
            or broker_position_id in (
                None,
                "",
            )
        ):
            return None

        try:
            action = PositionManagementAction(
                entry.action
            )
        except ValueError:
            return None

        return PositionManagementRequest(
            execution_id=entry.execution_id,
            action=action,
            symbol=symbol,
            broker_position_id=str(
                broker_position_id
            ),
            stop_loss=metadata.get(
                "stop_loss"
            ),
            take_profit=metadata.get(
                "take_profit"
            ),
            reason=metadata.get(
                "reason"
            ),
            metadata=dict(
                metadata.get(
                    "request_metadata"
                )
                or {}
            ),
        )

    @staticmethod
    def _apply_result(
        report: StartupRecoveryReport,
        entry: PositionManagementJournalEntry,
        result: ManagementRecoveryResult,
    ) -> None:
        if result.state in {
            ManagementRecoveryState.RECONCILED_COMPLETED,
            ManagementRecoveryState.ALREADY_COMPLETED,
        }:
            report.completed += 1
            recovered = True
            blocked = False

        elif result.state in {
            ManagementRecoveryState.RECONCILED_RETRYABLE,
            ManagementRecoveryState.RETRYABLE_FAILED,
        }:
            report.retryable += 1
            recovered = True
            blocked = False

        else:
            report.blocked += 1
            recovered = False
            blocked = True

        report.results.append(
            StartupRecoveryItem(
                request_key=entry.request_key,
                execution_id=entry.execution_id,
                recovered=recovered,
                blocked=blocked,
                retry_allowed=result.retry_allowed,
                reason=result.reason,
                recovery_state=result.state.value,
            )
        )