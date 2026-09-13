from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class RuntimeStateLoadResult:
    success: bool
    state: dict[str, Any] | None
    error: str | None = None
    recovered_from_backup: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "state": self.state,
            "error": self.error,
            "recovered_from_backup": (
                self.recovered_from_backup
            ),
        }


class RuntimeStateStore:
    """
    Persistent runtime-state storage.

    Features:
    - atomic JSON writes via temp file + os.replace();
    - optional .bak backup;
    - safe load with validation;
    - backup recovery if main state is corrupt;
    - no trading/execution side effects.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        create_backup: bool = True,
    ) -> None:
        self.path = Path(path)
        self.create_backup = bool(
            create_backup
        )

        self.backup_path = self.path.with_suffix(
            self.path.suffix + ".bak"
        )

    def save(
        self,
        state: dict[str, Any],
    ) -> None:
        if not isinstance(
            state,
            dict,
        ):
            raise TypeError(
                "runtime state must be a dict"
            )

        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        payload = {
            "version": 1,
            "state": state,
        }

        if (
            self.create_backup
            and self.path.exists()
        ):
            shutil.copy2(
                self.path,
                self.backup_path,
            )

        fd, temp_name = tempfile.mkstemp(
            prefix=(
                self.path.name + "."
            ),
            suffix=".tmp",
            dir=str(
                self.path.parent
            ),
            text=True,
        )

        temp_path = Path(
            temp_name
        )

        try:
            with os.fdopen(
                fd,
                "w",
                encoding="utf-8",
            ) as file:
                json.dump(
                    payload,
                    file,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )

                file.flush()
                os.fsync(
                    file.fileno()
                )

            os.replace(
                temp_path,
                self.path,
            )

        except Exception:
            try:
                temp_path.unlink(
                    missing_ok=True
                )
            finally:
                raise

    def load(
        self,
    ) -> RuntimeStateLoadResult:
        if not self.path.exists():
            return RuntimeStateLoadResult(
                success=True,
                state=None,
            )

        main_result = self._load_file(
            self.path
        )

        if main_result.success:
            return main_result

        if (
            self.create_backup
            and self.backup_path.exists()
        ):
            backup_result = self._load_file(
                self.backup_path
            )

            if backup_result.success:
                backup_result.recovered_from_backup = True
                return backup_result

        return main_result

    def clear(
        self,
    ) -> None:
        self.path.unlink(
            missing_ok=True
        )

        self.backup_path.unlink(
            missing_ok=True
        )

    def exists(
        self,
    ) -> bool:
        return self.path.exists()

    def snapshot_paths(
        self,
    ) -> dict[str, str]:
        return {
            "state": str(
                self.path
            ),
            "backup": str(
                self.backup_path
            ),
        }

    @staticmethod
    def _load_file(
        path: Path,
    ) -> RuntimeStateLoadResult:
        try:
            raw = path.read_text(
                encoding="utf-8"
            )

            payload = json.loads(
                raw
            )

        except (
            OSError,
            json.JSONDecodeError,
        ) as exc:
            return RuntimeStateLoadResult(
                success=False,
                state=None,
                error=(
                    f"runtime_state_load_failed:"
                    f"{exc.__class__.__name__}"
                ),
            )

        if not isinstance(
            payload,
            dict,
        ):
            return RuntimeStateLoadResult(
                success=False,
                state=None,
                error="runtime_state_payload_invalid",
            )

        version = payload.get(
            "version"
        )

        if version != 1:
            return RuntimeStateLoadResult(
                success=False,
                state=None,
                error=(
                    "runtime_state_version_unsupported"
                ),
            )

        state = payload.get(
            "state"
        )

        if not isinstance(
            state,
            dict,
        ):
            return RuntimeStateLoadResult(
                success=False,
                state=None,
                error="runtime_state_missing",
            )

        return RuntimeStateLoadResult(
            success=True,
            state=state,
        )