from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ExecutionLockHandle:
    execution_id: str
    acquired: bool
    lock_path: str
    owner_pid: int | None = None
    owner_thread_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "acquired": self.acquired,
            "lock_path": self.lock_path,
            "owner_pid": self.owner_pid,
            "owner_thread_id": self.owner_thread_id,
        }


class ExecutionLock:
    """
    File-based non-blocking lock per execution_id.

    Guarantees:
    - only one process/thread can own a given execution_id lock
      at the same time;
    - second acquire attempt returns acquired=False;
    - release removes the lock file;
    - no broker calls are performed here.

    Lock files are created atomically using O_CREAT | O_EXCL.
    """

    def __init__(
        self,
        directory: str | Path,
    ) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(
            parents=True,
            exist_ok=True,
        )

    def acquire(
        self,
        execution_id: str,
    ) -> ExecutionLockHandle:
        normalized = self._normalize_execution_id(
            execution_id
        )

        lock_path = self._lock_path(
            normalized
        )

        pid = os.getpid()
        thread_id = threading.get_ident()

        flags = (
            os.O_CREAT
            | os.O_EXCL
            | os.O_WRONLY
        )

        try:
            fd = os.open(
                lock_path,
                flags,
            )
        except FileExistsError:
            return ExecutionLockHandle(
                execution_id=normalized,
                acquired=False,
                lock_path=str(lock_path),
            )

        try:
            payload = (
                f"execution_id={normalized}\n"
                f"pid={pid}\n"
                f"thread_id={thread_id}\n"
            )

            os.write(
                fd,
                payload.encode("utf-8"),
            )

            os.fsync(fd)
        finally:
            os.close(fd)

        return ExecutionLockHandle(
            execution_id=normalized,
            acquired=True,
            lock_path=str(lock_path),
            owner_pid=pid,
            owner_thread_id=thread_id,
        )

    def release(
        self,
        handle: ExecutionLockHandle,
    ) -> None:
        if not handle.acquired:
            return

        path = Path(
            handle.lock_path
        )

        path.unlink(
            missing_ok=True
        )

    def is_locked(
        self,
        execution_id: str,
    ) -> bool:
        normalized = self._normalize_execution_id(
            execution_id
        )

        return self._lock_path(
            normalized
        ).exists()

    def _lock_path(
        self,
        execution_id: str,
    ) -> Path:
        safe = self._safe_filename(
            execution_id
        )

        return (
            self.directory
            / f"{safe}.lock"
        )

    @staticmethod
    def _normalize_execution_id(
        execution_id: str,
    ) -> str:
        value = str(
            execution_id
        ).strip()

        if not value:
            raise ValueError(
                "execution_id is required"
            )

        return value

    @staticmethod
    def _safe_filename(
        execution_id: str,
    ) -> str:
        allowed = []

        for char in execution_id:
            if (
                char.isalnum()
                or char in {
                    "-",
                    "_",
                    ".",
                }
            ):
                allowed.append(char)
            else:
                allowed.append("_")

        safe = "".join(
            allowed
        ).strip("._")

        if not safe:
            raise ValueError(
                "execution_id cannot produce empty lock name"
            )

        return safe