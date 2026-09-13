from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .runtime_state_crash_recovery import (
    RuntimeStateCrashRecovery,
    RuntimeStateRecoveryError,
)
from .runtime_event_journal import (
    RuntimeEventJournal,
    RuntimeEventJournalError,
)
from .runtime_checkpoint_journal_reconciler import (
    RuntimeCheckpointJournalReconciler,
    RuntimeReconciliationError,
)


class RuntimeStartupRecoveryError(ValueError):
    """Fail-closed production startup recovery error."""


@dataclass(frozen=True, slots=True)
class StartupRecoveryReport:
    ready: bool
    mode: str
    checkpoint_present: bool
    journal_present: bool
    reconciliation_status: str
    source_of_truth: str
    restored_state_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "mode": self.mode,
            "checkpoint_present": self.checkpoint_present,
            "journal_present": self.journal_present,
            "reconciliation_status": self.reconciliation_status,
            "source_of_truth": self.source_of_truth,
            "restored_state_count": self.restored_state_count,
        }


class RuntimeStartupRecoveryOrchestrator:
    """
    Production startup gate.

    Runtime is allowed to become READY only after:
      checkpoint load -> journal load/replay -> reconciliation
      -> state import -> final state validation.
    """

    def __init__(
        self,
        *,
        runtime: Any,
        checkpoint_path: str | Path,
        journal_path: str | Path,
        recovery: RuntimeStateCrashRecovery | None = None,
        reconciler: RuntimeCheckpointJournalReconciler | None = None,
    ) -> None:
        for attr in ("export_state", "import_state"):
            if not hasattr(runtime, attr):
                raise RuntimeStartupRecoveryError(
                    f"runtime_{attr}_required"
                )
        self.runtime = runtime
        self.checkpoint_path = Path(checkpoint_path)
        self.journal_path = Path(journal_path)
        self.recovery = recovery or RuntimeStateCrashRecovery()
        self.reconciler = reconciler or RuntimeCheckpointJournalReconciler()
        self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready

    def recover(self) -> StartupRecoveryReport:
        self._ready = False
        checkpoint_present = self.checkpoint_path.exists()
        journal_present = self.journal_path.exists()

        if not checkpoint_present and not journal_present:
            self.runtime.import_state({})
            self._ready = True
            return StartupRecoveryReport(
                ready=True,
                mode="CLEAN_START",
                checkpoint_present=False,
                journal_present=False,
                reconciliation_status="CONSISTENT",
                source_of_truth="EMPTY",
                restored_state_count=0,
            )

        if checkpoint_present != journal_present:
            raise RuntimeStartupRecoveryError(
                "startup_durable_pair_incomplete:"
                f"checkpoint={checkpoint_present}:journal={journal_present}"
            )

        # Load checkpoint into an isolated capture, then clear runtime until
        # reconciliation succeeds.
        try:
            self.recovery.restore(self.runtime, self.checkpoint_path)
            checkpoint_states = self.runtime.export_state()
            self.runtime.import_state({})
        except RuntimeStateRecoveryError as exc:
            raise RuntimeStartupRecoveryError(
                f"startup_checkpoint_failed:{exc}"
            ) from exc

        try:
            journal = RuntimeEventJournal(self.journal_path)
        except RuntimeEventJournalError as exc:
            raise RuntimeStartupRecoveryError(
                f"startup_journal_failed:{exc}"
            ) from exc

        try:
            reconciled, rec_report = self.reconciler.reconcile(
                checkpoint_states=checkpoint_states,
                events=journal.events(),
            )
        except RuntimeReconciliationError as exc:
            raise RuntimeStartupRecoveryError(
                f"startup_reconciliation_failed:{exc}"
            ) from exc

        try:
            self.runtime.import_state(reconciled)
            final_state = self.runtime.export_state()
        except Exception as exc:
            self.runtime.import_state({})
            raise RuntimeStartupRecoveryError(
                f"startup_state_import_failed:{exc}"
            ) from exc

        if final_state != reconciled:
            self.runtime.import_state({})
            raise RuntimeStartupRecoveryError(
                "startup_final_state_validation_failed"
            )

        self._ready = True
        mode = (
            "RECOVERED"
            if rec_report.status == "CONSISTENT"
            else "REPAIRED_AND_RECOVERED"
        )
        return StartupRecoveryReport(
            ready=True,
            mode=mode,
            checkpoint_present=True,
            journal_present=True,
            reconciliation_status=rec_report.status,
            source_of_truth=rec_report.source_of_truth,
            restored_state_count=len(final_state),
        )

    def require_ready(self) -> None:
        if not self._ready:
            raise RuntimeStartupRecoveryError("runtime_startup_not_ready")
