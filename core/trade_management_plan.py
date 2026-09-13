from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TradeManagementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    INVALID = "INVALID"


class StopManagementMode(str, Enum):
    NONE = "NONE"
    BREAK_EVEN = "BREAK_EVEN"
    TRAILING = "TRAILING"


@dataclass(slots=True)
class TradeManagementPlan:
    plan_id: str
    symbol: str

    entry_price: float
    initial_stop_loss: float
    take_profit: float

    break_even_enabled: bool = True
    break_even_trigger_r: float = 1.0
    break_even_offset: float = 0.0

    partial_close_enabled: bool = False
    partial_close_trigger_r: float = 1.0
    partial_close_percent: float = 0.0

    trailing_enabled: bool = False
    trailing_trigger_r: float = 2.0
    trailing_distance_r: float = 1.0

    status: TradeManagementStatus = (
        TradeManagementStatus.ACTIVE
    )

    stop_mode: StopManagementMode = (
        StopManagementMode.NONE
    )

    provider: str = "unknown"
    created_time: int = 0

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    @property
    def initial_risk_distance(self) -> float:
        return abs(
            float(self.entry_price)
            - float(self.initial_stop_loss)
        )

    def validate(self) -> tuple[
        bool,
        str | None,
    ]:
        if self.entry_price <= 0:
            return False, "entry_price_invalid"

        if self.initial_stop_loss <= 0:
            return False, "stop_loss_invalid"

        if self.take_profit <= 0:
            return False, "take_profit_invalid"

        if self.initial_risk_distance <= 0:
            return False, "risk_distance_invalid"

        if (
            self.break_even_enabled
            and self.break_even_trigger_r <= 0
        ):
            return False, "break_even_trigger_invalid"

        if self.partial_close_enabled:
            if self.partial_close_trigger_r <= 0:
                return False, "partial_trigger_invalid"

            if not (
                0 < self.partial_close_percent < 100
            ):
                return False, "partial_percent_invalid"

        if self.trailing_enabled:
            if self.trailing_trigger_r <= 0:
                return False, "trailing_trigger_invalid"

            if self.trailing_distance_r <= 0:
                return False, "trailing_distance_invalid"

        return True, None

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "symbol": self.symbol,
            "entry_price": float(
                self.entry_price
            ),
            "initial_stop_loss": float(
                self.initial_stop_loss
            ),
            "take_profit": float(
                self.take_profit
            ),
            "initial_risk_distance": float(
                self.initial_risk_distance
            ),
            "break_even_enabled": bool(
                self.break_even_enabled
            ),
            "break_even_trigger_r": float(
                self.break_even_trigger_r
            ),
            "break_even_offset": float(
                self.break_even_offset
            ),
            "partial_close_enabled": bool(
                self.partial_close_enabled
            ),
            "partial_close_trigger_r": float(
                self.partial_close_trigger_r
            ),
            "partial_close_percent": float(
                self.partial_close_percent
            ),
            "trailing_enabled": bool(
                self.trailing_enabled
            ),
            "trailing_trigger_r": float(
                self.trailing_trigger_r
            ),
            "trailing_distance_r": float(
                self.trailing_distance_r
            ),
            "status": self.status.value,
            "stop_mode": self.stop_mode.value,
            "provider": self.provider,
            "created_time": int(
                self.created_time
            ),
            "metadata": dict(
                self.metadata
            ),
        }