from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RiskPlanStatus(str, Enum):
    READY = "READY"
    REJECTED = "REJECTED"
    INVALID = "INVALID"


@dataclass(slots=True)
class RiskPlan:
    plan_id: str

    symbol: str

    balance: float
    equity: float

    risk_percent: float
    risk_amount: float

    entry_price: float
    stop_loss: float
    stop_distance: float

    position_size: float

    tick_size: float
    tick_value: float

    min_lot: float
    max_lot: float
    lot_step: float

    status: RiskPlanStatus = (
        RiskPlanStatus.READY
    )

    provider: str = "unknown"
    created_time: int = 0

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def validate(self) -> tuple[
        bool,
        str | None,
    ]:
        if self.balance <= 0:
            return (
                False,
                "balance_invalid",
            )

        if self.equity <= 0:
            return (
                False,
                "equity_invalid",
            )

        if self.risk_percent <= 0:
            return (
                False,
                "risk_percent_invalid",
            )

        if self.risk_amount <= 0:
            return (
                False,
                "risk_amount_invalid",
            )

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

        if self.stop_distance <= 0:
            return (
                False,
                "stop_distance_invalid",
            )

        if self.position_size <= 0:
            return (
                False,
                "position_size_invalid",
            )

        if self.tick_size <= 0:
            return (
                False,
                "tick_size_invalid",
            )

        if self.tick_value <= 0:
            return (
                False,
                "tick_value_invalid",
            )

        if self.min_lot <= 0:
            return (
                False,
                "min_lot_invalid",
            )

        if self.max_lot < self.min_lot:
            return (
                False,
                "lot_limits_invalid",
            )

        if self.lot_step <= 0:
            return (
                False,
                "lot_step_invalid",
            )

        if (
            self.position_size
            < self.min_lot
        ):
            return (
                False,
                "position_size_below_min_lot",
            )

        if (
            self.position_size
            > self.max_lot
        ):
            return (
                False,
                "position_size_above_max_lot",
            )

        return (
            True,
            None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "symbol": self.symbol,
            "balance": float(
                self.balance
            ),
            "equity": float(
                self.equity
            ),
            "risk_percent": float(
                self.risk_percent
            ),
            "risk_amount": float(
                self.risk_amount
            ),
            "entry_price": float(
                self.entry_price
            ),
            "stop_loss": float(
                self.stop_loss
            ),
            "stop_distance": float(
                self.stop_distance
            ),
            "position_size": float(
                self.position_size
            ),
            "tick_size": float(
                self.tick_size
            ),
            "tick_value": float(
                self.tick_value
            ),
            "min_lot": float(
                self.min_lot
            ),
            "max_lot": float(
                self.max_lot
            ),
            "lot_step": float(
                self.lot_step
            ),
            "status": (
                self.status.value
            ),
            "provider": self.provider,
            "created_time": int(
                self.created_time
            ),
            "metadata": dict(
                self.metadata
            ),
        }