from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class StopLossEngineError(ValueError):
    """Fail-closed stop-loss construction error."""


class StopDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class StopMode(str, Enum):
    FIXED_PIPS = "FIXED_PIPS"
    FIXED_POINTS = "FIXED_POINTS"
    FIXED_PRICE = "FIXED_PRICE"
    PERCENT = "PERCENT"
    ATR_MULTIPLE = "ATR_MULTIPLE"
    SWING = "SWING"
    ORDER_BLOCK = "ORDER_BLOCK"
    CANDLE = "CANDLE"
    STRUCTURE = "STRUCTURE"
    CUSTOM_REFERENCE = "CUSTOM_REFERENCE"


@dataclass(frozen=True, slots=True)
class StopLossRequest:
    mode: StopMode | str
    direction: StopDirection | str
    entry_price: float
    value: float | None = None
    pip_size: float | None = None
    point_size: float | None = None
    atr: float | None = None
    reference_price: float | None = None
    buffer: float = 0.0


@dataclass(frozen=True, slots=True)
class StopLossPlan:
    mode: StopMode
    direction: StopDirection
    entry_price: float
    stop_price: float
    distance: float
    risk_percent_of_entry: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "direction": self.direction.value,
            "entry_price": self.entry_price,
            "stop_price": self.stop_price,
            "distance": self.distance,
            "risk_percent_of_entry": self.risk_percent_of_entry,
        }


class UniversalStopLossEngine:
    """
    Universal stop-loss builder.

    Reference-based modes (SWING / ORDER_BLOCK / CANDLE / STRUCTURE /
    CUSTOM_REFERENCE) use an explicit reference price and optional absolute
    buffer. LONG places SL below reference; SHORT places SL above reference.
    """

    def build(self, request: StopLossRequest) -> StopLossPlan:
        if not isinstance(request, StopLossRequest):
            raise StopLossEngineError("invalid_stop_loss_request")

        mode = self._mode(request.mode)
        direction = self._direction(request.direction)
        entry = self._positive(request.entry_price, "entry_price")
        buffer = self._non_negative(request.buffer, "buffer")

        if mode == StopMode.FIXED_PIPS:
            value = self._positive_required(request.value, "pips")
            pip = self._positive_required(request.pip_size, "pip_size")
            distance = value * pip
            stop = self._from_distance(entry, distance, direction)

        elif mode == StopMode.FIXED_POINTS:
            value = self._positive_required(request.value, "points")
            point = self._positive_required(request.point_size, "point_size")
            distance = value * point
            stop = self._from_distance(entry, distance, direction)

        elif mode == StopMode.FIXED_PRICE:
            stop = self._positive_required(request.value, "stop_price")
            distance = abs(entry - stop)

        elif mode == StopMode.PERCENT:
            percent = self._positive_required(request.value, "percent")
            distance = entry * percent / 100.0
            stop = self._from_distance(entry, distance, direction)

        elif mode == StopMode.ATR_MULTIPLE:
            multiple = self._positive_required(request.value, "atr_multiple")
            atr = self._positive_required(request.atr, "atr")
            distance = atr * multiple
            stop = self._from_distance(entry, distance, direction)

        else:
            reference = self._positive_required(
                request.reference_price, "reference_price"
            )
            stop = (
                reference - buffer
                if direction == StopDirection.LONG
                else reference + buffer
            )
            distance = abs(entry - stop)

        self._validate_geometry(
            direction=direction,
            entry=entry,
            stop=stop,
        )

        if distance <= 0:
            raise StopLossEngineError("stop_distance_must_be_positive")

        return StopLossPlan(
            mode=mode,
            direction=direction,
            entry_price=entry,
            stop_price=stop,
            distance=distance,
            risk_percent_of_entry=(distance / entry) * 100.0,
        )

    @staticmethod
    def _from_distance(
        entry: float,
        distance: float,
        direction: StopDirection,
    ) -> float:
        return (
            entry - distance
            if direction == StopDirection.LONG
            else entry + distance
        )

    @staticmethod
    def _validate_geometry(
        *,
        direction: StopDirection,
        entry: float,
        stop: float,
    ) -> None:
        if direction == StopDirection.LONG and stop >= entry:
            raise StopLossEngineError(
                f"invalid_stop_geometry:LONG:{entry}:{stop}"
            )
        if direction == StopDirection.SHORT and stop <= entry:
            raise StopLossEngineError(
                f"invalid_stop_geometry:SHORT:{entry}:{stop}"
            )

    @staticmethod
    def _mode(value: StopMode | str) -> StopMode:
        if isinstance(value, StopMode):
            return value
        raw = str(value or "").strip().upper().replace(" ", "_")
        aliases = {
            "PIPS": StopMode.FIXED_PIPS,
            "POINTS": StopMode.FIXED_POINTS,
            "PRICE": StopMode.FIXED_PRICE,
            "ATR": StopMode.ATR_MULTIPLE,
            "SWING_HIGH_LOW": StopMode.SWING,
            "OB": StopMode.ORDER_BLOCK,
            "ORDERBLOCK": StopMode.ORDER_BLOCK,
            "CUSTOM": StopMode.CUSTOM_REFERENCE,
        }
        if raw in aliases:
            return aliases[raw]
        try:
            return StopMode(raw)
        except ValueError as exc:
            raise StopLossEngineError(
                f"unsupported_stop_mode:{value}"
            ) from exc

    @staticmethod
    def _direction(value: StopDirection | str) -> StopDirection:
        if isinstance(value, StopDirection):
            return value
        raw = str(value or "").strip().upper()
        aliases = {
            "BUY": StopDirection.LONG,
            "LONG": StopDirection.LONG,
            "SELL": StopDirection.SHORT,
            "SHORT": StopDirection.SHORT,
        }
        result = aliases.get(raw)
        if result is None:
            raise StopLossEngineError(
                f"unsupported_stop_direction:{value}"
            )
        return result

    @staticmethod
    def _number(value: Any, name: str) -> float:
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise StopLossEngineError(
                f"stop_value_not_numeric:{name}"
            ) from exc

    @classmethod
    def _positive(cls, value: Any, name: str) -> float:
        result = cls._number(value, name)
        if result <= 0:
            raise StopLossEngineError(
                f"{name}_must_be_positive"
            )
        return result

    @classmethod
    def _positive_required(cls, value: Any, name: str) -> float:
        if value is None:
            raise StopLossEngineError(
                f"{name}_required"
            )
        return cls._positive(value, name)

    @classmethod
    def _non_negative(cls, value: Any, name: str) -> float:
        result = cls._number(value, name)
        if result < 0:
            raise StopLossEngineError(
                f"{name}_must_be_non_negative"
            )
        return result
