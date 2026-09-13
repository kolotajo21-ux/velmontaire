from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.context import StrategyContext
from core.execution_state import ExecutionSnapshot
from execution_state.mt5_state_synchronizer import (
    MT5StateSynchronizer,
)
from infrastructure.execution_journal_recovery import (
    ExecutionJournalRecovery,
)
from infrastructure.runtime_state_context import (
    RuntimeStateCoordinator,
)
from infrastructure.multi_symbol_runtime_state_context import (
    MultiSymbolRuntimeStateCoordinator,
)
from modules.execution.broker_reconciler import (
    BrokerReconciler,
)
from modules.execution.broker_recovery_coordinator import (
    BrokerRecoveryCoordinator,
)


@dataclass(slots=True)
class RuntimeCycleResult:
    restored: bool
    synchronized: bool
    journal_recovered: bool
    reconciled: bool
    recovered: bool
    persisted: bool

    submission_allowed: bool = True
    new_entries_allowed: bool = True

    recovered_from_backup: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "restored": self.restored,
            "synchronized": self.synchronized,
            "journal_recovered": self.journal_recovered,
            "reconciled": self.reconciled,
            "recovered": self.recovered,
            "persisted": self.persisted,
            "submission_allowed": self.submission_allowed,
            "new_entries_allowed": self.new_entries_allowed,
            "recovered_from_backup": (
                self.recovered_from_backup
            ),
            "error": self.error,
        }


