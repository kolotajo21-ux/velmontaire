from __future__ import annotations

from typing import Any

from strategy_runtime.position_reconciliation import (
    BrokerPositionSnapshot,
    BrokerPositionStatus,
)


class MT5PositionReader:
    """
    Day 64 read-only MT5 position reader.

    Converts MetaTrader5.positions_get() data into BrokerPositionSnapshot
    for GenericPositionStateReconciler.

    No order_send / modify / close calls are performed here.
    """

    def __init__(self, *, mt5: Any | None = None) -> None:
        if mt5 is None:
            try:
                import MetaTrader5 as mt5_module
            except ImportError as exc:
                raise RuntimeError(
                    "MetaTrader5 package is not installed"
                ) from exc

            mt5 = mt5_module

        self.mt5 = mt5

    def get_position(
        self,
        *,
        broker_position_id: str,
        symbol: str | None = None,
    ) -> BrokerPositionSnapshot | None:
        if not broker_position_id:
            return None

        try:
            ticket = int(broker_position_id)
        except (TypeError, ValueError):
            return None

        try:
            positions = self.mt5.positions_get(
                ticket=ticket
            )
        except Exception:
            return None

        if positions is None:
            return None

        if len(positions) == 0:
            return BrokerPositionSnapshot(
                found=False,
                status=BrokerPositionStatus.CLOSED,
                broker_position_id=str(ticket),
                symbol=(
                    str(symbol).strip().upper()
                    if symbol
                    else None
                ),
            )

        if len(positions) != 1:
            return BrokerPositionSnapshot(
                found=False,
                status=BrokerPositionStatus.UNKNOWN,
                broker_position_id=str(ticket),
                symbol=(
                    str(symbol).strip().upper()
                    if symbol
                    else None
                ),
                metadata={
                    "reason": "broker_position_not_unique",
                    "count": len(positions),
                },
            )

        position = positions[0]

        broker_symbol = str(
            getattr(position, "symbol", "") or ""
        ).strip()

        if not broker_symbol:
            return BrokerPositionSnapshot(
                found=True,
                status=BrokerPositionStatus.UNKNOWN,
                broker_position_id=str(ticket),
                metadata={
                    "reason": "broker_position_symbol_missing",
                },
            )

        if (
            symbol is not None
            and str(symbol).strip().upper()
            != broker_symbol.upper()
        ):
            return BrokerPositionSnapshot(
                found=True,
                status=BrokerPositionStatus.UNKNOWN,
                broker_position_id=str(ticket),
                symbol=broker_symbol,
                metadata={
                    "reason": "broker_position_symbol_mismatch",
                    "requested_symbol": str(symbol),
                },
            )

        try:
            volume = float(
                getattr(position, "volume")
            )
            entry_price = float(
                getattr(position, "price_open")
            )
        except (TypeError, ValueError, AttributeError):
            return BrokerPositionSnapshot(
                found=True,
                status=BrokerPositionStatus.UNKNOWN,
                broker_position_id=str(ticket),
                symbol=broker_symbol,
                metadata={
                    "reason": "broker_position_numeric_data_invalid",
                },
            )

        if volume <= 0 or entry_price <= 0:
            return BrokerPositionSnapshot(
                found=True,
                status=BrokerPositionStatus.UNKNOWN,
                broker_position_id=str(ticket),
                symbol=broker_symbol,
                metadata={
                    "reason": "broker_position_numeric_data_invalid",
                },
            )

        side = self._side(
            getattr(
                position,
                "type",
                None,
            )
        )

        if side is None:
            return BrokerPositionSnapshot(
                found=True,
                status=BrokerPositionStatus.UNKNOWN,
                broker_position_id=str(ticket),
                symbol=broker_symbol,
                volume=volume,
                entry_price=entry_price,
                metadata={
                    "reason": "broker_position_side_unknown",
                },
            )

        stop_loss = self._positive_or_none(
            getattr(position, "sl", None)
        )
        take_profit = self._positive_or_none(
            getattr(position, "tp", None)
        )

        current_price = self._current_price(
            position=position,
            symbol=broker_symbol,
            side=side,
        )

        return BrokerPositionSnapshot(
            found=True,
            status=BrokerPositionStatus.OPEN,
            broker_position_id=str(ticket),
            symbol=broker_symbol,
            side=side,
            volume=volume,
            entry_price=entry_price,
            current_price=current_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            metadata={
                "source": "MT5PositionReader",
                "magic": getattr(
                    position,
                    "magic",
                    None,
                ),
                "comment": getattr(
                    position,
                    "comment",
                    None,
                ),
            },
        )

    def _side(self, value: Any) -> str | None:
        if value == getattr(
            self.mt5,
            "POSITION_TYPE_BUY",
            object(),
        ):
            return "LONG"

        if value == getattr(
            self.mt5,
            "POSITION_TYPE_SELL",
            object(),
        ):
            return "SHORT"

        return None

    def _current_price(
        self,
        *,
        position: Any,
        symbol: str,
        side: str,
    ) -> float | None:
        direct = self._positive_or_none(
            getattr(
                position,
                "price_current",
                None,
            )
        )
        if direct is not None:
            return direct

        try:
            tick = self.mt5.symbol_info_tick(
                symbol
            )
        except Exception:
            return None

        if tick is None:
            return None

        field = (
            "bid"
            if side == "LONG"
            else "ask"
        )

        return self._positive_or_none(
            getattr(
                tick,
                field,
                None,
            )
        )

    @staticmethod
    def _positive_or_none(
        value: Any,
    ) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None

        return (
            number
            if number > 0
            else None
        )