from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SessionType(str, Enum):
    ASIA = "ASIA"
    LONDON = "LONDON"
    NEW_YORK = "NEW_YORK"


@dataclass(slots=True)
class SessionZone:
    session_type: SessionType

    start_time: int
    end_time: int

    high: float
    low: float

    open_price: float
    close_price: float

    active: bool = False

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    @property
    def midpoint(self) -> float:
        return (
            self.high + self.low
        ) / 2.0

    @property
    def range(self) -> float:
        return max(
            self.high - self.low,
            0.0,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_type": self.session_type.value,
            "start_time": int(self.start_time),
            "end_time": int(self.end_time),
            "high": float(self.high),
            "low": float(self.low),
            "open_price": float(self.open_price),
            "close_price": float(self.close_price),
            "midpoint": float(self.midpoint),
            "range": float(self.range),
            "active": bool(self.active),
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class PreviousDayLevels:
    high: float
    low: float

    date: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "high": float(self.high),
            "low": float(self.low),
            "date": int(self.date),
        }


@dataclass(slots=True)
class PremiumDiscountZone:
    equilibrium: float

    premium_high: float
    premium_low: float

    discount_high: float
    discount_low: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "equilibrium": float(self.equilibrium),
            "premium_high": float(self.premium_high),
            "premium_low": float(self.premium_low),
            "discount_high": float(self.discount_high),
            "discount_low": float(self.discount_low),
        }


@dataclass(slots=True)
class SessionState:
    asia: SessionZone | None = None
    london: SessionZone | None = None
    new_york: SessionZone | None = None

    previous_day: PreviousDayLevels | None = None

    premium_discount: PremiumDiscountZone | None = None

    diagnostics: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "asia": (
                self.asia.to_dict()
                if self.asia
                else None
            ),
            "london": (
                self.london.to_dict()
                if self.london
                else None
            ),
            "new_york": (
                self.new_york.to_dict()
                if self.new_york
                else None
            ),
            "previous_day": (
                self.previous_day.to_dict()
                if self.previous_day
                else None
            ),
            "premium_discount": (
                self.premium_discount.to_dict()
                if self.premium_discount
                else None
            ),
            "diagnostics": dict(
                self.diagnostics
            ),
        }