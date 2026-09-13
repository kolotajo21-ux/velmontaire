from __future__ import annotations

from pathlib import Path
from typing import Any

from .runtime_state_crash_recovery import (
    RuntimeStateCrashRecovery,
    RuntimeStateRecoveryError,
)


class RuntimeCheckpointError(ValueError):
    """Fail-closed checkpoint coordinator error."""


class RuntimeCheckpointCoordinator:
    """
    Coordinates stateful runtime processing with durable checkpoints.

    Successful process_bar -> atomic checkpoint.
    Failed process_bar -> no checkpoint mutation.
    Startup may restore the last valid checkpoint.
    """

    def __init__(
        self,
        *,
        runtime: Any,
        checkpoint_path: str | Path,
        recovery: RuntimeStateCrashRecovery | None = None,
    ) -> None:
        if not hasattr(runtime, "process_bar"):
            raise RuntimeCheckpointError("runtime_process_bar_required")
        if not hasattr(runtime, "export_state"):
            raise RuntimeCheckpointError("runtime_export_state_required")
        if not hasattr(runtime, "import_state"):
            raise RuntimeCheckpointError("runtime_import_state_required")

        self.runtime = runtime
        self.checkpoint_path = Path(checkpoint_path)
        self.recovery = recovery or RuntimeStateCrashRecovery()
        self.checkpoint_count = 0

    def restore_if_present(self) -> bool:
        if not self.checkpoint_path.exists():
            return False
        try:
            self.recovery.restore(self.runtime, self.checkpoint_path)
        except RuntimeStateRecoveryError as exc:
            raise RuntimeCheckpointError(
                f"checkpoint_restore_failed:{exc}"
            ) from exc
        return True

    def process_bar(self, *args: Any, **kwargs: Any) -> Any:
        before = self.runtime.export_state()
        try:
            result = self.runtime.process_bar(*args, **kwargs)
        except Exception:
            # Defensive rollback of in-memory state if runtime mutated before failing.
            try:
                self.runtime.import_state(before)
            except Exception as rollback_exc:
                raise RuntimeCheckpointError(
                    f"runtime_rollback_failed:{rollback_exc}"
                ) from rollback_exc
            raise

        try:
            self.recovery.save(self.runtime, self.checkpoint_path)
        except Exception as exc:
            # A successful runtime transition without durable persistence is unsafe.
            try:
                self.runtime.import_state(before)
            except Exception as rollback_exc:
                raise RuntimeCheckpointError(
                    f"checkpoint_save_and_rollback_failed:{exc}:{rollback_exc}"
                ) from rollback_exc
            raise RuntimeCheckpointError(
                f"checkpoint_save_failed:{exc}"
            ) from exc

        self.checkpoint_count += 1
        return result

    def force_checkpoint(self) -> Path:
        try:
            path = self.recovery.save(
                self.runtime,
                self.checkpoint_path,
            )
        except Exception as exc:
            raise RuntimeCheckpointError(
                f"checkpoint_save_failed:{exc}"
            ) from exc
        self.checkpoint_count += 1
        return path
