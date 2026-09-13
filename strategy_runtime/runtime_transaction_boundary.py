from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import shutil
import tempfile


class RuntimeTransactionError(ValueError):
    """Fail-closed durable runtime transaction error."""


@dataclass(frozen=True, slots=True)
class RuntimeTransactionResult:
    committed: bool
    transaction_id: int
    runtime_result: Any


class RuntimeTransactionBoundary:
    """
    Atomic boundary around:
      process_bar -> journal append(s) -> checkpoint

    The boundary snapshots:
      - in-memory runtime state
      - durable journal file
      - durable checkpoint file

    Any failure restores all three to their pre-transaction state.
    """

    def __init__(
        self,
        *,
        runtime: Any,
        journaled_coordinator: Any,
        checkpoint_path: str | Path,
        journal_path: str | Path,
    ) -> None:
        if not hasattr(runtime, "export_state") or not hasattr(runtime, "import_state"):
            raise RuntimeTransactionError("runtime_state_interface_required")
        if not hasattr(journaled_coordinator, "process_bar"):
            raise RuntimeTransactionError("journaled_coordinator_required")

        self.runtime = runtime
        self.coordinator = journaled_coordinator
        self.checkpoint_path = Path(checkpoint_path)
        self.journal_path = Path(journal_path)
        self._transaction_id = 0

    def process_bar(self, *args: Any, **kwargs: Any) -> RuntimeTransactionResult:
        before_state = self.runtime.export_state()

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            cp_backup = tmp / "checkpoint.backup"
            jr_backup = tmp / "journal.backup"

            cp_existed = self.checkpoint_path.exists()
            jr_existed = self.journal_path.exists()

            if cp_existed:
                shutil.copy2(self.checkpoint_path, cp_backup)
            if jr_existed:
                shutil.copy2(self.journal_path, jr_backup)

            try:
                result = self.coordinator.process_bar(*args, **kwargs)
            except Exception as exc:
                self._rollback(
                    before_state=before_state,
                    cp_existed=cp_existed,
                    jr_existed=jr_existed,
                    cp_backup=cp_backup,
                    jr_backup=jr_backup,
                )
                raise RuntimeTransactionError(
                    f"runtime_transaction_aborted:{exc}"
                ) from exc

        self._transaction_id += 1
        return RuntimeTransactionResult(
            committed=True,
            transaction_id=self._transaction_id,
            runtime_result=result,
        )

    def _rollback(
        self,
        *,
        before_state: dict[str, Any],
        cp_existed: bool,
        jr_existed: bool,
        cp_backup: Path,
        jr_backup: Path,
    ) -> None:
        errors = []
        try:
            self.runtime.import_state(before_state)
        except Exception as exc:
            errors.append(f"runtime:{exc}")

        try:
            self._restore_file(self.checkpoint_path, cp_backup, cp_existed)
        except Exception as exc:
            errors.append(f"checkpoint:{exc}")

        try:
            self._restore_file(self.journal_path, jr_backup, jr_existed)
        except Exception as exc:
            errors.append(f"journal:{exc}")

        # Journal object may have cached events; reload it from disk.
        try:
            journal = getattr(self.coordinator, "journal", None)
            if journal is not None:
                journal._events = []
                journal._ids = set()
                if self.journal_path.exists():
                    journal._load()
        except Exception as exc:
            errors.append(f"journal_cache:{exc}")

        if errors:
            raise RuntimeTransactionError(
                "runtime_transaction_rollback_failed:" + "|".join(errors)
            )

    @staticmethod
    def _restore_file(target: Path, backup: Path, existed: bool) -> None:
        if existed:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, target)
        elif target.exists():
            target.unlink()
