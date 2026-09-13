from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.execution_adapter import (
    AdapterExecutionResult,
    AdapterExecutionStatus,
    ExecutionAdapter,
)
from core.execution_order import (
    ExecutionOrder,
    ExecutionOrderType,
)


@dataclass(slots=True)
class PaperOrderState:
    execution_id: str
    broker_order_id: str

    order: ExecutionOrder

    status: AdapterExecutionStatus

    filled_volume: float = 0.0
    filled_price: float | None = None

    stop_loss: float | None = None
    take_profit: float | None = None

    metadata: dict[str, Any] = field(
        default_factory=dict
    )


class PaperExecutionAdapter(
    ExecutionAdapter
):
    """
    In-memory execution adapter.

    Нужен для:
    - unit/integration тестов;
    - paper trading;
    - проверки execution-flow без MT5.
    """

    name = "paper"

    def __init__(
        self,
        *,
        auto_fill_market: bool = True,
        auto_fill_pending: bool = False,
    ) -> None:
        self.auto_fill_market = bool(
            auto_fill_market
        )
        self.auto_fill_pending = bool(
            auto_fill_pending
        )

        self._orders: dict[
            str,
            PaperOrderState,
        ] = {}

        self._counter = 0

    def submit(
        self,
        order: ExecutionOrder,
    ) -> AdapterExecutionResult:
        valid, reason = self.validate_order(
            order
        )

        if not valid:
            return self.rejected(
                order=order,
                message=(
                    reason
                    or "order_validation_failed"
                ),
            )

        self._counter += 1

        broker_order_id = (
            f"PAPER-{self._counter:06d}"
        )

        should_fill = False

        if (
            order.order_type
            == ExecutionOrderType.MARKET
            and self.auto_fill_market
        ):
            should_fill = True

        if (
            order.order_type
            != ExecutionOrderType.MARKET
            and self.auto_fill_pending
        ):
            should_fill = True

        if should_fill:
            status = (
                AdapterExecutionStatus.FILLED
            )
            filled_volume = float(
                order.volume
            )
            filled_price = float(
                order.entry_price
            )
        else:
            status = (
                AdapterExecutionStatus.SUBMITTED
            )
            filled_volume = 0.0
            filled_price = None

        state = PaperOrderState(
            execution_id=(
                order.execution_id
            ),
            broker_order_id=(
                broker_order_id
            ),
            order=order,
            status=status,
            filled_volume=(
                filled_volume
            ),
            filled_price=(
                filled_price
            ),
            stop_loss=float(
                order.stop_loss
            ),
            take_profit=float(
                order.take_profit
            ),
        )

        self._orders[
            broker_order_id
        ] = state

        return self.accepted(
            order=order,
            status=status,
            broker_order_id=(
                broker_order_id
            ),
            broker_position_id=(
                broker_order_id
                if status
                == AdapterExecutionStatus.FILLED
                else None
            ),
            filled_volume=(
                filled_volume
            ),
            filled_price=(
                filled_price
            ),
            message=(
                "paper_order_filled"
                if should_fill
                else "paper_order_submitted"
            ),
            diagnostics={
                "auto_fill_market": (
                    self.auto_fill_market
                ),
                "auto_fill_pending": (
                    self.auto_fill_pending
                ),
            },
        )

    def cancel(
        self,
        *,
        execution_id: str,
        broker_order_id: str | None = None,
    ) -> AdapterExecutionResult:
        state = self._find_state(
            execution_id=(
                execution_id
            ),
            broker_order_id=(
                broker_order_id
            ),
        )

        if state is None:
            return AdapterExecutionResult(
                execution_id=(
                    execution_id
                ),
                adapter=self.name,
                success=False,
                status=(
                    AdapterExecutionStatus
                    .REJECTED
                ),
                message="paper_order_not_found",
            )

        if (
            state.status
            == AdapterExecutionStatus.FILLED
        ):
            return AdapterExecutionResult(
                execution_id=(
                    execution_id
                ),
                adapter=self.name,
                success=False,
                status=(
                    AdapterExecutionStatus
                    .REJECTED
                ),
                broker_order_id=(
                    state.broker_order_id
                ),
                requested_volume=float(
                    state.order.volume
                ),
                filled_volume=float(
                    state.filled_volume
                ),
                requested_price=float(
                    state.order.entry_price
                ),
                filled_price=(
                    state.filled_price
                ),
                message=(
                    "filled_order_cannot_be_cancelled"
                ),
            )

        state.status = (
            AdapterExecutionStatus.CANCELLED
        )

        return AdapterExecutionResult(
            execution_id=(
                execution_id
            ),
            adapter=self.name,
            success=True,
            status=(
                AdapterExecutionStatus.CANCELLED
            ),
            broker_order_id=(
                state.broker_order_id
            ),
            requested_volume=float(
                state.order.volume
            ),
            filled_volume=float(
                state.filled_volume
            ),
            requested_price=float(
                state.order.entry_price
            ),
            filled_price=(
                state.filled_price
            ),
            message="paper_order_cancelled",
        )

    def modify(
        self,
        *,
        execution_id: str,
        broker_order_id: str | None = None,
        broker_position_id: str | None = None,
        stop_loss: float | None = None,
        take_profit: float | None = None,
    ) -> AdapterExecutionResult:
        state = self._find_state(
            execution_id=(
                execution_id
            ),
            broker_order_id=(
                broker_order_id
            ),
        )

        if state is None:
            return AdapterExecutionResult(
                execution_id=(
                    execution_id
                ),
                adapter=self.name,
                success=False,
                status=(
                    AdapterExecutionStatus.REJECTED
                ),
                message="paper_order_not_found",
            )

        if stop_loss is not None:
            state.stop_loss = float(
                stop_loss
            )

        if take_profit is not None:
            state.take_profit = float(
                take_profit
            )

        return AdapterExecutionResult(
            execution_id=(
                execution_id
            ),
            adapter=self.name,
            success=True,
            status=(
                state.status
            ),
            broker_order_id=(
                state.broker_order_id
            ),
            broker_position_id=(
                broker_position_id
            ),
            requested_volume=float(
                state.order.volume
            ),
            filled_volume=float(
                state.filled_volume
            ),
            requested_price=float(
                state.order.entry_price
            ),
            filled_price=(
                state.filled_price
            ),
            message="paper_order_modified",
            diagnostics={
                "stop_loss": (
                    state.stop_loss
                ),
                "take_profit": (
                    state.take_profit
                ),
            },
        )

    def get_order(
        self,
        broker_order_id: str,
    ) -> PaperOrderState | None:
        return self._orders.get(
            broker_order_id
        )

    def _find_state(
        self,
        *,
        execution_id: str,
        broker_order_id: str | None,
    ) -> PaperOrderState | None:
        if broker_order_id is not None:
            state = self._orders.get(
                broker_order_id
            )

            if state is not None:
                return state

        for state in self._orders.values():
            if (
                state.execution_id
                == execution_id
            ):
                return state

        return None