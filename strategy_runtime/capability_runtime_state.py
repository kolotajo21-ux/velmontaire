from __future__ import annotations

from dataclasses import dataclass, asdict
from enum import Enum
from typing import Any


class CapabilityRuntimeStateError(ValueError):
    """Fail-closed state error."""


class SequenceRuntimeStatus(str, Enum):
    IDLE = "IDLE"
    ACTIVE = "ACTIVE"
    MATCHED = "MATCHED"
    EXPIRED = "EXPIRED"


@dataclass(slots=True)
class SequenceRuntimeState:
    capability_id: str
    version: int
    symbol: str
    current_step: int = 0
    started_bar: int | None = None
    last_step_bar: int | None = None
    last_bar: int | None = None
    status: SequenceRuntimeStatus = SequenceRuntimeStatus.IDLE

    def key(self) -> str:
        return (
            f"{self.capability_id}@v{self.version}:"
            f"{self.symbol.upper()}"
        )

    def reset(self) -> None:
        self.current_step = 0
        self.started_bar = None
        self.last_step_bar = None
        self.status = SequenceRuntimeStatus.IDLE

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SequenceRuntimeState":
        if not isinstance(data, dict):
            raise CapabilityRuntimeStateError("state_payload_must_be_object")
        try:
            status = SequenceRuntimeStatus(
                str(data.get("status", "IDLE"))
            )
            return cls(
                capability_id=str(data["capability_id"]),
                version=int(data["version"]),
                symbol=str(data["symbol"]),
                current_step=int(data.get("current_step", 0)),
                started_bar=(
                    None if data.get("started_bar") is None
                    else int(data["started_bar"])
                ),
                last_step_bar=(
                    None if data.get("last_step_bar") is None
                    else int(data["last_step_bar"])
                ),
                last_bar=(
                    None if data.get("last_bar") is None
                    else int(data["last_bar"])
                ),
                status=status,
            )
        except Exception as exc:
            raise CapabilityRuntimeStateError(
                f"invalid_state_payload:{exc}"
            ) from exc
