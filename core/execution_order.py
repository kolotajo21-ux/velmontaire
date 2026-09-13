from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ExecutionDirection(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class ExecutionOrderType(str, Enum):
    MARKET = "MARKET"
    BUY_LIMIT = "BUY_LIMIT"
    SELL_LIMIT = "SELL_LIMIT"
    BUY_STOP = "BUY_STOP"
    SELL_STOP = "SELL_STOP"


class ExecutionStatus(str, Enum):
    READY = "READY"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


@dataclass(slots=True)
class ExecutionOrder:
    execution_id: str

    symbol: str
    direction: ExecutionDirection
    order_type: ExecutionOrderType

    volume: float

    entry_price: float
    stop_loss: float
    take_profit: float

    status: ExecutionStatus = (
        ExecutionStatus.READY
    )

    provider: str = "unknown"

    created_time: int = 0

    deviation: int = 20
    magic: int = 0
    comment: str = ""

    expiration_time: int | None = None

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def validate(self) -> tuple[
        bool,
        str | None,
    ]:
        if not self.symbol:
            return False, "symbol_missing"

        if self.volume <= 0:
            return False, "volume_invalid"

        if self.entry_price <= 0:
            return False, "entry_price_invalid"

        if self.stop_loss <= 0:
            return False, "stop_loss_invalid"

        if self.take_profit <= 0:
            return False, "take_profit_invalid"

        if self.direction == ExecutionDirection.BUY:
            if not (
                self.stop_loss
                < self.entry_price
                < self.take_profit
            ):
                return (
                    False,
                    "buy_price_structure_invalid",
                )

            if self.order_type in {
                ExecutionOrderType.SELL_LIMIT,
                ExecutionOrderType.SELL_STOP,
            }:
                return (
                    False,
                    "buy_direction_order_type_mismatch",
                )

        elif self.direction == ExecutionDirection.SELL:
            if not (
                self.take_profit
                < self.entry_price
                < self.stop_loss
            ):
                return (
                    False,
                    "sell_price_structure_invalid",
                )

            if self.order_type in {
                ExecutionOrderType.BUY_LIMIT,
                ExecutionOrderType.BUY_STOP,
            }:
                return (
                    False,
                    "sell_direction_order_type_mismatch",
                )

        else:
            return (
                False,
                "execution_direction_invalid",
            )

        return True, None

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "symbol": self.symbol,
            "direction": self.direction.value,
            "order_type": self.order_type.value,
            "volume": float(self.volume),
            "entry_price": float(
                self.entry_price
            ),
            "stop_loss": float(
                self.stop_loss
            ),
            "take_profit": float(
                self.take_profit
            ),
            "status": self.status.value,
            "provider": self.provider,
            "created_time": int(
                self.created_time
            ),
            "deviation": int(
                self.deviation
            ),
            "magic": int(
                self.magic
            ),
            "comment": self.comment,
            "expiration_time": (
                int(self.expiration_time)
                if self.expiration_time
                is not None
                else None
            ),
            "metadata": dict(
                self.metadata
            ),
        }