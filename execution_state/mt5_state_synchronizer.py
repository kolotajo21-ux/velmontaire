from __future__ import annotations

import time
from typing import Any

from core.execution_state import (
    ExecutionSnapshot,
    OrderState,
    OrderStateStatus,
    PositionState,
    PositionStateStatus,
)


class MT5StateSynchronizer:
    """
    Reads current broker state from an MT5-like API and converts it
    into the universal execution-state models.

    This class does not send, modify, or cancel orders.
    """

    def __init__(
        self,
        *,
        mt5: Any,
    ) -> None:
        self.mt5 = mt5

    def synchronize(
        self,
        *,
        symbol: str | None = None,
        synchronized_time: int | None = None,
    ) -> ExecutionSnapshot:
        now = int(
            synchronized_time
            if synchronized_time is not None
            else time.time()
        )

        raw_orders = self._get_orders(
            symbol=symbol
        )
        raw_positions = self._get_positions(
            symbol=symbol
        )

        orders = [
            self._map_order(
                item,
                updated_time=now,
            )
            for item in raw_orders
        ]

        positions = [
            self._map_position(
                item,
                updated_time=now,
            )
            for item in raw_positions
        ]

        return ExecutionSnapshot(
            orders=orders,
            positions=positions,
            synchronized_time=now,
            diagnostics={
                "orders_received": len(
                    raw_orders
                ),
                "positions_received": len(
                    raw_positions
                ),
                "symbol": symbol,
            },
        )

    def _get_orders(
        self,
        *,
        symbol: str | None,
    ) -> list[Any]:
        if symbol:
            result = self.mt5.orders_get(
                symbol=symbol
            )
        else:
            result = self.mt5.orders_get()

        if result is None:
            return []

        return list(result)

    def _get_positions(
        self,
        *,
        symbol: str | None,
    ) -> list[Any]:
        if symbol:
            result = self.mt5.positions_get(
                symbol=symbol
            )
        else:
            result = self.mt5.positions_get()

        if result is None:
            return []

        return list(result)

    def _map_order(
        self,
        raw: Any,
        *,
        updated_time: int,
    ) -> OrderState:
        order_type = int(
            self._value(
                raw,
                "type",
                -1,
            )
        )

        direction = (
            self._order_direction(
                order_type
            )
        )

        type_name = (
            self._order_type_name(
                order_type
            )
        )

        volume = float(
            self._value(
                raw,
                "volume_initial",
                self._value(
                    raw,
                    "volume_current",
                    0.0,
                ),
            )
            or 0.0
        )

        remaining = float(
            self._value(
                raw,
                "volume_current",
                volume,
            )
            or 0.0
        )

        filled_volume = max(
            0.0,
            volume - remaining,
        )

        status = (
            OrderStateStatus.PENDING
            if filled_volume <= 0.0
            else OrderStateStatus
            .PARTIALLY_FILLED
        )

        ticket = str(
            self._value(
                raw,
                "ticket",
                "",
            )
        )

        return OrderState(
            execution_id=(
                self._execution_id(
                    raw,
                    fallback=(
                        f"mt5:order:{ticket}"
                    ),
                )
            ),
            broker_order_id=ticket,
            symbol=str(
                self._value(
                    raw,
                    "symbol",
                    "",
                )
            ),
            direction=direction,
            order_type=type_name,
            volume=volume,
            price=float(
                self._value(
                    raw,
                    "price_open",
                    0.0,
                )
                or 0.0
            ),
            stop_loss=self._optional_float(
                self._value(
                    raw,
                    "sl",
                    None,
                )
            ),
            take_profit=self._optional_float(
                self._value(
                    raw,
                    "tp",
                    None,
                )
            ),
            filled_volume=filled_volume,
            status=status,
            created_time=int(
                self._value(
                    raw,
                    "time_setup",
                    0,
                )
                or 0
            ),
            updated_time=updated_time,
            metadata={
                "magic": self._value(
                    raw,
                    "magic",
                    None,
                ),
                "comment": self._value(
                    raw,
                    "comment",
                    "",
                ),
                "type_time": self._value(
                    raw,
                    "type_time",
                    None,
                ),
                "time_expiration": (
                    self._value(
                        raw,
                        "time_expiration",
                        0,
                    )
                ),
            },
        )

    def _map_position(
        self,
        raw: Any,
        *,
        updated_time: int,
    ) -> PositionState:
        position_type = int(
            self._value(
                raw,
                "type",
                -1,
            )
        )

        ticket = str(
            self._value(
                raw,
                "ticket",
                "",
            )
        )

        return PositionState(
            broker_position_id=ticket,
            symbol=str(
                self._value(
                    raw,
                    "symbol",
                    "",
                )
            ),
            direction=(
                self._position_direction(
                    position_type
                )
            ),
            volume=float(
                self._value(
                    raw,
                    "volume",
                    0.0,
                )
                or 0.0
            ),
            entry_price=float(
                self._value(
                    raw,
                    "price_open",
                    0.0,
                )
                or 0.0
            ),
            stop_loss=self._optional_float(
                self._value(
                    raw,
                    "sl",
                    None,
                )
            ),
            take_profit=self._optional_float(
                self._value(
                    raw,
                    "tp",
                    None,
                )
            ),
            current_price=self._optional_float(
                self._value(
                    raw,
                    "price_current",
                    None,
                )
            ),
            profit=float(
                self._value(
                    raw,
                    "profit",
                    0.0,
                )
                or 0.0
            ),
            status=PositionStateStatus.OPEN,
            opened_time=int(
                self._value(
                    raw,
                    "time",
                    0,
                )
                or 0
            ),
            updated_time=updated_time,
            metadata={
                "magic": self._value(
                    raw,
                    "magic",
                    None,
                ),
                "comment": self._value(
                    raw,
                    "comment",
                    "",
                ),
                "identifier": (
                    self._value(
                        raw,
                        "identifier",
                        None,
                    )
                ),
            },
        )

    def _order_direction(
        self,
        order_type: int,
    ) -> str:
        buy_types = {
            self._constant(
                "ORDER_TYPE_BUY",
                0,
            ),
            self._constant(
                "ORDER_TYPE_BUY_LIMIT",
                2,
            ),
            self._constant(
                "ORDER_TYPE_BUY_STOP",
                4,
            ),
        }

        sell_types = {
            self._constant(
                "ORDER_TYPE_SELL",
                1,
            ),
            self._constant(
                "ORDER_TYPE_SELL_LIMIT",
                3,
            ),
            self._constant(
                "ORDER_TYPE_SELL_STOP",
                5,
            ),
        }

        if order_type in buy_types:
            return "BUY"

        if order_type in sell_types:
            return "SELL"

        return "UNKNOWN"

    def _position_direction(
        self,
        position_type: int,
    ) -> str:
        if position_type == self._constant(
            "POSITION_TYPE_BUY",
            0,
        ):
            return "BUY"

        if position_type == self._constant(
            "POSITION_TYPE_SELL",
            1,
        ):
            return "SELL"

        return "UNKNOWN"

    def _order_type_name(
        self,
        order_type: int,
    ) -> str:
        mapping = {
            self._constant(
                "ORDER_TYPE_BUY",
                0,
            ): "BUY",
            self._constant(
                "ORDER_TYPE_SELL",
                1,
            ): "SELL",
            self._constant(
                "ORDER_TYPE_BUY_LIMIT",
                2,
            ): "BUY_LIMIT",
            self._constant(
                "ORDER_TYPE_SELL_LIMIT",
                3,
            ): "SELL_LIMIT",
            self._constant(
                "ORDER_TYPE_BUY_STOP",
                4,
            ): "BUY_STOP",
            self._constant(
                "ORDER_TYPE_SELL_STOP",
                5,
            ): "SELL_STOP",
        }

        return mapping.get(
            order_type,
            "UNKNOWN",
        )

    def _execution_id(
        self,
        raw: Any,
        *,
        fallback: str,
    ) -> str:
        comment = str(
            self._value(
                raw,
                "comment",
                "",
            )
            or ""
        ).strip()

        if comment.startswith(
            "execution_id="
        ):
            value = comment.split(
                "=",
                1,
            )[1].strip()

            if value:
                return value

        return fallback

    def _constant(
        self,
        name: str,
        fallback: int,
    ) -> int:
        return int(
            getattr(
                self.mt5,
                name,
                fallback,
            )
        )

    @staticmethod
    def _value(
        raw: Any,
        name: str,
        default: Any = None,
    ) -> Any:
        if isinstance(
            raw,
            dict,
        ):
            return raw.get(
                name,
                default,
            )

        return getattr(
            raw,
            name,
            default,
        )

    @staticmethod
    def _optional_float(
        value: Any,
    ) -> float | None:
        if value is None:
            return None

        try:
            number = float(value)
        except (
            TypeError,
            ValueError,
        ):
            return None

        # MT5 commonly represents unset SL/TP as 0.0.
        if number == 0.0:
            return None

        return number