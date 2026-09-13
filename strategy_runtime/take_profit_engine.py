from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class TakeProfitEngineError(ValueError):
    """Fail-closed take-profit construction error."""


class TakeProfitDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class TakeProfitMode(str, Enum):
    FIXED_PIPS = "FIXED_PIPS"
    FIXED_POINTS = "FIXED_POINTS"
    FIXED_PRICE = "FIXED_PRICE"
    PERCENT = "PERCENT"
    R_MULTIPLE = "R_MULTIPLE"
    ATR_MULTIPLE = "ATR_MULTIPLE"
    PREVIOUS_HIGH_LOW = "PREVIOUS_HIGH_LOW"
    LIQUIDITY = "LIQUIDITY"
    SESSION_HIGH_LOW = "SESSION_HIGH_LOW"
    STRUCTURE = "STRUCTURE"
    CUSTOM_REFERENCE = "CUSTOM_REFERENCE"


@dataclass(frozen=True, slots=True)
class TakeProfitTarget:
    price: float
    close_percent: float = 100.0
    label: str = "TP"

    def to_dict(self) -> dict[str, Any]:
        return {
            "price": self.price,
            "close_percent": self.close_percent,
            "label": self.label,
        }


@dataclass(frozen=True, slots=True)
class TakeProfitRequest:
    mode: TakeProfitMode | str
    direction: TakeProfitDirection | str
    entry_price: float
    value: float | None = None
    pip_size: float | None = None
    point_size: float | None = None
    atr: float | None = None
    stop_price: float | None = None
    reference_price: float | None = None
    buffer: float = 0.0
    close_percent: float = 100.0
    label: str = "TP"


@dataclass(frozen=True, slots=True)
class TakeProfitPlan:
    mode: TakeProfitMode
    direction: TakeProfitDirection
    entry_price: float
    targets: tuple[TakeProfitTarget, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "direction": self.direction.value,
            "entry_price": self.entry_price,
            "targets": [x.to_dict() for x in self.targets],
        }


