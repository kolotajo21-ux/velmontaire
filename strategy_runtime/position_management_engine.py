from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class PositionManagementError(ValueError):
    """Fail-closed position-management error."""


class ManagementAction(str, Enum):
    BREAK_EVEN = "BREAK_EVEN"
    PARTIAL_CLOSE = "PARTIAL_CLOSE"
    TRAILING_STOP = "TRAILING_STOP"
    MOVE_STOP = "MOVE_STOP"
    CLOSE_POSITION = "CLOSE_POSITION"
    SCALE_IN = "SCALE_IN"
    SCALE_OUT = "SCALE_OUT"


class PositionDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass(frozen=True, slots=True)
class PositionState:
    direction: PositionDirection | str
    entry_price: float
    stop_price: float
    current_price: float
    initial_risk_distance: float
    current_r: float
    bars_in_trade: int
    volume: float
    session_active: bool = True
    opposite_signal: bool = False


@dataclass(frozen=True, slots=True)
class ManagementRule:
    action: ManagementAction | str
    trigger_r: float | None = None
    bars: int | None = None
    close_percent: float | None = None
    trail_distance: float | None = None
    move_stop_to_r: float | None = None
    scale_volume: float | None = None
    require_session_end: bool = False
    require_opposite_signal: bool = False
    priority: int = 100


@dataclass(frozen=True, slots=True)
class ManagementDecision:
    action: ManagementAction
    triggered: bool
    priority: int
    new_stop_price: float | None = None
    close_percent: float | None = None
    scale_volume: float | None = None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "triggered": self.triggered,
            "priority": self.priority,
            "new_stop_price": self.new_stop_price,
            "close_percent": self.close_percent,
            "scale_volume": self.scale_volume,
            "reason": self.reason,
        }


