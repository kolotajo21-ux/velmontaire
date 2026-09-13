from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ManagementActionType(str, Enum):
    MOVE_SL_TO_BE = "MOVE_SL_TO_BE"
    PARTIAL_CLOSE = "PARTIAL_CLOSE"
    UPDATE_TRAILING_SL = "UPDATE_TRAILING_SL"


@dataclass(slots=True)
class ManagementAction:
    action_type: ManagementActionType
    payload: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_type": self.action_type.value,
            "payload": dict(self.payload),
        }


@dataclass(slots=True)
class ManagementEvaluation:
    current_r: float
    actions: list[ManagementAction] = field(
        default_factory=list
    )
    diagnostics: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_r": float(self.current_r),
            "actions": [
                action.to_dict()
                for action in self.actions
            ],
            "diagnostics": dict(self.diagnostics),
        }


class TradeManagementEvaluator:
    """
    Оценивает текущую цену относительно TradeManagementPlan.

    Поддерживает BUY/SELL:
    - Break Even;
    - Partial Close;
    - Trailing Stop.

    epsilon нужен для безопасного сравнения float:
    например 0.999999999999778 считается достигнутым 1.0R.
    """

    EPSILON = 1e-9

    def evaluate(
        self,
        *,
        plan: dict[str, Any],
        direction: str,
        current_price: float,
        state: dict[str, Any] | None = None,
    ) -> ManagementEvaluation:
        state = dict(state or {})

        entry_price = float(
            plan["entry_price"]
        )
        initial_stop = float(
            plan["initial_stop_loss"]
        )

        risk_distance = abs(
            entry_price - initial_stop
        )

        if risk_distance <= 0:
            raise ValueError(
                "risk_distance_invalid"
            )

        direction = str(
            direction
        ).upper()

        if direction == "BUY":
            current_r = (
                current_price - entry_price
            ) / risk_distance
        elif direction == "SELL":
            current_r = (
                entry_price - current_price
            ) / risk_distance
        else:
            raise ValueError(
                "direction_must_be_BUY_or_SELL"
            )

        actions: list[
            ManagementAction
        ] = []

        # Break Even
        if bool(
            plan.get(
                "break_even_enabled",
                False,
            )
        ):
            trigger = float(
                plan.get(
                    "break_even_trigger_r",
                    1.0,
                )
            )

            if (
                self._trigger_reached(
                    current_r,
                    trigger,
                )
                and not bool(
                    state.get(
                        "break_even_done",
                        False,
                    )
                )
            ):
                offset = float(
                    plan.get(
                        "break_even_offset",
                        0.0,
                    )
                )

                if direction == "BUY":
                    new_sl = (
                        entry_price + offset
                    )
                else:
                    new_sl = (
                        entry_price - offset
                    )

                actions.append(
                    ManagementAction(
                        action_type=(
                            ManagementActionType
                            .MOVE_SL_TO_BE
                        ),
                        payload={
                            "new_stop_loss": float(
                                new_sl
                            ),
                            "trigger_r": trigger,
                        },
                    )
                )

        # Partial Close
        if bool(
            plan.get(
                "partial_close_enabled",
                False,
            )
        ):
            trigger = float(
                plan.get(
                    "partial_close_trigger_r",
                    1.5,
                )
            )

            if (
                self._trigger_reached(
                    current_r,
                    trigger,
                )
                and not bool(
                    state.get(
                        "partial_close_done",
                        False,
                    )
                )
            ):
                close_percent = float(
                    plan.get(
                        "partial_close_percent",
                        50.0,
                    )
                )

                actions.append(
                    ManagementAction(
                        action_type=(
                            ManagementActionType
                            .PARTIAL_CLOSE
                        ),
                        payload={
                            "close_percent": (
                                close_percent
                            ),
                            "trigger_r": trigger,
                        },
                    )
                )

        # Trailing Stop
        if bool(
            plan.get(
                "trailing_enabled",
                False,
            )
        ):
            trigger = float(
                plan.get(
                    "trailing_trigger_r",
                    2.0,
                )
            )

            if self._trigger_reached(
                current_r,
                trigger,
            ):
                distance_r = float(
                    plan.get(
                        "trailing_distance_r",
                        1.0,
                    )
                )

                trailing_distance = (
                    risk_distance
                    * distance_r
                )

                if direction == "BUY":
                    new_sl = (
                        current_price
                        - trailing_distance
                    )
                else:
                    new_sl = (
                        current_price
                        + trailing_distance
                    )

                actions.append(
                    ManagementAction(
                        action_type=(
                            ManagementActionType
                            .UPDATE_TRAILING_SL
                        ),
                        payload={
                            "new_stop_loss": float(
                                new_sl
                            ),
                            "trigger_r": trigger,
                            "distance_r": distance_r,
                        },
                    )
                )

        diagnostics = {
            "direction": direction,
            "entry_price": entry_price,
            "initial_stop_loss": initial_stop,
            "risk_distance": risk_distance,
            "current_price": float(
                current_price
            ),
            "current_r": float(
                current_r
            ),
            "epsilon": float(
                self.EPSILON
            ),
            "break_even_done": bool(
                state.get(
                    "break_even_done",
                    False,
                )
            ),
            "partial_close_done": bool(
                state.get(
                    "partial_close_done",
                    False,
                )
            ),
        }

        return ManagementEvaluation(
            current_r=float(
                current_r
            ),
            actions=actions,
            diagnostics=diagnostics,
        )

    @classmethod
    def _trigger_reached(
        cls,
        current_r: float,
        trigger_r: float,
    ) -> bool:
        return (
            current_r
            + cls.EPSILON
            >= trigger_r
        )