class UniversalTakeProfitEngine:
    """Universal single/multi-target take-profit builder."""

    def build(self, request: TakeProfitRequest) -> TakeProfitPlan:
        target = self._build_target(request)
        return TakeProfitPlan(
            mode=self._mode(request.mode),
            direction=self._direction(request.direction),
            entry_price=self._positive(request.entry_price, "entry_price"),
            targets=(target,),
        )

    def build_multiple(
        self,
        requests: list[TakeProfitRequest] | tuple[TakeProfitRequest, ...],
        *,
        require_full_allocation: bool = True,
    ) -> TakeProfitPlan:
        if not requests:
            raise TakeProfitEngineError("take_profit_targets_required")

        first_mode = self._mode(requests[0].mode)
        direction = self._direction(requests[0].direction)
        entry = self._positive(requests[0].entry_price, "entry_price")
        targets: list[TakeProfitTarget] = []

        for request in requests:
            if self._direction(request.direction) != direction:
                raise TakeProfitEngineError("mixed_take_profit_directions")
            if abs(self._positive(request.entry_price, "entry_price") - entry) > 1e-12:
                raise TakeProfitEngineError("mixed_take_profit_entries")
            targets.append(self._build_target(request))

        total = sum(x.close_percent for x in targets)
        if total > 100.0 + 1e-9:
            raise TakeProfitEngineError(f"partial_allocation_exceeds_100:{total}")
        if require_full_allocation and abs(total - 100.0) > 1e-9:
            raise TakeProfitEngineError(f"partial_allocation_must_equal_100:{total}")

        # Targets must progress away from entry.
        prices = [x.price for x in targets]
        if direction == TakeProfitDirection.LONG:
            if prices != sorted(prices):
                raise TakeProfitEngineError("take_profit_targets_not_progressive")
        else:
            if prices != sorted(prices, reverse=True):
                raise TakeProfitEngineError("take_profit_targets_not_progressive")

        return TakeProfitPlan(
            mode=first_mode,
            direction=direction,
            entry_price=entry,
            targets=tuple(targets),
        )

    def _build_target(self, request: TakeProfitRequest) -> TakeProfitTarget:
        if not isinstance(request, TakeProfitRequest):
            raise TakeProfitEngineError("invalid_take_profit_request")

        mode = self._mode(request.mode)
        direction = self._direction(request.direction)
        entry = self._positive(request.entry_price, "entry_price")
        buffer = self._non_negative(request.buffer, "buffer")
        close_percent = self._allocation(request.close_percent)
        label = str(request.label or "TP").strip() or "TP"

        if mode == TakeProfitMode.FIXED_PIPS:
            distance = self._positive_required(request.value, "pips") * self._positive_required(request.pip_size, "pip_size")
            price = self._from_distance(entry, distance, direction)
        elif mode == TakeProfitMode.FIXED_POINTS:
            distance = self._positive_required(request.value, "points") * self._positive_required(request.point_size, "point_size")
            price = self._from_distance(entry, distance, direction)
        elif mode == TakeProfitMode.FIXED_PRICE:
            price = self._positive_required(request.value, "take_profit_price")
        elif mode == TakeProfitMode.PERCENT:
            distance = entry * self._positive_required(request.value, "percent") / 100.0
            price = self._from_distance(entry, distance, direction)
        elif mode == TakeProfitMode.R_MULTIPLE:
            multiple = self._positive_required(request.value, "r_multiple")
            stop = self._positive_required(request.stop_price, "stop_price")
            risk = abs(entry - stop)
            if risk <= 0:
                raise TakeProfitEngineError("stop_distance_must_be_positive")
            self._validate_stop_geometry(direction, entry, stop)
            price = self._from_distance(entry, risk * multiple, direction)
        elif mode == TakeProfitMode.ATR_MULTIPLE:
            distance = self._positive_required(request.value, "atr_multiple") * self._positive_required(request.atr, "atr")
            price = self._from_distance(entry, distance, direction)
        else:
            reference = self._positive_required(request.reference_price, "reference_price")
            price = (
                reference + buffer
                if direction == TakeProfitDirection.LONG
                else reference - buffer
            )

        self._validate_target_geometry(direction, entry, price)
        return TakeProfitTarget(price=price, close_percent=close_percent, label=label)

    @staticmethod
    def _from_distance(entry: float, distance: float, direction: TakeProfitDirection) -> float:
        return entry + distance if direction == TakeProfitDirection.LONG else entry - distance

    @staticmethod
    def _validate_target_geometry(direction: TakeProfitDirection, entry: float, target: float) -> None:
        if direction == TakeProfitDirection.LONG and target <= entry:
            raise TakeProfitEngineError(f"invalid_take_profit_geometry:LONG:{entry}:{target}")
        if direction == TakeProfitDirection.SHORT and target >= entry:
            raise TakeProfitEngineError(f"invalid_take_profit_geometry:SHORT:{entry}:{target}")

    @staticmethod
    def _validate_stop_geometry(direction: TakeProfitDirection, entry: float, stop: float) -> None:
        if direction == TakeProfitDirection.LONG and stop >= entry:
            raise TakeProfitEngineError(f"invalid_stop_geometry_for_r:LONG:{entry}:{stop}")
        if direction == TakeProfitDirection.SHORT and stop <= entry:
            raise TakeProfitEngineError(f"invalid_stop_geometry_for_r:SHORT:{entry}:{stop}")

    @staticmethod
    def _mode(value: TakeProfitMode | str) -> TakeProfitMode:
        if isinstance(value, TakeProfitMode):
            return value
        raw = str(value or "").strip().upper().replace(" ", "_")
        aliases = {
            "PIPS": TakeProfitMode.FIXED_PIPS,
            "POINTS": TakeProfitMode.FIXED_POINTS,
            "PRICE": TakeProfitMode.FIXED_PRICE,
            "RR": TakeProfitMode.R_MULTIPLE,
            "R": TakeProfitMode.R_MULTIPLE,
            "RISK_REWARD": TakeProfitMode.R_MULTIPLE,
            "ATR": TakeProfitMode.ATR_MULTIPLE,
            "PREVIOUS_HIGH": TakeProfitMode.PREVIOUS_HIGH_LOW,
            "PREVIOUS_LOW": TakeProfitMode.PREVIOUS_HIGH_LOW,
            "LIQUIDITY_TARGET": TakeProfitMode.LIQUIDITY,
            "SESSION_HIGH": TakeProfitMode.SESSION_HIGH_LOW,
            "SESSION_LOW": TakeProfitMode.SESSION_HIGH_LOW,
            "CUSTOM": TakeProfitMode.CUSTOM_REFERENCE,
        }
        if raw in aliases:
            return aliases[raw]
        try:
            return TakeProfitMode(raw)
        except ValueError as exc:
            raise TakeProfitEngineError(f"unsupported_take_profit_mode:{value}") from exc

    @staticmethod
    def _direction(value: TakeProfitDirection | str) -> TakeProfitDirection:
        if isinstance(value, TakeProfitDirection):
            return value
        raw = str(value or "").strip().upper()
        aliases = {
            "BUY": TakeProfitDirection.LONG,
            "LONG": TakeProfitDirection.LONG,
            "SELL": TakeProfitDirection.SHORT,
            "SHORT": TakeProfitDirection.SHORT,
        }
        result = aliases.get(raw)
        if result is None:
            raise TakeProfitEngineError(f"unsupported_take_profit_direction:{value}")
        return result

    @staticmethod
    def _number(value: Any, name: str) -> float:
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise TakeProfitEngineError(f"take_profit_value_not_numeric:{name}") from exc

    @classmethod
    def _positive(cls, value: Any, name: str) -> float:
        result = cls._number(value, name)
        if result <= 0:
            raise TakeProfitEngineError(f"{name}_must_be_positive")
        return result

    @classmethod
    def _positive_required(cls, value: Any, name: str) -> float:
        if value is None:
            raise TakeProfitEngineError(f"{name}_required")
        return cls._positive(value, name)

    @classmethod
    def _non_negative(cls, value: Any, name: str) -> float:
        result = cls._number(value, name)
        if result < 0:
            raise TakeProfitEngineError(f"{name}_must_be_non_negative")
        return result

    @classmethod
    def _allocation(cls, value: Any) -> float:
        result = cls._number(value, "close_percent")
        if result <= 0 or result > 100:
            raise TakeProfitEngineError("close_percent_must_be_between_0_and_100")
        return result
