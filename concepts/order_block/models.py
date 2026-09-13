from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class OrderBlockType(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"


class MitigationStatus(str, Enum):
    FRESH = "FRESH"
    TOUCHED = "TOUCHED"
    PARTIAL = "PARTIAL"
    MITIGATED = "MITIGATED"
    INVALIDATED = "INVALIDATED"


@dataclass(slots=True)
class Mitigation:
    first_touch_time: int | None = None
    last_touch_time: int | None = None

    touch_count: int = 0

    filled_percent: float = 0.0

    status: MitigationStatus = (
        MitigationStatus.FRESH
    )

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "first_touch_time": self.first_touch_time,
            "last_touch_time": self.last_touch_time,
            "touch_count": self.touch_count,
            "filled_percent": self.filled_percent,
            "status": self.status.value,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class OrderBlock:
    block_id: str

    block_type: OrderBlockType

    high: float
    low: float

    open_price: float
    close_price: float

    index: int
    time: int

    impulse_index: int
    impulse_time: int

    quality_score: float = 0.0

    active: bool = True

    mitigation: Mitigation = field(
        default_factory=Mitigation
    )

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_id": self.block_id,
            "block_type": self.block_type.value,
            "high": self.high,
            "low": self.low,
            "open_price": self.open_price,
            "close_price": self.close_price,
            "index": self.index,
            "time": self.time,
            "impulse_index": self.impulse_index,
            "impulse_time": self.impulse_time,
            "quality_score": self.quality_score,
            "active": self.active,
            "mitigation": self.mitigation.to_dict(),
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class OrderBlockState:
    bullish_blocks: list[OrderBlock] = field(
        default_factory=list
    )

    bearish_blocks: list[OrderBlock] = field(
        default_factory=list
    )

    last_bullish: OrderBlock | None = None

    last_bearish: OrderBlock | None = None

    diagnostics: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "bullish_blocks": [
                block.to_dict()
                for block in self.bullish_blocks
            ],
            "bearish_blocks": [
                block.to_dict()
                for block in self.bearish_blocks
            ],
            "last_bullish": (
                self.last_bullish.to_dict()
                if self.last_bullish
                else None
            ),
            "last_bearish": (
                self.last_bearish.to_dict()
                if self.last_bearish
                else None
            ),
            "diagnostics": dict(
                self.diagnostics
            ),
        }