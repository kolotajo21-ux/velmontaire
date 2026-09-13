from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.context import StrategyContext


class PositionManagementAction(str, Enum):
    NONE = "NONE"
    MOVE_TO_BE = "MOVE_TO_BE"
    MOVE_SL = "MOVE_SL"
    UPDATE_TP = "UPDATE_TP"
    CLOSE = "CLOSE"


@dataclass(slots=True)
class PositionManagementRequest:
    execution_id: str
    action: PositionManagementAction
    symbol: str
    broker_position_id: str | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "action": self.action.value,
            "symbol": self.symbol,
            "broker_position_id": self.broker_position_id,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "reason": self.reason,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class PositionManagementResult:
    success: bool
    request: PositionManagementRequest | None = None
    reason: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)


class GenericPositionManager:
    """
    Day 58 generic post-fill position management planner.

    Produces management requests only. It never calls broker/MT5.
    Supported rules:
      - BREAK_EVEN / MOVE_TO_BE at trigger_r
      - MOVE_SL to explicit price
      - UPDATE_TP to explicit price
      - CLOSE at trigger_r
    """

    def evaluate(
        self,
        context: StrategyContext,
        *,
        execution_id: str,
        current_price: float,
        management_rules: list[dict[str, Any]],
        broker_position_id: str | None = None,
    ) -> PositionManagementResult:
        trade = context.trade
        side = str(trade.get("side", "")).upper()

        try:
            entry = float(trade["entry_price"])
            initial_sl = float(trade["stop_loss"])
            current_tp = float(trade["take_profit"])
            price = float(current_price)
        except (KeyError, TypeError, ValueError):
            return self._fail("position_trade_data_incomplete")

        if side not in {"LONG", "BUY", "SHORT", "SELL"}:
            return self._fail("position_side_invalid")

        bullish = side in {"LONG", "BUY"}
        risk_distance = abs(entry - initial_sl)
        if risk_distance <= 0:
            return self._fail("position_initial_risk_invalid")

        profit_distance = (
            price - entry
            if bullish
            else entry - price
        )
        current_r = profit_distance / risk_distance

        for rule in management_rules:
            if not isinstance(rule, dict):
                continue

            rule_type = str(
                rule.get("type", rule.get("action", ""))
            ).strip().upper()

            if rule_type in {
                "BREAK_EVEN",
                "BREAKEVEN",
                "MOVE_TO_BE",
            }:
                trigger = self._number(
                    rule.get(
                        "trigger_r",
                        rule.get("value"),
                    )
                )
                if trigger is None or trigger <= 0:
                    return self._fail("break_even_trigger_invalid")

                if current_r + 1e-9 >= trigger:
                    request = PositionManagementRequest(
                        execution_id=execution_id,
                        action=PositionManagementAction.MOVE_TO_BE,
                        symbol=context.symbol,
                        broker_position_id=broker_position_id,
                        stop_loss=entry,
                        take_profit=current_tp,
                        reason=f"break_even_triggered_at_{trigger}R",
                        metadata={
                            "current_r": current_r,
                            "trigger_r": trigger,
                        },
                    )
                    return self._success(context, request)

            elif rule_type == "MOVE_SL":
                target = self._number(
                    rule.get(
                        "price",
                        rule.get("value"),
                    )
                )
                if target is None or target <= 0:
                    return self._fail("move_sl_price_invalid")

                if bullish and target >= current_tp:
                    return self._fail("move_sl_long_structure_invalid")
                if not bullish and target <= current_tp:
                    return self._fail("move_sl_short_structure_invalid")

                request = PositionManagementRequest(
                    execution_id=execution_id,
                    action=PositionManagementAction.MOVE_SL,
                    symbol=context.symbol,
                    broker_position_id=broker_position_id,
                    stop_loss=target,
                    take_profit=current_tp,
                    reason="explicit_stop_loss_update",
                    metadata={"current_r": current_r},
                )
                return self._success(context, request)

            elif rule_type == "UPDATE_TP":
                target = self._number(
                    rule.get(
                        "price",
                        rule.get("value"),
                    )
                )
                if target is None or target <= 0:
                    return self._fail("update_tp_price_invalid")

                if bullish and target <= entry:
                    return self._fail("update_tp_long_structure_invalid")
                if not bullish and target >= entry:
                    return self._fail("update_tp_short_structure_invalid")

                request = PositionManagementRequest(
                    execution_id=execution_id,
                    action=PositionManagementAction.UPDATE_TP,
                    symbol=context.symbol,
                    broker_position_id=broker_position_id,
                    stop_loss=initial_sl,
                    take_profit=target,
                    reason="explicit_take_profit_update",
                    metadata={"current_r": current_r},
                )
                return self._success(context, request)

            elif rule_type in {"CLOSE", "CLOSE_POSITION"}:
                trigger = self._number(
                    rule.get(
                        "trigger_r",
                        rule.get("value"),
                    )
                )
                if trigger is None:
                    return self._fail("close_trigger_invalid")

                if current_r + 1e-9 >= trigger:
                    request = PositionManagementRequest(
                        execution_id=execution_id,
                        action=PositionManagementAction.CLOSE,
                        symbol=context.symbol,
                        broker_position_id=broker_position_id,
                        reason=f"close_triggered_at_{trigger}R",
                        metadata={
                            "current_r": current_r,
                            "trigger_r": trigger,
                        },
                    )
                    return self._success(context, request)

        context.trade["position_management"] = {
            "action": PositionManagementAction.NONE.value,
            "current_r": current_r,
        }
        return PositionManagementResult(
            success=True,
            request=None,
            reason="no_management_action_ready",
            diagnostics={
                "current_r": current_r,
                "broker_call_performed": False,
            },
        )

    @staticmethod
    def _number(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _fail(reason: str) -> PositionManagementResult:
        return PositionManagementResult(
            success=False,
            request=None,
            reason=reason,
            diagnostics={
                "broker_call_performed": False,
            },
        )

    @staticmethod
    def _success(
        context: StrategyContext,
        request: PositionManagementRequest,
    ) -> PositionManagementResult:
        context.trade["position_management"] = request.to_dict()
        return PositionManagementResult(
            success=True,
            request=request,
            reason="position_management_request_ready",
            diagnostics={
                "broker_call_performed": False,
            },
        )