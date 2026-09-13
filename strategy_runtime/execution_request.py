from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from core.context import StrategyContext
from core.execution_order import (
    ExecutionDirection,
    ExecutionOrder,
    ExecutionOrderType,
)
from .trade_plan import TradePlan


@dataclass(slots=True)
class ExecutionRequestBuildResult:
    success: bool
    order: ExecutionOrder | None = None
    reason: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": bool(self.success),
            "order": (
                self.order.to_dict()
                if self.order is not None
                else None
            ),
            "reason": self.reason,
            "diagnostics": dict(self.diagnostics),
        }


class TradePlanExecutionRequestBuilder:
    """
    Day 54 TradePlan -> ExecutionOrder bridge.

    Guarantees:
    - deterministic execution_id for the same strategy/setup/time;
    - strict direction/order-type mapping;
    - ExecutionOrder.validate() must pass;
    - invalid plans fail closed;
    - no broker/MT5 call is performed here.
    """

    def __init__(
        self,
        *,
        provider: str = "generic_strategy_runtime",
        deviation: int = 20,
        magic: int = 0,
    ) -> None:
        self.provider = str(provider).strip()
        self.deviation = int(deviation)
        self.magic = int(magic)

        if not self.provider:
            raise ValueError("provider_is_required")

    def build(
        self,
        plan: TradePlan,
        context: StrategyContext,
        *,
        expiration_time: int | None = None,
    ) -> ExecutionRequestBuildResult:
        if plan.strategy_id != context.strategy.metadata.strategy_id:
            return self._fail(
                "trade_plan_strategy_context_mismatch"
            )

        if (
            str(plan.symbol).strip().upper()
            != str(context.symbol).strip().upper()
        ):
            return self._fail(
                "trade_plan_symbol_context_mismatch"
            )

        direction = self._direction(
            plan.side
        )
        if direction is None:
            return self._fail(
                "execution_direction_unresolved"
            )

        order_type = self._order_type(
            plan.order_type,
            direction=direction,
        )
        if order_type is None:
            return self._fail(
                "execution_order_type_unresolved"
            )

        numeric_error = self._validate_numeric_plan(
            plan
        )
        if numeric_error is not None:
            return self._fail(
                numeric_error
            )

        execution_id = self._execution_id(
            plan=plan,
            current_time=int(
                context.current_time
            ),
            direction=direction,
            order_type=order_type,
        )

        order = ExecutionOrder(
            execution_id=execution_id,
            symbol=str(
                plan.symbol
            ).strip().upper(),
            direction=direction,
            order_type=order_type,
            volume=float(plan.lot),
            entry_price=float(
                plan.entry_price
            ),
            stop_loss=float(
                plan.stop_loss
            ),
            take_profit=float(
                plan.take_profit
            ),
            provider=self.provider,
            created_time=int(
                context.current_time
            ),
            deviation=self.deviation,
            magic=self.magic,
            comment=(
                f"{plan.strategy_id}:"
                f"{plan.compilation_id}:"
                f"entry_{plan.entry_index}"
            )[:31],
            expiration_time=(
                int(expiration_time)
                if expiration_time
                is not None
                else None
            ),
            metadata={
                "strategy_id": (
                    plan.strategy_id
                ),
                "compilation_id": (
                    plan.compilation_id
                ),
                "entry_index": int(
                    plan.entry_index
                ),
                "risk_percent": float(
                    plan.risk_percent
                ),
                "risk_money": float(
                    plan.risk_money
                ),
                "trade_plan": plan.to_dict(),
                "source": "DAY54_TRADE_PLAN_BRIDGE",
            },
        )

        valid, reason = order.validate()

        if not valid:
            return self._fail(
                (
                    "execution_order_invalid:"
                    f"{reason}"
                )
            )

        context.trade[
            "execution_request"
        ] = order.to_dict()

        return ExecutionRequestBuildResult(
            success=True,
            order=order,
            reason="execution_request_ready",
            diagnostics={
                "execution_id": (
                    execution_id
                ),
                "validated": True,
                "broker_call_performed": False,
            },
        )

    @staticmethod
    def _direction(
        side: str,
    ) -> ExecutionDirection | None:
        value = str(
            side
        ).strip().upper()

        if value in {
            "LONG",
            "BUY",
        }:
            return ExecutionDirection.BUY

        if value in {
            "SHORT",
            "SELL",
        }:
            return ExecutionDirection.SELL

        return None

    @staticmethod
    def _order_type(
        raw: str,
        *,
        direction: ExecutionDirection,
    ) -> ExecutionOrderType | None:
        value = str(
            raw
        ).strip().upper()

        if value == "MARKET":
            return ExecutionOrderType.MARKET

        if value in {
            "LIMIT",
            "BUY_LIMIT",
            "SELL_LIMIT",
        }:
            return (
                ExecutionOrderType.BUY_LIMIT
                if direction
                == ExecutionDirection.BUY
                else ExecutionOrderType.SELL_LIMIT
            )

        if value in {
            "STOP",
            "BUY_STOP",
            "SELL_STOP",
        }:
            return (
                ExecutionOrderType.BUY_STOP
                if direction
                == ExecutionDirection.BUY
                else ExecutionOrderType.SELL_STOP
            )

        return None

    @staticmethod
    def _validate_numeric_plan(
        plan: TradePlan,
    ) -> str | None:
        values = {
            "entry_price": plan.entry_price,
            "stop_loss": plan.stop_loss,
            "take_profit": plan.take_profit,
            "lot": plan.lot,
            "risk_percent": plan.risk_percent,
            "risk_money": plan.risk_money,
        }

        for name, raw in values.items():
            try:
                value = float(raw)
            except (
                TypeError,
                ValueError,
                OverflowError,
            ):
                return (
                    "trade_plan_numeric_invalid:"
                    f"{name}"
                )

            if value <= 0:
                return (
                    "trade_plan_numeric_non_positive:"
                    f"{name}"
                )

        return None

    @staticmethod
    def _execution_id(
        *,
        plan: TradePlan,
        current_time: int,
        direction: ExecutionDirection,
        order_type: ExecutionOrderType,
    ) -> str:
        payload = {
            "strategy_id": plan.strategy_id,
            "compilation_id": (
                plan.compilation_id
            ),
            "symbol": (
                plan.symbol
                .strip()
                .upper()
            ),
            "direction": direction.value,
            "order_type": order_type.value,
            "entry_price": float(
                plan.entry_price
            ),
            "stop_loss": float(
                plan.stop_loss
            ),
            "take_profit": float(
                plan.take_profit
            ),
            "volume": float(
                plan.lot
            ),
            "entry_index": int(
                plan.entry_index
            ),
            "created_time": int(
                current_time
            ),
        }

        digest = hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:24]

        return (
            f"{plan.strategy_id}:"
            f"{plan.symbol.strip().upper()}:"
            f"{digest}"
        )

    @staticmethod
    def _fail(
        reason: str,
    ) -> ExecutionRequestBuildResult:
        return ExecutionRequestBuildResult(
            success=False,
            order=None,
            reason=reason,
            diagnostics={
                "broker_call_performed": False,
            },
        )