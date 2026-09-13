from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class OrderStateStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


class PositionStateStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    UNKNOWN = "UNKNOWN"


@dataclass(slots=True)
class OrderState:
    execution_id: str
    broker_order_id: str

    symbol: str
    direction: str
    order_type: str

    volume: float
    price: float

    stop_loss: float | None = None
    take_profit: float | None = None

    filled_volume: float = 0.0
    filled_price: float | None = None

    status: OrderStateStatus = (
        OrderStateStatus.UNKNOWN
    )

    created_time: int = 0
    updated_time: int = 0

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    @property
    def remaining_volume(self) -> float:
        return max(
            0.0,
            float(self.volume)
            - float(self.filled_volume),
        )

    @property
    def active(self) -> bool:
        return self.status in {
            OrderStateStatus.PENDING,
            OrderStateStatus.PARTIALLY_FILLED,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "broker_order_id": (
                self.broker_order_id
            ),
            "symbol": self.symbol,
            "direction": self.direction,
            "order_type": self.order_type,
            "volume": float(self.volume),
            "price": float(self.price),
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "filled_volume": float(
                self.filled_volume
            ),
            "filled_price": (
                self.filled_price
            ),
            "remaining_volume": (
                self.remaining_volume
            ),
            "status": self.status.value,
            "active": self.active,
            "created_time": int(
                self.created_time
            ),
            "updated_time": int(
                self.updated_time
            ),
            "metadata": dict(
                self.metadata
            ),
        }


@dataclass(slots=True)
class PositionState:
    broker_position_id: str

    symbol: str
    direction: str

    volume: float
    entry_price: float

    stop_loss: float | None = None
    take_profit: float | None = None

    current_price: float | None = None
    profit: float = 0.0

    status: PositionStateStatus = (
        PositionStateStatus.OPEN
    )

    opened_time: int = 0
    updated_time: int = 0
    closed_time: int | None = None

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    @property
    def active(self) -> bool:
        return (
            self.status
            == PositionStateStatus.OPEN
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "broker_position_id": (
                self.broker_position_id
            ),
            "symbol": self.symbol,
            "direction": self.direction,
            "volume": float(self.volume),
            "entry_price": float(
                self.entry_price
            ),
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "current_price": (
                self.current_price
            ),
            "profit": float(
                self.profit
            ),
            "status": self.status.value,
            "active": self.active,
            "opened_time": int(
                self.opened_time
            ),
            "updated_time": int(
                self.updated_time
            ),
            "closed_time": (
                int(self.closed_time)
                if self.closed_time
                is not None
                else None
            ),
            "metadata": dict(
                self.metadata
            ),
        }


@dataclass(slots=True)
class ExecutionSnapshot:
    orders: list[OrderState] = field(
        default_factory=list
    )
    positions: list[PositionState] = field(
        default_factory=list
    )

    synchronized_time: int = 0

    diagnostics: dict[str, Any] = field(
        default_factory=dict
    )

    @property
    def active_orders(
        self,
    ) -> list[OrderState]:
        return [
            order
            for order in self.orders
            if order.active
        ]

    @property
    def open_positions(
        self,
    ) -> list[PositionState]:
        return [
            position
            for position in self.positions
            if position.active
        ]

    def order_by_broker_id(
        self,
        broker_order_id: str,
    ) -> OrderState | None:
        target = str(
            broker_order_id
        )

        for order in self.orders:
            if (
                str(order.broker_order_id)
                == target
            ):
                return order

        return None

    def position_by_broker_id(
        self,
        broker_position_id: str,
    ) -> PositionState | None:
        target = str(
            broker_position_id
        )

        for position in self.positions:
            if (
                str(
                    position.broker_position_id
                )
                == target
            ):
                return position

        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "orders": [
                order.to_dict()
                for order in self.orders
            ],
            "positions": [
                position.to_dict()
                for position in self.positions
            ],
            "active_orders": len(
                self.active_orders
            ),
            "open_positions": len(
                self.open_positions
            ),
            "synchronized_time": int(
                self.synchronized_time
            ),
            "diagnostics": dict(
                self.diagnostics
            ),
        }