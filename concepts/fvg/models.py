from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class FVGType(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"


class FVGStatus(str, Enum):
    FRESH = "FRESH"
    PARTIAL = "PARTIAL"
    MITIGATED = "MITIGATED"
    INVALIDATED = "INVALIDATED"


class FVGEventType(str, Enum):
    FVG = "FVG"
    IFVG = "IFVG"


@dataclass(slots=True)
class FVGZone:
    zone_id: str

    zone_type: FVGType
    event_type: FVGEventType

    high: float
    low: float

    start_index: int
    middle_index: int
    end_index: int

    start_time: int
    middle_time: int
    end_time: int

    gap_size: float
    gap_ratio: float = 0.0

    status: FVGStatus = FVGStatus.FRESH

    filled_percent: float = 0.0
    touch_count: int = 0

    first_touch_time: int | None = None
    last_touch_time: int | None = None

    quality_score: float = 0.0

    active: bool = True

    source_fvg_id: str | None = None

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    @property
    def midpoint(self) -> float:
        return (
            self.high + self.low
        ) / 2.0

    @property
    def size(self) -> float:
        return max(
            self.high - self.low,
            0.0,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "zone_id": self.zone_id,
            "zone_type": self.zone_type.value,
            "event_type": self.event_type.value,
            "high": float(self.high),
            "low": float(self.low),
            "midpoint": float(
                self.midpoint
            ),
            "size": float(
                self.size
            ),
            "start_index": int(
                self.start_index
            ),
            "middle_index": int(
                self.middle_index
            ),
            "end_index": int(
                self.end_index
            ),
            "start_time": int(
                self.start_time
            ),
            "middle_time": int(
                self.middle_time
            ),
            "end_time": int(
                self.end_time
            ),
            "gap_size": float(
                self.gap_size
            ),
            "gap_ratio": float(
                self.gap_ratio
            ),
            "status": (
                self.status.value
            ),
            "filled_percent": float(
                self.filled_percent
            ),
            "touch_count": int(
                self.touch_count
            ),
            "first_touch_time": (
                int(self.first_touch_time)
                if self.first_touch_time
                is not None
                else None
            ),
            "last_touch_time": (
                int(self.last_touch_time)
                if self.last_touch_time
                is not None
                else None
            ),
            "quality_score": float(
                self.quality_score
            ),
            "active": bool(
                self.active
            ),
            "source_fvg_id": (
                str(self.source_fvg_id)
                if self.source_fvg_id
                is not None
                else None
            ),
            "metadata": dict(
                self.metadata
            ),
        }


@dataclass(slots=True)
class FVGState:
    bullish_fvgs: list[FVGZone] = field(
        default_factory=list
    )

    bearish_fvgs: list[FVGZone] = field(
        default_factory=list
    )

    bullish_ifvgs: list[FVGZone] = field(
        default_factory=list
    )

    bearish_ifvgs: list[FVGZone] = field(
        default_factory=list
    )

    last_fvg: FVGZone | None = None
    last_ifvg: FVGZone | None = None

    diagnostics: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "bullish_fvgs": [
                zone.to_dict()
                for zone
                in self.bullish_fvgs
            ],
            "bearish_fvgs": [
                zone.to_dict()
                for zone
                in self.bearish_fvgs
            ],
            "bullish_ifvgs": [
                zone.to_dict()
                for zone
                in self.bullish_ifvgs
            ],
            "bearish_ifvgs": [
                zone.to_dict()
                for zone
                in self.bearish_ifvgs
            ],
            "last_fvg": (
                self.last_fvg.to_dict()
                if self.last_fvg
                is not None
                else None
            ),
            "last_ifvg": (
                self.last_ifvg.to_dict()
                if self.last_ifvg
                is not None
                else None
            ),
            "diagnostics": dict(
                self.diagnostics
            ),
        }