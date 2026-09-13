from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class PositionManagementJournalStatus(str, Enum):
    INTENT = "INTENT"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(slots=True)
class PositionManagementJournalEntry:
    request_key: str
    execution_id: str
    status: PositionManagementJournalStatus
    action: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_key": self.request_key,
            "execution_id": self.execution_id,
            "status": self.status.value,
            "action": self.action,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> "PositionManagementJournalEntry":
        return cls(
            request_key=str(data["request_key"]),
            execution_id=str(data["execution_id"]),
            status=PositionManagementJournalStatus(
                str(data["status"])
            ),
            action=str(data["action"]),
            metadata=dict(data.get("metadata") or {}),
        )


class PositionManagementJournal:
    """
    Day 73 write-ahead journal for live position-management requests.

    The INTENT is persisted BEFORE any broker call. Therefore a process crash
    can never silently turn an already-attempted management request back into
    READY and cause a blind duplicate broker call after restart.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def get(
        self,
        request_key: str,
    ) -> PositionManagementJournalEntry | None:
        raw = self._load().get(str(request_key))
        if raw is None:
            return None
        return PositionManagementJournalEntry.from_dict(raw)

    def begin(
        self,
        *,
        request_key: str,
        execution_id: str,
        action: str,
        metadata: dict[str, Any] | None = None,
    ) -> PositionManagementJournalEntry:
        data = self._load()
        existing = data.get(request_key)

        if existing is not None:
            return PositionManagementJournalEntry.from_dict(existing)

        entry = PositionManagementJournalEntry(
            request_key=request_key,
            execution_id=execution_id,
            status=PositionManagementJournalStatus.INTENT,
            action=action,
            metadata=dict(metadata or {}),
        )
        data[request_key] = entry.to_dict()
        self._atomic_write(data)
        return entry

    def mark_completed(
        self,
        *,
        request_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> PositionManagementJournalEntry:
        return self._transition(
            request_key=request_key,
            status=PositionManagementJournalStatus.COMPLETED,
            metadata=metadata,
        )

    def mark_failed(
        self,
        *,
        request_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> PositionManagementJournalEntry:
        return self._transition(
            request_key=request_key,
            status=PositionManagementJournalStatus.FAILED,
            metadata=metadata,
        )

    def _transition(
        self,
        *,
        request_key: str,
        status: PositionManagementJournalStatus,
        metadata: dict[str, Any] | None,
    ) -> PositionManagementJournalEntry:
        data = self._load()
        raw = data.get(request_key)

        if raw is None:
            raise KeyError("position_management_journal_intent_missing")

        entry = PositionManagementJournalEntry.from_dict(raw)
        entry.status = status
        entry.metadata.update(dict(metadata or {}))
        data[request_key] = entry.to_dict()
        self._atomic_write(data)
        return entry

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}

        text = self.path.read_text(encoding="utf-8").strip()
        if not text:
            return {}

        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError(
                "position management journal root must be a JSON object"
            )
        return data

    def _atomic_write(
        self,
        data: dict[str, dict[str, Any]],
    ) -> None:
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        payload = json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )

        with open(temp, "w", encoding="utf-8") as file:
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())

        os.replace(temp, self.path)