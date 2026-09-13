from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class PositionManagementPersistentState:
    execution_id: str
    completed_request_keys: list[str] = field(default_factory=list)
    last_request_key: str | None = None
    last_reason: str | None = None
    last_success: bool | None = None
    last_attempted: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "completed_request_keys": list(self.completed_request_keys),
            "last_request_key": self.last_request_key,
            "last_reason": self.last_reason,
            "last_success": self.last_success,
            "last_attempted": self.last_attempted,
        }

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> "PositionManagementPersistentState":
        return cls(
            execution_id=str(data["execution_id"]),
            completed_request_keys=[
                str(x)
                for x in data.get(
                    "completed_request_keys",
                    [],
                )
            ],
            last_request_key=data.get("last_request_key"),
            last_reason=data.get("last_reason"),
            last_success=data.get("last_success"),
            last_attempted=data.get("last_attempted"),
        )


class PositionManagementStateStore:
    """
    Day 72 crash-safe persistent store for idempotent management cycles.

    Atomic persistence:
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

    def get(
        self,
        execution_id: str,
    ) -> PositionManagementPersistentState:
        execution_id = str(execution_id).strip()

        if not execution_id:
            raise ValueError(
                "execution_id is required"
            )

        data = self._load()

        raw = data.get(execution_id)

        if raw is None:
            return PositionManagementPersistentState(
                execution_id=execution_id
            )

        return PositionManagementPersistentState.from_dict(
            raw
        )

    def save(
        self,
        state: PositionManagementPersistentState,
    ) -> None:
        data = self._load()
        data[state.execution_id] = state.to_dict()
        self._atomic_write(data)

    def mark_completed(
        self,
        *,
        execution_id: str,
        request_key: str,
        reason: str,
        success: bool,
        attempted: bool,
    ) -> PositionManagementPersistentState:
        state = self.get(execution_id)

        if request_key not in state.completed_request_keys:
            state.completed_request_keys.append(
                request_key
            )

        state.last_request_key = request_key
        state.last_reason = reason
        state.last_success = bool(success)
        state.last_attempted = bool(attempted)

        self.save(state)

        return state

    def record_attempt(
        self,
        *,
        execution_id: str,
        request_key: str,
        reason: str,
        success: bool,
        attempted: bool,
    ) -> PositionManagementPersistentState:
        state = self.get(execution_id)

        state.last_request_key = request_key
        state.last_reason = reason
        state.last_success = bool(success)
        state.last_attempted = bool(attempted)

        self.save(state)

        return state

    def _load(
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

        if not isinstance(data, dict):
            raise ValueError(
                "position management state root must be a JSON object"
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