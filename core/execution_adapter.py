from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .execution_order import (
    ExecutionOrder,
    ExecutionStatus,
)


class AdapterExecutionStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


@dataclass(slots=True)
class AdapterExecutionResult:
    execution_id: str
    adapter: str

    success: bool
    status: AdapterExecutionStatus

    broker_order_id: str | None = None
    broker_position_id: str | None = None

    requested_volume: float = 0.0
    filled_volume: float = 0.0

    requested_price: float = 0.0
    filled_price: float | None = None

    message: str | None = None
    error_code: str | int | None = None

    raw: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "adapter": self.adapter,
            "success": bool(self.success),
            "status": self.status.value,
            "broker_order_id": self.broker_order_id,
            "broker_position_id": self.broker_position_id,
            "requested_volume": float(self.requested_volume),
            "filled_volume": float(self.filled_volume),
            "requested_price": float(self.requested_price),
            "filled_price": (
                float(self.filled_price)
                if self.filled_price is not None
                else None
            ),
            "message": self.message,
            "error_code": self.error_code,
            "raw": dict(self.raw),
            "diagnostics": dict(self.diagnostics),
        }


class ExecutionAdapter(ABC):
    """
    Universal execution interface.

    Day 60 adds close_position() as a backwards-compatible optional capability.
    Existing adapters are NOT forced to implement it immediately.
    """

    name: str = "base"

    @abstractmethod
    def submit(
        self,
        order: ExecutionOrder,
    ) -> AdapterExecutionResult:
        raise NotImplementedError

    @abstractmethod
    def cancel(
        self,
        *,
        execution_id: str,
        broker_order_id: str | None = None,
    ) -> AdapterExecutionResult:
        raise NotImplementedError

    @abstractmethod
    def modify(
        self,
        *,
        execution_id: str,
        broker_order_id: str | None = None,
        broker_position_id: str | None = None,
        stop_loss: float | None = None,
        take_profit: float | None = None,
    ) -> AdapterExecutionResult:
        raise NotImplementedError

    def close_position(
        self,
        *,
        execution_id: str,
        broker_position_id: str,
        symbol: str | None = None,
        volume: float | None = None,
        deviation: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AdapterExecutionResult:
        """
        Optional live-position close capability.

        Existing adapters remain instantiable. An adapter that has not yet
        implemented live position closing fails closed with NotImplementedError.
        """
        raise NotImplementedError(
            "close_position_not_implemented"
        )

    def validate_order(
        self,
        order: ExecutionOrder,
    ) -> tuple[bool, str | None]:
        if not isinstance(order, ExecutionOrder):
            return False, "execution_order_type_invalid"

        valid, reason = order.validate()

        if not valid:
            return False, reason or "execution_order_invalid"

        if order.status != ExecutionStatus.READY:
            return False, "execution_order_not_ready"

        return True, None

    def accepted(
        self,
        *,
        order: ExecutionOrder,
        status: AdapterExecutionStatus = AdapterExecutionStatus.SUBMITTED,
        broker_order_id: str | None = None,
        broker_position_id: str | None = None,
        filled_volume: float = 0.0,
        filled_price: float | None = None,
        message: str | None = None,
        raw: dict[str, Any] | None = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> AdapterExecutionResult:
        return AdapterExecutionResult(
            execution_id=order.execution_id,
            adapter=self.name,
            success=True,
            status=status,
            broker_order_id=broker_order_id,
            broker_position_id=broker_position_id,
            requested_volume=float(order.volume),
            filled_volume=float(filled_volume),
            requested_price=float(order.entry_price),
            filled_price=(
                float(filled_price)
                if filled_price is not None
                else None
            ),
            message=message,
            raw=dict(raw or {}),
            diagnostics=dict(diagnostics or {}),
        )

    def rejected(
        self,
        *,
        order: ExecutionOrder,
        message: str,
        error_code: str | int | None = None,
        raw: dict[str, Any] | None = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> AdapterExecutionResult:
        return AdapterExecutionResult(
            execution_id=order.execution_id,
            adapter=self.name,
            success=False,
            status=AdapterExecutionStatus.REJECTED,
            requested_volume=float(order.volume),
            filled_volume=0.0,
            requested_price=float(order.entry_price),
            filled_price=None,
            message=str(message),
            error_code=error_code,
            raw=dict(raw or {}),
            diagnostics=dict(diagnostics or {}),
        )