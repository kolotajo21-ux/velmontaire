from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class LiquiditySide(str, Enum):
    BUY_SIDE = "BUY_SIDE"
    SELL_SIDE = "SELL_SIDE"


class EqualLevelType(str, Enum):
    EQH = "EQH"
    EQL = "EQL"


class LiquidityEventType(str, Enum):
    POOL = "POOL"
    SWEEP = "SWEEP"
    RUN = "RUN"


class LiquidityDirection(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


@dataclass(slots=True)
class EqualLevel:
    level_type: EqualLevelType
    side: LiquiditySide

    price: float

    first_index: int
    first_time: int

    second_index: int
    second_time: int

    distance: float = 0.0
    tolerance: float = 0.0

    confirmed: bool = True
    tested: bool = False
    invalidated: bool = False

    touch_count: int = 2

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    @property
    def level_id(self) -> str:
        return (
            f"{self.level_type.value}:"
            f"{self.first_time}:"
            f"{self.second_time}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "level_id": self.level_id,
            "level_type": self.level_type.value,
            "side": self.side.value,
            "price": float(self.price),
            "first_index": int(self.first_index),
            "first_time": int(self.first_time),
            "second_index": int(self.second_index),
            "second_time": int(self.second_time),
            "distance": float(self.distance),
            "tolerance": float(self.tolerance),
            "confirmed": bool(self.confirmed),
            "tested": bool(self.tested),
            "invalidated": bool(
                self.invalidated
            ),
            "touch_count": int(
                self.touch_count
            ),
            "metadata": dict(
                self.metadata
            ),
        }


@dataclass(slots=True)
class LiquidityPool:
    side: LiquiditySide
    price: float

    start_index: int
    start_time: int

    end_index: int
    end_time: int

    source_type: str
    source_ids: list[str] = field(
        default_factory=list
    )

    strength: float = 0.0
    active: bool = True
    swept: bool = False
    invalidated: bool = False

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    @property
    def pool_id(self) -> str:
        return (
            f"{self.side.value}:"
            f"{self.start_time}:"
            f"{self.end_time}:"
            f"{self.price}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "pool_id": self.pool_id,
            "side": self.side.value,
            "price": float(self.price),
            "start_index": int(
                self.start_index
            ),
            "start_time": int(
                self.start_time
            ),
            "end_index": int(
                self.end_index
            ),
            "end_time": int(
                self.end_time
            ),
            "source_type": str(
                self.source_type
            ),
            "source_ids": list(
                self.source_ids
            ),
            "strength": float(
                self.strength
            ),
            "active": bool(
                self.active
            ),
            "swept": bool(
                self.swept
            ),
            "invalidated": bool(
                self.invalidated
            ),
            "metadata": dict(
                self.metadata
            ),
        }


@dataclass(slots=True)
class LiquidityEvent:
    event_type: LiquidityEventType
    side: LiquiditySide
    direction: LiquidityDirection

    index: int
    time: int

    level: float
    close_price: float
    extreme_price: float

    penetration: float = 0.0
    penetration_ratio: float = 0.0

    closed_back_inside: bool = False
    continued_beyond: bool = False

    confirmed: bool = True
    quality_score: float = 0.0

    source_pool_id: str | None = None

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    @property
    def event_id(self) -> str:
        return (
            f"{self.event_type.value}:"
            f"{self.side.value}:"
            f"{self.time}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": (
                self.event_type.value
            ),
            "type": (
                self.event_type.value
            ),
            "side": self.side.value,
            "direction": (
                self.direction.value
            ),
            "index": int(
                self.index
            ),
            "time": int(
                self.time
            ),
            "level": float(
                self.level
            ),
            "close_price": float(
                self.close_price
            ),
            "extreme_price": float(
                self.extreme_price
            ),
            "penetration": float(
                self.penetration
            ),
            "penetration_ratio": float(
                self.penetration_ratio
            ),
            "closed_back_inside": bool(
                self.closed_back_inside
            ),
            "continued_beyond": bool(
                self.continued_beyond
            ),
            "confirmed": bool(
                self.confirmed
            ),
            "quality_score": float(
                self.quality_score
            ),
            "source_pool_id": (
                str(self.source_pool_id)
                if self.source_pool_id
                is not None
                else None
            ),
            "metadata": dict(
                self.metadata
            ),
        }


@dataclass(slots=True)
class LiquidityState:
    equal_highs: list[EqualLevel] = field(
        default_factory=list
    )

    equal_lows: list[EqualLevel] = field(
        default_factory=list
    )

    pools: list[LiquidityPool] = field(
        default_factory=list
    )

    events: list[LiquidityEvent] = field(
        default_factory=list
    )

    last_sweep: LiquidityEvent | None = None
    last_run: LiquidityEvent | None = None

    diagnostics: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "equal_highs": [
                level.to_dict()
                for level in self.equal_highs
            ],
            "equal_lows": [
                level.to_dict()
                for level in self.equal_lows
            ],
            "pools": [
                pool.to_dict()
                for pool in self.pools
            ],
            "events": [
                event.to_dict()
                for event in self.events
            ],
            "last_sweep": (
                self.last_sweep.to_dict()
                if self.last_sweep
                is not None
                else None
            ),
            "last_run": (
                self.last_run.to_dict()
                if self.last_run
                is not None
                else None
            ),
            "diagnostics": dict(
                self.diagnostics
            ),
        }