class RuntimeExecutionLifecycle:
    """
    Full crash-safe runtime lifecycle.

    Startup flow:
        restore runtime state
            ->
        preserve persisted execution snapshot
            ->
        fresh MT5 synchronization
            ->
        recover unresolved execution journal entries
            ->
        broker reconciliation
            ->
        recovery policy
            ->
        persist refreshed runtime state

    This class never calls order_send().
    """

    def __init__(
        self,
        *,
        coordinator: RuntimeStateCoordinator | MultiSymbolRuntimeStateCoordinator,
        synchronizer: MT5StateSynchronizer,
        broker_reconciler: BrokerReconciler | None = None,
        recovery_coordinator: (
            BrokerRecoveryCoordinator | None
        ) = None,
        journal_recovery: (
            ExecutionJournalRecovery | None
        ) = None,
    ) -> None:
        self.coordinator = coordinator
        self.synchronizer = synchronizer

        self.broker_reconciler = (
            broker_reconciler
            if broker_reconciler is not None
            else BrokerReconciler()
        )

        self.recovery_coordinator = (
            recovery_coordinator
            if recovery_coordinator is not None
            else BrokerRecoveryCoordinator()
        )

        self.journal_recovery = (
            journal_recovery
        )

        self._last_snapshots: dict[str, ExecutionSnapshot] = {}

    def restore(
        self,
        context: StrategyContext,
        *,
        strict_symbol: bool = True,
    ) -> RuntimeCycleResult:
        result = self.coordinator.restore_context(
            context,
            strict_symbol=strict_symbol,
        )

        if not result.success:
            return RuntimeCycleResult(
                restored=False,
                synchronized=False,
                journal_recovered=False,
                reconciled=False,
                recovered=False,
                persisted=False,
                submission_allowed=False,
                new_entries_allowed=False,
                recovered_from_backup=(
                    result.recovered_from_backup
                ),
                error=result.error,
            )

        return RuntimeCycleResult(
            restored=(
                result.state is not None
            ),
            synchronized=False,
            journal_recovered=False,
            reconciled=False,
            recovered=False,
            persisted=False,
            submission_allowed=True,
            new_entries_allowed=bool(
                context.get(
                    "new_entries_allowed",
                    True,
                )
            ),
            recovered_from_backup=(
                result.recovered_from_backup
            ),
        )

    def synchronize(
        self,
        context: StrategyContext,
    ) -> RuntimeCycleResult:
        try:
            snapshot = self.synchronizer.synchronize(
                symbol=context.symbol,
                synchronized_time=int(
                    context.current_time
                ),
            )
        except Exception as exc:
            return RuntimeCycleResult(
                restored=bool(
                    context.get(
                        "runtime_state_restored"
                    )
                ),
                synchronized=False,
                journal_recovered=False,
                reconciled=False,
                recovered=False,
                persisted=False,
                submission_allowed=False,
                new_entries_allowed=False,
                recovered_from_backup=bool(
                    context.get(
                        "runtime_state_recovered_from_backup"
                    )
                ),
                error=(
                    "broker_state_sync_failed:"
                    f"{exc.__class__.__name__}:"
                    f"{exc}"
                ),
            )

        self._last_snapshots[str(context.symbol)] = snapshot

        snapshot_data = snapshot.to_dict()

        context.put(
            "execution_snapshot",
            snapshot_data,
        )

        context.trade[
            "execution_snapshot"
        ] = snapshot_data

        context.put(
            "execution_state_synchronized",
            True,
        )

        context.trade[
            "execution_state_synchronized"
        ] = True

        return RuntimeCycleResult(
            restored=bool(
                context.get(
                    "runtime_state_restored"
                )
            ),
            synchronized=True,
            journal_recovered=False,
            reconciled=False,
            recovered=False,
            persisted=False,
            submission_allowed=True,
            new_entries_allowed=bool(
                context.get(
                    "new_entries_allowed",
                    True,
                )
            ),
            recovered_from_backup=bool(
                context.get(
                    "runtime_state_recovered_from_backup"
                )
            ),
        )

    def recover_journal(
        self,
        context: StrategyContext,
    ) -> RuntimeCycleResult:
        if self.journal_recovery is None:
            context.put(
                "execution_journal_recovery_skipped",
                True,
            )

            return RuntimeCycleResult(
                restored=bool(
                    context.get(
                        "runtime_state_restored"
                    )
                ),
                synchronized=bool(
                    context.get(
                        "execution_state_synchronized"
                    )
                ),
                journal_recovered=False,
                reconciled=False,
                recovered=False,
                persisted=False,
                submission_allowed=True,
                new_entries_allowed=bool(
                    context.get(
                        "new_entries_allowed",
                        True,
                    )
                ),
                recovered_from_backup=bool(
                    context.get(
                        "runtime_state_recovered_from_backup"
                    )
                ),
            )

        snapshot = self._last_snapshots.get(str(context.symbol))

        if snapshot is None:
            return RuntimeCycleResult(
                restored=bool(
                    context.get(
                        "runtime_state_restored"
                    )
                ),
                synchronized=False,
                journal_recovered=False,
                reconciled=False,
                recovered=False,
                persisted=False,
                submission_allowed=False,
                new_entries_allowed=False,
                recovered_from_backup=bool(
                    context.get(
                        "runtime_state_recovered_from_backup"
                    )
                ),
                error="fresh_execution_snapshot_missing",
            )

        try:
            report = self.journal_recovery.recover(
                snapshot=snapshot
            )
        except Exception as exc:
            return RuntimeCycleResult(
                restored=bool(
                    context.get(
                        "runtime_state_restored"
                    )
                ),
                synchronized=True,
                journal_recovered=False,
                reconciled=False,
                recovered=False,
                persisted=False,
                submission_allowed=False,
                new_entries_allowed=False,
                recovered_from_backup=bool(
                    context.get(
                        "runtime_state_recovered_from_backup"
                    )
                ),
                error=(
                    "execution_journal_recovery_failed:"
                    f"{exc.__class__.__name__}:"
                    f"{exc}"
                ),
            )

        report_data = report.to_dict()

        context.put(
            "execution_journal_recovery_report",
            report_data,
        )

        context.trade[
            "execution_journal_recovery_report"
        ] = report_data

        context.put(
            "execution_journal_recovered",
            True,
        )

        context.trade[
            "execution_journal_recovered"
        ] = True

        return RuntimeCycleResult(
            restored=bool(
                context.get(
                    "runtime_state_restored"
                )
            ),
            synchronized=True,
            journal_recovered=True,
            reconciled=False,
            recovered=False,
            persisted=False,
            submission_allowed=True,
            new_entries_allowed=bool(
                context.get(
                    "new_entries_allowed",
                    True,
                )
            ),
            recovered_from_backup=bool(
                context.get(
                    "runtime_state_recovered_from_backup"
                )
            ),
        )

    def reconcile_and_recover(
        self,
        context: StrategyContext,
        *,
        persisted_snapshot: (
            dict[str, Any] | None
        ),
    ) -> RuntimeCycleResult:
        fresh_snapshot = self._last_snapshots.get(
            str(context.symbol)
        )

        if fresh_snapshot is None:
            return RuntimeCycleResult(
                restored=bool(
                    context.get(
                        "runtime_state_restored"
                    )
                ),
                synchronized=False,
                journal_recovered=bool(
                    context.get(
                        "execution_journal_recovered"
                    )
                ),
                reconciled=False,
                recovered=False,
                persisted=False,
                submission_allowed=False,
                new_entries_allowed=False,
                recovered_from_backup=bool(
                    context.get(
                        "runtime_state_recovered_from_backup"
                    )
                ),
                error="fresh_execution_snapshot_missing",
            )

        candidate_execution_id = (
            self._candidate_execution_id(
                context
            )
        )

        report = (
            self.broker_reconciler.reconcile(
                persisted_snapshot=(
                    persisted_snapshot
                ),
                fresh_snapshot=(
                    fresh_snapshot
                ),
                candidate_execution_id=(
                    candidate_execution_id
                ),
            )
        )

        decision = (
            self.recovery_coordinator.evaluate(
                report
            )
        )

        report_data = report.to_dict()
        decision_data = decision.to_dict()
        recovery_plan_data = (
            decision.recovery_plan.to_dict()
        )

        context.put(
            "broker_reconciliation_report",
            report_data,
        )
        context.trade[
            "broker_reconciliation_report"
        ] = report_data

        context.put(
            "broker_recovery_decision",
            decision_data,
        )
        context.trade[
            "broker_recovery_decision"
        ] = decision_data

        context.put(
            "execution_recovery_plan",
            recovery_plan_data,
        )
        context.trade[
            "execution_recovery_plan"
        ] = recovery_plan_data

        context.put(
            "broker_submission_allowed",
            bool(
                decision.submission_allowed
            ),
        )
        context.trade[
            "broker_submission_allowed"
        ] = bool(
            decision.submission_allowed
        )

        context.put(
            "new_entries_allowed",
            bool(
                decision.new_entries_allowed
            ),
        )
        context.trade[
            "new_entries_allowed"
        ] = bool(
            decision.new_entries_allowed
        )

        if report.duplicate_execution:
            context.put(
                "duplicate_execution_detected",
                True,
            )
            context.trade[
                "duplicate_execution_detected"
            ] = True

        if decision.requires_manual_review:
            context.put(
                "manual_review_required",
                True,
            )
            context.trade[
                "manual_review_required"
            ] = True

        return RuntimeCycleResult(
            restored=bool(
                context.get(
                    "runtime_state_restored"
                )
            ),
            synchronized=True,
            journal_recovered=bool(
                context.get(
                    "execution_journal_recovered"
                )
            ),
            reconciled=True,
            recovered=True,
            persisted=False,
            submission_allowed=bool(
                decision.submission_allowed
            ),
            new_entries_allowed=bool(
                decision.new_entries_allowed
            ),
            recovered_from_backup=bool(
                context.get(
                    "runtime_state_recovered_from_backup"
                )
            ),
        )

    def persist(
        self,
        context: StrategyContext,
    ) -> RuntimeCycleResult:
        try:
            self.coordinator.save_context(
                context
            )
        except Exception as exc:
            return RuntimeCycleResult(
                restored=bool(
                    context.get(
                        "runtime_state_restored"
                    )
                ),
                synchronized=bool(
                    context.get(
                        "execution_state_synchronized"
                    )
                ),
                journal_recovered=bool(
                    context.get(
                        "execution_journal_recovered"
                    )
                ),
                reconciled=isinstance(
                    context.get(
                        "broker_reconciliation_report"
                    ),
                    dict,
                ),
                recovered=isinstance(
                    context.get(
                        "broker_recovery_decision"
                    ),
                    dict,
                ),
                persisted=False,
                submission_allowed=bool(
                    context.get(
                        "broker_submission_allowed"
                    )
                    is not False
                ),
                new_entries_allowed=bool(
                    context.get(
                        "new_entries_allowed",
                        True,
                    )
                ),
                recovered_from_backup=bool(
                    context.get(
                        "runtime_state_recovered_from_backup"
                    )
                ),
                error=(
                    "runtime_state_persist_failed:"
                    f"{exc.__class__.__name__}:"
                    f"{exc}"
                ),
            )

        context.put(
            "runtime_state_persisted",
            True,
        )
        context.trade[
            "runtime_state_persisted"
        ] = True

        return RuntimeCycleResult(
            restored=bool(
                context.get(
                    "runtime_state_restored"
                )
            ),
            synchronized=bool(
                context.get(
                    "execution_state_synchronized"
                )
            ),
            journal_recovered=bool(
                context.get(
                    "execution_journal_recovered"
                )
            ),
            reconciled=isinstance(
                context.get(
                    "broker_reconciliation_report"
                ),
                dict,
            ),
            recovered=isinstance(
                context.get(
                    "broker_recovery_decision"
                ),
                dict,
            ),
            persisted=True,
            submission_allowed=bool(
                context.get(
                    "broker_submission_allowed"
                )
                is not False
            ),
            new_entries_allowed=bool(
                context.get(
                    "new_entries_allowed",
                    True,
                )
            ),
            recovered_from_backup=bool(
                context.get(
                    "runtime_state_recovered_from_backup"
                )
            ),
        )

    def prepare_cycle(
        self,
        context: StrategyContext,
        *,
        strict_symbol: bool = True,
    ) -> RuntimeCycleResult:
        restore_result = self.restore(
            context,
            strict_symbol=strict_symbol,
        )

        if restore_result.error is not None:
            return restore_result

        persisted_snapshot = context.get(
            "execution_snapshot"
        )

        if not isinstance(
            persisted_snapshot,
            dict,
        ):
            persisted_snapshot = None

        context.put(
            "persisted_execution_snapshot",
            persisted_snapshot,
        )
        context.trade[
            "persisted_execution_snapshot"
        ] = persisted_snapshot

        sync_result = self.synchronize(
            context
        )

        if sync_result.error is not None:
            return sync_result

        journal_result = self.recover_journal(
            context
        )

        if journal_result.error is not None:
            return journal_result

        recovery_result = (
            self.reconcile_and_recover(
                context,
                persisted_snapshot=(
                    persisted_snapshot
                ),
            )
        )

        if recovery_result.error is not None:
            return recovery_result

        persist_result = self.persist(
            context
        )

        return RuntimeCycleResult(
            restored=recovery_result.restored,
            synchronized=True,
            journal_recovered=(
                journal_result
                .journal_recovered
            ),
            reconciled=True,
            recovered=True,
            persisted=persist_result.persisted,
            submission_allowed=(
                recovery_result
                .submission_allowed
            ),
            new_entries_allowed=(
                recovery_result
                .new_entries_allowed
            ),
            recovered_from_backup=(
                recovery_result
                .recovered_from_backup
            ),
            error=persist_result.error,
        )

    def finish_cycle(
        self,
        context: StrategyContext,
    ) -> RuntimeCycleResult:
        return self.persist(
            context
        )

    @staticmethod
    def _candidate_execution_id(
        context: StrategyContext,
    ) -> str | None:
        execution_order = context.get(
            "execution_order"
        )

        if not isinstance(
            execution_order,
            dict,
        ):
            return None

        value = execution_order.get(
            "execution_id"
        )

        if value is None:
            return None

        execution_id = str(
            value
        ).strip()

        return (
            execution_id
            if execution_id
            else None
        )