from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class EntryEngineError(ValueError):
    """Fail-closed entry construction/evaluation error."""


class EntryOrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


class EntryDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class ZoneReference(str, Enum):
    MIDPOINT = "MIDPOINT"
    DISTAL = "DISTAL"
    PROXIMAL = "PROXIMAL"


@dataclass(frozen=True, slots=True)
class EntryZone:
    low: float
    high: float

    def __post_init__(self) -> None:
        low = float(self.low)
        high = float(self.high)
        if high < low:
            raise EntryEngineError("invalid_entry_zone")
        object.__setattr__(self, "low", low)
        object.__setattr__(self, "high", high)

    @property
    def midpoint(self) -> float:
        return (self.low + self.high) / 2.0


@dataclass(frozen=True, slots=True)
class EntryRequest:
    order_type: EntryOrderType | str
    direction: EntryDirection | str
    reference_price: float | None = None
    zone: EntryZone | None = None
    zone_reference: ZoneReference | str | None = None
    offset: float = 0.0
    require_candle_close: bool = False
    first_touch_only: bool = False
    expiration_bars: int | None = None


@dataclass(frozen=True, slots=True)
class EntryPlan:
    order_type: EntryOrderType
    direction: EntryDirection
    entry_price: float
    require_candle_close: bool
    first_touch_only: bool
    expiration_bars: int | None
    zone: EntryZone | None = None
    zone_reference: ZoneReference | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "order_type": self.order_type.value,
            "direction": self.direction.value,
            "entry_price": self.entry_price,
            "require_candle_close": self.require_candle_close,
            "first_touch_only": self.first_touch_only,
            "expiration_bars": self.expiration_bars,
            "zone": None if self.zone is None else {
                "low": self.zone.low,
                "high": self.zone.high,
            },
            "zone_reference": None if self.zone_reference is None else self.zone_reference.value,
        }


@dataclass(slots=True)
class PendingEntryState:
    created_bar: int
    touches: int = 0
    filled: bool = False
    expired: bool = False


