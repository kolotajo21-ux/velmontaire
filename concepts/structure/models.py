from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class StructureDirection(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    RANGE = "RANGE"


class SwingType(str, Enum):
    HIGH = "HIGH"
    LOW = "LOW"


class StructurePointType(str, Enum):
    HH = "HH"
    HL = "HL"
    LH = "LH"
    LL = "LL"
    UNKNOWN = "UNKNOWN"


class StructureEventType(str, Enum):
    BOS = "BOS"
    CHOCH = "CHOCH"
    MSS = "MSS"


@dataclass(slots=True)
class SwingPoint:
    index: int
    time: int
    price: float
    swing_type: SwingType

    point_type: StructurePointType = (
        StructurePointType.UNKNOWN
    )

    strength: int = 1
    confirmed: bool = True

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": int(self.index),
            "time": int(self.time),
            "price": float(self.price),
            "swing_type": self.swing_type.value,
            "point_type": self.point_type.value,
            "strength": int(self.strength),
            "confirmed": bool(self.confirmed),
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class StructureEvent:
    event_type: StructureEventType
    direction: StructureDirection

    index: int
    time: int

    broken_level: float
    close_price: float

    source_swing_index: int | None = None
    source_swing_time: int | None = None

    body_ratio: float = 0.0
    break_distance: float = 0.0
    break_ratio: float = 0.0

    confirmed: bool = True
    quality_score: float = 0.0

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    @property
    def event_id(self) -> str:
        return (
            f"{self.event_type.value}:"
            f"{self.direction.value}:"
            f"{self.time}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "type": self.event_type.value,
            "direction": self.direction.value,
            "index": int(self.index),
            "time": int(self.time),
            "broken_level": float(
                self.broken_level
            ),
            "close_price": float(
                self.close_price
            ),
            "source_swing_index": (
                int(self.source_swing_index)
                if self.source_swing_index
                is not None
                else None
            ),
            "source_swing_time": (
                int(self.source_swing_time)
                if self.source_swing_time
                is not None
                else None
            ),
            "body_ratio": float(
                self.body_ratio
            ),
            "break_distance": float(
                self.break_distance
            ),
            "break_ratio": float(
                self.break_ratio
            ),
            "confirmed": bool(
                self.confirmed
            ),
            "quality_score": float(
                self.quality_score
            ),
            "metadata": dict(
                self.metadata
            ),
        }


@dataclass(slots=True)
class ProtectedLevel:
    direction: StructureDirection
    level_type: SwingType

    price: float
    index: int
    time: int

    valid: bool = True
    broken_time: int | None = None

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "direction": self.direction.value,
            "level_type": self.level_type.value,
            "price": float(self.price),
            "index": int(self.index),
            "time": int(self.time),
            "valid": bool(self.valid),
            "broken_time": (
                int(self.broken_time)
                if self.broken_time
                is not None
                else None
            ),
            "metadata": dict(
                self.metadata
            ),
        }


@dataclass(slots=True)
class StructureState:
    trend: StructureDirection = (
        StructureDirection.RANGE
    )

    swings: list[SwingPoint] = field(
        default_factory=list
    )

    events: list[StructureEvent] = field(
        default_factory=list
    )

    protected_high: ProtectedLevel | None = None
    protected_low: ProtectedLevel | None = None

    last_bos: StructureEvent | None = None
    last_choch: StructureEvent | None = None
    last_mss: StructureEvent | None = None

    diagnostics: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "trend": self.trend.value,
            "direction": self.trend.value,
            "swings": [
                swing.to_dict()
                for swing in self.swings
            ],
            "events": [
                event.to_dict()
                for event in self.events
            ],
            "protected_high": (
                self.protected_high.to_dict()
                if self.protected_high
                is not None
                else None
            ),
            "protected_low": (
                self.protected_low.to_dict()
                if self.protected_low
                is not None
                else None
            ),
            "last_bos": (
                self.last_bos.to_dict()
                if self.last_bos
                is not None
                else None
            ),
            "last_choch": (
                self.last_choch.to_dict()
                if self.last_choch
                is not None
                else None
            ),
            "last_mss": (
                self.last_mss.to_dict()
                if self.last_mss
                is not None
                else None
            ),
            "diagnostics": dict(
                self.diagnostics
            ),
        }