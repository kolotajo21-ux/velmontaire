from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class ExecutionJournalStatus(str, Enum):
    SUBMISSION_INTENT = "SUBMISSION_INTENT"
    SUBMITTED = "SUBMITTED"
    REJECTED = "REJECTED"
    CONFIRMED = "CONFIRMED"


@dataclass(slots=True)
class ExecutionJournalEntry:
    execution_id: str
    status: ExecutionJournalStatus
    updated_at: str

    symbol: str | None = None
    broker_order_id: str | None = None
    broker_deal_id: str | None = None
    error: str | None = None

    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> "ExecutionJournalEntry":
        return cls(
            execution_id=str(
                data["execution_id"]
            ),
            status=ExecutionJournalStatus(
                data["status"]
            ),
            updated_at=str(
                data["updated_at"]
            ),
            symbol=data.get("symbol"),
            broker_order_id=(
                str(data["broker_order_id"])
                if data.get("broker_order_id")
                is not None
                else None
            ),
            broker_deal_id=(
                str(data["broker_deal_id"])
                if data.get("broker_deal_id")
                is not None
                else None
            ),
            error=data.get("error"),
            metadata=data.get("metadata"),
        )


class ExecutionJournal:
    """
    Crash-safe write-ahead execution journal.

    Critical rule:
    SUBMISSION_INTENT must be persisted BEFORE order_send().

    Writes are atomic:
        temp file -> flush -> fsync -> os.replace
    """

    def __init__(
        self,
        path: str | Path,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

    def record_intent(
        self,
        *,
        execution_id: str,
        symbol: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ExecutionJournalEntry:
        return self._transition(
            execution_id=execution_id,
            status=(
                ExecutionJournalStatus
                .SUBMISSION_INTENT
            ),
            symbol=symbol,
            metadata=metadata,
        )

    def mark_submitted(
        self,
        *,
        execution_id: str,
        broker_order_id: str | int | None = None,
        broker_deal_id: str | int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ExecutionJournalEntry:
        return self._transition(
            execution_id=execution_id,
            status=ExecutionJournalStatus.SUBMITTED,
            broker_order_id=broker_order_id,
            broker_deal_id=broker_deal_id,
            metadata=metadata,
        )

    def mark_rejected(
        self,
        *,
        execution_id: str,
        error: str,
        metadata: dict[str, Any] | None = None,
    ) -> ExecutionJournalEntry:
        return self._transition(
            execution_id=execution_id,
            status=ExecutionJournalStatus.REJECTED,
            error=error,
            metadata=metadata,
        )

    def mark_confirmed(
        self,
        *,
        execution_id: str,
        broker_order_id: str | int | None = None,
        broker_deal_id: str | int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ExecutionJournalEntry:
        return self._transition(
            execution_id=execution_id,
            status=ExecutionJournalStatus.CONFIRMED,
            broker_order_id=broker_order_id,
            broker_deal_id=broker_deal_id,
            metadata=metadata,
        )

    def get(
        self,
        execution_id: str,
    ) -> ExecutionJournalEntry | None:
        entries = self._load_entries()

        raw = entries.get(
            str(execution_id)
        )

        if raw is None:
            return None

        return ExecutionJournalEntry.from_dict(
            raw
        )

    def all(
        self,
    ) -> list[ExecutionJournalEntry]:
        entries = self._load_entries()

        return [
            ExecutionJournalEntry.from_dict(
                raw
            )
            for raw in entries.values()
        ]

    def unresolved(
        self,
    ) -> list[ExecutionJournalEntry]:
        unresolved_statuses = {
            ExecutionJournalStatus.SUBMISSION_INTENT,
            ExecutionJournalStatus.SUBMITTED,
        }

        return [
            entry
            for entry in self.all()
            if entry.status
            in unresolved_statuses
        ]

    def blocks_submission(
        self,
        execution_id: str,
    ) -> bool:
        entry = self.get(
            execution_id
        )

        if entry is None:
            return False

        return entry.status in {
            ExecutionJournalStatus.SUBMISSION_INTENT,
            ExecutionJournalStatus.SUBMITTED,
            ExecutionJournalStatus.CONFIRMED,
        }

    def _transition(
        self,
        *,
        execution_id: str,
        status: ExecutionJournalStatus,
        symbol: str | None = None,
        broker_order_id: str | int | None = None,
        broker_deal_id: str | int | None = None,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ExecutionJournalEntry:
        execution_id = str(
            execution_id
        ).strip()

        if not execution_id:
            raise ValueError(
                "execution_id is required"
            )

        entries = self._load_entries()

        previous = entries.get(
            execution_id,
            {},
        )

        entry = ExecutionJournalEntry(
            execution_id=execution_id,
            status=status,
            updated_at=self._utc_now(),
            symbol=(
                symbol
                if symbol is not None
                else previous.get("symbol")
            ),
            broker_order_id=self._string_or_previous(
                broker_order_id,
                previous.get(
                    "broker_order_id"
                ),
            ),
            broker_deal_id=self._string_or_previous(
                broker_deal_id,
                previous.get(
                    "broker_deal_id"
                ),
            ),
            error=(
                error
                if error is not None
                else previous.get("error")
            ),
            metadata=self._merge_metadata(
                previous.get("metadata"),
                metadata,
            ),
        )

        entries[
            execution_id
        ] = entry.to_dict()

        self._atomic_write(
            entries
        )

        return entry

    def _load_entries(
        self,
    ) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}

        text = self.path.read_text(
            encoding="utf-8"
        ).strip()

        if not text:
            return {}

        data = json.loads(text)

        if not isinstance(
            data,
            dict,
        ):
            raise ValueError(
                "execution journal root "
                "must be a JSON object"
            )

        return data

    def _atomic_write(
        self,
        data: dict[str, dict[str, Any]],
    ) -> None:
        temp_path = self.path.with_suffix(
            self.path.suffix + ".tmp"
        )

        payload = json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )

        with open(
            temp_path,
            "w",
            encoding="utf-8",
        ) as file:
            file.write(payload)
            file.flush()
            os.fsync(
                file.fileno()
            )

        os.replace(
            temp_path,
            self.path,
        )

    @staticmethod
    def _utc_now() -> str:
        return (
            datetime.now(
                timezone.utc
            )
            .isoformat()
        )

    @staticmethod
    def _string_or_previous(
        value: str | int | None,
        previous: Any,
    ) -> str | None:
        if value is not None:
            return str(value)

        if previous is not None:
            return str(previous)

        return None

    @staticmethod
    def _merge_metadata(
        previous: Any,
        current: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        merged: dict[str, Any] = {}

        if isinstance(
            previous,
            dict,
        ):
            merged.update(
                previous
            )

        if isinstance(
            current,
            dict,
        ):
            merged.update(
                current
            )

        return (
            merged
            if merged
            else None
        )