class UniversalPositionManagementEngine:
    """
    Deterministic position-management engine.

    Supported:
    - Break Even
    - Partial Close
    - Trailing Stop
    - Move SL after X R
    - Close after X bars
    - Close at session end
    - Close on opposite signal
    - Scale In / Scale Out
    - explicit rule priorities
    """

    def evaluate(
        self,
        state: PositionState,
        rules: list[ManagementRule] | tuple[ManagementRule, ...],
    ) -> list[ManagementDecision]:
        if not isinstance(state, PositionState):
            raise PositionManagementError("invalid_position_state")
        if not rules:
            return []

        direction = self._direction(state.direction)
        entry = self._positive(state.entry_price, "entry_price")
        current = self._positive(state.current_price, "current_price")
        stop = self._positive(state.stop_price, "stop_price")
        initial_risk = self._positive(
            state.initial_risk_distance, "initial_risk_distance"
        )
        current_r = self._number(state.current_r, "current_r")
        bars = self._non_negative_int(state.bars_in_trade, "bars_in_trade")
        volume = self._positive(state.volume, "volume")

        self._validate_stop_geometry(direction, entry, stop)

        decisions: list[ManagementDecision] = []
        for rule in sorted(rules, key=lambda x: int(x.priority)):
            action = self._action(rule.action)
            priority = int(rule.priority)
            if priority < 0:
                raise PositionManagementError("priority_must_be_non_negative")

            triggered = self._triggered(rule, state, current_r, bars)
            if not triggered:
                decisions.append(
                    ManagementDecision(
                        action=action,
                        triggered=False,
                        priority=priority,
                        reason="TRIGGER_NOT_MET",
                    )
                )
                continue

            if action == ManagementAction.BREAK_EVEN:
                new_stop = entry
                decisions.append(
                    ManagementDecision(
                        action=action,
                        triggered=True,
                        priority=priority,
                        new_stop_price=new_stop,
                        reason="BREAK_EVEN_TRIGGERED",
                    )
                )

            elif action == ManagementAction.PARTIAL_CLOSE:
                pct = self._allocation(rule.close_percent)
                decisions.append(
                    ManagementDecision(
                        action=action,
                        triggered=True,
                        priority=priority,
                        close_percent=pct,
                        reason="PARTIAL_CLOSE_TRIGGERED",
                    )
                )

            elif action == ManagementAction.TRAILING_STOP:
                distance = self._positive_required(
                    rule.trail_distance, "trail_distance"
                )
                new_stop = (
                    current - distance
                    if direction == PositionDirection.LONG
                    else current + distance
                )
                self._validate_stop_geometry(direction, entry, new_stop, allow_profit_side=True)
                decisions.append(
                    ManagementDecision(
                        action=action,
                        triggered=True,
                        priority=priority,
                        new_stop_price=new_stop,
                        reason="TRAILING_STOP_TRIGGERED",
                    )
                )

            elif action == ManagementAction.MOVE_STOP:
                target_r = self._number_required(
                    rule.move_stop_to_r, "move_stop_to_r"
                )
                new_stop = (
                    entry + initial_risk * target_r
                    if direction == PositionDirection.LONG
                    else entry - initial_risk * target_r
                )
                decisions.append(
                    ManagementDecision(
                        action=action,
                        triggered=True,
                        priority=priority,
                        new_stop_price=new_stop,
                        reason="MOVE_STOP_TRIGGERED",
                    )
                )

            elif action == ManagementAction.CLOSE_POSITION:
                decisions.append(
                    ManagementDecision(
                        action=action,
                        triggered=True,
                        priority=priority,
                        close_percent=100.0,
                        reason=self._close_reason(rule),
                    )
                )

            elif action == ManagementAction.SCALE_IN:
                scale = self._positive_required(
                    rule.scale_volume, "scale_volume"
                )
                decisions.append(
                    ManagementDecision(
                        action=action,
                        triggered=True,
                        priority=priority,
                        scale_volume=scale,
                        reason="SCALE_IN_TRIGGERED",
                    )
                )

            elif action == ManagementAction.SCALE_OUT:
                if rule.close_percent is not None:
                    pct = self._allocation(rule.close_percent)
                    decisions.append(
                        ManagementDecision(
                            action=action,
                            triggered=True,
                            priority=priority,
                            close_percent=pct,
                            reason="SCALE_OUT_TRIGGERED",
                        )
                    )
                else:
                    scale = self._positive_required(
                        rule.scale_volume, "scale_volume"
                    )
                    if scale > volume:
                        raise PositionManagementError(
                            "scale_out_volume_exceeds_position"
                        )
                    decisions.append(
                        ManagementDecision(
                            action=action,
                            triggered=True,
                            priority=priority,
                            scale_volume=scale,
                            reason="SCALE_OUT_TRIGGERED",
                        )
                    )
            else:
                raise PositionManagementError(
                    f"unsupported_management_action:{action.value}"
                )

        return decisions

    def highest_priority_trigger(
        self,
        state: PositionState,
        rules: list[ManagementRule] | tuple[ManagementRule, ...],
    ) -> ManagementDecision | None:
        for decision in self.evaluate(state, rules):
            if decision.triggered:
                return decision
        return None

    def _triggered(
        self,
        rule: ManagementRule,
        state: PositionState,
        current_r: float,
        bars: int,
    ) -> bool:
        triggers: list[bool] = []

        if rule.trigger_r is not None:
            triggers.append(
                current_r >= self._number(rule.trigger_r, "trigger_r")
            )

        if rule.bars is not None:
            target_bars = self._positive_int(rule.bars, "bars")
            triggers.append(bars >= target_bars)

        if rule.require_session_end:
            triggers.append(not bool(state.session_active))

        if rule.require_opposite_signal:
            triggers.append(bool(state.opposite_signal))

        if not triggers:
            raise PositionManagementError(
                f"management_trigger_required:{self._action(rule.action).value}"
            )

        return all(triggers)

    @staticmethod
    def _close_reason(rule: ManagementRule) -> str:
        if rule.require_opposite_signal:
            return "OPPOSITE_SIGNAL"
        if rule.require_session_end:
            return "SESSION_END"
        if rule.bars is not None:
            return "MAX_BARS"
        if rule.trigger_r is not None:
            return "R_TRIGGER"
        return "CLOSE_POSITION_TRIGGERED"

    @staticmethod
    def _validate_stop_geometry(
        direction: PositionDirection,
        entry: float,
        stop: float,
        *,
        allow_profit_side: bool = False,
    ) -> None:
        if allow_profit_side:
            return
        if direction == PositionDirection.LONG and stop >= entry:
            raise PositionManagementError("invalid_initial_stop_geometry:LONG")
        if direction == PositionDirection.SHORT and stop <= entry:
            raise PositionManagementError("invalid_initial_stop_geometry:SHORT")

    @staticmethod
    def _action(value: ManagementAction | str) -> ManagementAction:
        if isinstance(value, ManagementAction):
            return value
        raw = str(value or "").strip().upper().replace(" ", "_")
        aliases = {
            "BE": ManagementAction.BREAK_EVEN,
            "BREAKEVEN": ManagementAction.BREAK_EVEN,
            "PARTIAL": ManagementAction.PARTIAL_CLOSE,
            "TRAIL": ManagementAction.TRAILING_STOP,
            "CLOSE": ManagementAction.CLOSE_POSITION,
        }
        if raw in aliases:
            return aliases[raw]
        try:
            return ManagementAction(raw)
        except ValueError as exc:
            raise PositionManagementError(
                f"unsupported_management_action:{value}"
            ) from exc

    @staticmethod
    def _direction(value: PositionDirection | str) -> PositionDirection:
        if isinstance(value, PositionDirection):
            return value
        raw = str(value or "").strip().upper()
        aliases = {
            "BUY": PositionDirection.LONG,
            "LONG": PositionDirection.LONG,
            "SELL": PositionDirection.SHORT,
            "SHORT": PositionDirection.SHORT,
        }
        result = aliases.get(raw)
        if result is None:
            raise PositionManagementError(
                f"unsupported_position_direction:{value}"
            )
        return result

    @staticmethod
    def _number(value: Any, name: str) -> float:
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise PositionManagementError(
                f"management_value_not_numeric:{name}"
            ) from exc

    @classmethod
    def _positive(cls, value: Any, name: str) -> float:
        result = cls._number(value, name)
        if result <= 0:
            raise PositionManagementError(
                f"{name}_must_be_positive"
            )
        return result

    @classmethod
    def _positive_required(cls, value: Any, name: str) -> float:
        if value is None:
            raise PositionManagementError(f"{name}_required")
        return cls._positive(value, name)

    @classmethod
    def _number_required(cls, value: Any, name: str) -> float:
        if value is None:
            raise PositionManagementError(f"{name}_required")
        return cls._number(value, name)

    @staticmethod
    def _positive_int(value: Any, name: str) -> int:
        try:
            result = int(value)
        except (TypeError, ValueError) as exc:
            raise PositionManagementError(
                f"{name}_must_be_positive_integer"
            ) from exc
        if result <= 0:
            raise PositionManagementError(
                f"{name}_must_be_positive_integer"
            )
        return result

    @staticmethod
    def _non_negative_int(value: Any, name: str) -> int:
        try:
            result = int(value)
        except (TypeError, ValueError) as exc:
            raise PositionManagementError(
                f"{name}_must_be_non_negative_integer"
            ) from exc
        if result < 0:
            raise PositionManagementError(
                f"{name}_must_be_non_negative_integer"
            )
        return result

    @classmethod
    def _allocation(cls, value: Any) -> float:
        if value is None:
            raise PositionManagementError("close_percent_required")
        result = cls._number(value, "close_percent")
        if result <= 0 or result > 100:
            raise PositionManagementError(
                "close_percent_must_be_between_0_and_100"
            )
        return result