class UniversalEntryEngine:
    """
    Universal order-entry primitive.

    Supports MARKET/LIMIT/STOP, zone-based entries, midpoint/distal/proximal,
    absolute offsets, candle-close confirmation, first-touch semantics,
    and bar-based pending-order expiration.
    """

    def build(self, request: EntryRequest) -> EntryPlan:
        if not isinstance(request, EntryRequest):
            raise EntryEngineError("invalid_entry_request")

        order_type = self._order_type(request.order_type)
        direction = self._direction(request.direction)
        offset = self._number(request.offset, "offset")

        zone_ref = None
        if request.zone_reference is not None:
            zone_ref = self._zone_reference(request.zone_reference)

        if request.zone is not None:
            if zone_ref is None:
                raise EntryEngineError("zone_reference_required")
            base = self._zone_price(request.zone, zone_ref, direction)
        else:
            if request.reference_price is None:
                raise EntryEngineError("entry_reference_required")
            if zone_ref is not None:
                raise EntryEngineError("zone_required_for_zone_reference")
            base = self._number(request.reference_price, "reference_price")

        expiration = request.expiration_bars
        if expiration is not None:
            try:
                expiration = int(expiration)
            except (TypeError, ValueError) as exc:
                raise EntryEngineError("invalid_expiration_bars") from exc
            if expiration <= 0:
                raise EntryEngineError("invalid_expiration_bars")

        return EntryPlan(
            order_type=order_type,
            direction=direction,
            entry_price=base + offset,
            require_candle_close=bool(request.require_candle_close),
            first_touch_only=bool(request.first_touch_only),
            expiration_bars=expiration,
            zone=request.zone,
            zone_reference=zone_ref,
        )

    def validate_order_geometry(
        self,
        plan: EntryPlan,
        *,
        market_price: float,
        tolerance: float = 0.0,
    ) -> bool:
        market = self._number(market_price, "market_price")
        tol = self._non_negative(tolerance, "tolerance")

        if plan.order_type == EntryOrderType.MARKET:
            return True

        if plan.order_type == EntryOrderType.LIMIT:
            if plan.direction == EntryDirection.LONG:
                return plan.entry_price <= market + tol
            return plan.entry_price >= market - tol

        if plan.order_type == EntryOrderType.STOP:
            if plan.direction == EntryDirection.LONG:
                return plan.entry_price >= market - tol
            return plan.entry_price <= market + tol

        raise EntryEngineError("unsupported_entry_geometry")

    def evaluate_bar(
        self,
        plan: EntryPlan,
        state: PendingEntryState,
        *,
        bar_index: int,
        open_price: float,
        high: float,
        low: float,
        close: float,
    ) -> str:
        if state.filled:
            return "FILLED"
        if state.expired:
            return "EXPIRED"

        idx = int(bar_index)
        if idx < state.created_bar:
            raise EntryEngineError("bar_index_moved_backwards")

        if (
            plan.expiration_bars is not None
            and idx - state.created_bar >= plan.expiration_bars
        ):
            state.expired = True
            return "EXPIRED"

        o = self._number(open_price, "open")
        h = self._number(high, "high")
        l = self._number(low, "low")
        c = self._number(close, "close")
        if h < l:
            raise EntryEngineError("invalid_bar_range")

        if plan.order_type == EntryOrderType.MARKET:
            triggered = True
        else:
            triggered = l <= plan.entry_price <= h

        if not triggered:
            return "WAITING"

        state.touches += 1

        if plan.first_touch_only and state.touches > 1:
            return "MISSED_FIRST_TOUCH"

        if plan.require_candle_close:
            confirmed = self._close_confirms(plan, o, c)
            if not confirmed:
                return "TOUCHED_WAITING_CLOSE"

        state.filled = True
        return "FILLED"

    @staticmethod
    def _close_confirms(plan: EntryPlan, open_price: float, close: float) -> bool:
        if plan.direction == EntryDirection.LONG:
            return close > open_price
        return close < open_price

    @staticmethod
    def _zone_price(
        zone: EntryZone,
        ref: ZoneReference,
        direction: EntryDirection,
    ) -> float:
        if ref == ZoneReference.MIDPOINT:
            return zone.midpoint

        # Distal = far edge from current-price side of the zone.
        # Proximal = near edge. Direction makes this deterministic.
        if direction == EntryDirection.LONG:
            if ref == ZoneReference.DISTAL:
                return zone.low
            return zone.high

        if ref == ZoneReference.DISTAL:
            return zone.high
        return zone.low

    @staticmethod
    def _order_type(value: EntryOrderType | str) -> EntryOrderType:
        if isinstance(value, EntryOrderType):
            return value
        try:
            return EntryOrderType(str(value or "").strip().upper())
        except ValueError as exc:
            raise EntryEngineError(f"unsupported_entry_order_type:{value}") from exc

    @staticmethod
    def _direction(value: EntryDirection | str) -> EntryDirection:
        if isinstance(value, EntryDirection):
            return value
        raw = str(value or "").strip().upper()
        aliases = {
            "BUY": EntryDirection.LONG,
            "LONG": EntryDirection.LONG,
            "SELL": EntryDirection.SHORT,
            "SHORT": EntryDirection.SHORT,
        }
        result = aliases.get(raw)
        if result is None:
            raise EntryEngineError(f"unsupported_entry_direction:{value}")
        return result

    @staticmethod
    def _zone_reference(value: ZoneReference | str) -> ZoneReference:
        if isinstance(value, ZoneReference):
            return value
        try:
            return ZoneReference(str(value or "").strip().upper())
        except ValueError as exc:
            raise EntryEngineError(f"unsupported_zone_reference:{value}") from exc

    @staticmethod
    def _number(value: Any, name: str) -> float:
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise EntryEngineError(f"entry_value_not_numeric:{name}") from exc

    @classmethod
    def _non_negative(cls, value: Any, name: str) -> float:
        result = cls._number(value, name)
        if result < 0:
            raise EntryEngineError(f"{name}_must_be_non_negative")
        return result
