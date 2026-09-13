from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EntryDirection(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class EntryOrderType(str, Enum):
    MARKET = "MARKET"
    BUY_LIMIT = "BUY_LIMIT"
    SELL_LIMIT = "SELL_LIMIT"
    BUY_STOP = "BUY_STOP"
    SELL_STOP = "SELL_STOP"


class EntrySignalStatus(str, Enum):
    READY = "READY"
    WAITING = "WAITING"
    REJECTED = "REJECTED"
    INVALID = "INVALID"


@dataclass(slots=True)
class EntrySignal:
    signal_id: str

    symbol: str
    direction: EntryDirection
    order_type: EntryOrderType

    entry_price: float
    stop_loss: float
    take_profit: float

    rr: float

    status: EntrySignalStatus = (
        EntrySignalStatus.READY
    )

    provider: str = "unknown"

    timeframe: str | None = None

    poi_provider: str | None = None
    poi_type: str | None = None

    created_time: int = 0

    confidence: float = 0.0

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    @property
    def risk_distance(self) -> float:
        return abs(
            float(self.entry_price)
            - float(self.stop_loss)
        )

    @property
    def reward_distance(self) -> float:
        return abs(
            float(self.take_profit)
            - float(self.entry_price)
        )

    def validate(self) -> tuple[
        bool,
        str | None,
    ]:
        if self.entry_price <= 0:
            return (
                False,
                "entry_price_invalid",
            )

        if self.stop_loss <= 0:
            return (
                False,
                "stop_loss_invalid",
            )

        if self.take_profit <= 0:
            return (
                False,
                "take_profit_invalid",
            )

        if self.risk_distance <= 0:
            return (
                False,
                "risk_distance_zero",
            )

        if self.direction == EntryDirection.BUY:
            if not (
                self.stop_loss
                < self.entry_price
                < self.take_profit
            ):
                return (
                    False,
                    "buy_price_structure_invalid",
                )

        if self.direction == EntryDirection.SELL:
            if not (
                self.take_profit
                < self.entry_price
                < self.stop_loss
            ):
                return (
                    False,
                    "sell_price_structure_invalid",
                )

        calculated_rr = (
            self.reward_distance
            / self.risk_distance
        )

        if calculated_rr <= 0:
            return (
                False,
                "rr_invalid",
            )

        return (
            True,
            None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "symbol": self.symbol,
            "direction": self.direction.value,
            "order_type": self.order_type.value,
            "entry_price": float(
                self.entry_price
            ),
            "stop_loss": float(
                self.stop_loss
            ),
            "take_profit": float(
                self.take_profit
            ),
            "rr": float(
                self.rr
            ),
            "status": self.status.value,
            "provider": self.provider,
            "timeframe": self.timeframe,
            "poi_provider": self.poi_provider,
            "poi_type": self.poi_type,
            "created_time": int(
                self.created_time
            ),
            "confidence": float(
                self.confidence
            ),
            "risk_distance": float(
                self.risk_distance
            ),
            "reward_distance": float(
                self.reward_distance
            ),
            "metadata": dict(
                self.metadata
            ),
        }