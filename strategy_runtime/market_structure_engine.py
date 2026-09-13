from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable


class MarketStructureError(ValueError):
    """Fail-closed market-structure evaluation error."""


class SwingKind(str, Enum):
    HIGH = "SWING_HIGH"
    LOW = "SWING_LOW"


class StructureLabel(str, Enum):
    HH = "HH"
    HL = "HL"
    LH = "LH"
    LL = "LL"


class StructureEventType(str, Enum):
    BOS = "BOS"
    CHOCH = "CHOCH"
    MSS = "MSS"


class StructureDirection(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class StructureScope(str, Enum):
    INTERNAL = "INTERNAL"
    SWING = "SWING"


@dataclass(frozen=True, slots=True)
class SwingPoint:
    index: int
    price: float
    kind: SwingKind
    label: StructureLabel | None = None


@dataclass(frozen=True, slots=True)
class StructureEvent:
    event: StructureEventType
    direction: StructureDirection
    index: int
    price: float
    broken_level: float
    scope: StructureScope

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event.value,
            "direction": self.direction.value,
            "index": self.index,
            "price": self.price,
            "broken_level": self.broken_level,
            "scope": self.scope.value,
        }


@dataclass(frozen=True, slots=True)
class MarketStructureResult:
    swings: tuple[SwingPoint, ...]
    events: tuple[StructureEvent, ...]
    direction: StructureDirection
    scope: StructureScope

    def events_of(self, event: StructureEventType | str) -> list[StructureEvent]:
        target = event if isinstance(event, StructureEventType) else StructureEventType(str(event).upper())
        return [x for x in self.events if x.event == target]


class UniversalMarketStructureEngine:
    """
    Deterministic swing/structure engine.

    - detects confirmed pivot highs/lows;
    - labels HH/HL/LH/LL;
    - detects BOS and CHOCH from closes breaking confirmed swing levels;
    - exposes MSS as the first opposite-direction structural shift (CHOCH);
    - supports INTERNAL and SWING scopes through different pivot lengths;
    - never uses unconfirmed future pivots as already-known signals.
    """

    def analyze(
        self,
        rates: Any,
        *,
        swing_length: int = 2,
        scope: StructureScope | str = StructureScope.SWING,
    ) -> MarketStructureResult:
        rows = self._rows(rates)
        length = self._positive_int(swing_length, "swing_length")
        parsed_scope = self._scope(scope)

        if len(rows) < 2 * length + 3:
            raise MarketStructureError(
                f"insufficient_structure_history:{2 * length + 3}:{len(rows)}"
            )

        highs = self._series(rows, "high")
        lows = self._series(rows, "low")
        closes = self._series(rows, "close")

        raw_swings = self._detect_swings(highs, lows, length)
        swings = self._label_swings(raw_swings)
        events, direction = self._detect_events(
            closes=closes,
            swings=swings,
            confirmation_offset=length,
            scope=parsed_scope,
        )

        return MarketStructureResult(
            swings=tuple(swings),
            events=tuple(events),
            direction=direction,
            scope=parsed_scope,
        )

    def analyze_internal(
        self,
        rates: Any,
        *,
        swing_length: int = 1,
    ) -> MarketStructureResult:
        return self.analyze(
            rates,
            swing_length=swing_length,
            scope=StructureScope.INTERNAL,
        )

    def analyze_swing(
        self,
        rates: Any,
        *,
        swing_length: int = 3,
    ) -> MarketStructureResult:
        return self.analyze(
            rates,
            swing_length=swing_length,
            scope=StructureScope.SWING,
        )

    @staticmethod
    def _detect_swings(
        highs: list[float],
        lows: list[float],
        length: int,
    ) -> list[SwingPoint]:
        points: list[SwingPoint] = []

        for i in range(length, len(highs) - length):
            high_window = highs[i - length:i + length + 1]
            low_window = lows[i - length:i + length + 1]

            is_high = (
                highs[i] == max(high_window)
                and high_window.count(highs[i]) == 1
            )
            is_low = (
                lows[i] == min(low_window)
                and low_window.count(lows[i]) == 1
            )

            if is_high:
                points.append(SwingPoint(i, highs[i], SwingKind.HIGH))
            if is_low:
                points.append(SwingPoint(i, lows[i], SwingKind.LOW))

        points.sort(key=lambda x: (x.index, 0 if x.kind == SwingKind.HIGH else 1))
        return points

    @staticmethod
    def _label_swings(points: list[SwingPoint]) -> list[SwingPoint]:
        last_high: float | None = None
        last_low: float | None = None
        labeled: list[SwingPoint] = []

        for point in points:
            label = None
            if point.kind == SwingKind.HIGH:
                if last_high is not None:
                    label = StructureLabel.HH if point.price > last_high else StructureLabel.LH
                last_high = point.price
            else:
                if last_low is not None:
                    label = StructureLabel.HL if point.price > last_low else StructureLabel.LL
                last_low = point.price

            labeled.append(
                SwingPoint(
                    index=point.index,
                    price=point.price,
                    kind=point.kind,
                    label=label,
                )
            )

        return labeled

    @staticmethod
    def _detect_events(
        *,
        closes: list[float],
        swings: list[SwingPoint],
        confirmation_offset: int,
        scope: StructureScope,
    ) -> tuple[list[StructureEvent], StructureDirection]:
        events: list[StructureEvent] = []
        direction = StructureDirection.NEUTRAL
        active_high: SwingPoint | None = None
        active_low: SwingPoint | None = None
        broken_high_indices: set[int] = set()
        broken_low_indices: set[int] = set()

        # A pivot at i is only confirmed after i + confirmation_offset.
        confirmations: dict[int, list[SwingPoint]] = {}
        for swing in swings:
            confirmations.setdefault(
                swing.index + confirmation_offset, []
            ).append(swing)

        for i, close in enumerate(closes):
            for swing in confirmations.get(i, []):
                if swing.kind == SwingKind.HIGH:
                    active_high = swing
                else:
                    active_low = swing

            if (
                active_high is not None
                and active_high.index not in broken_high_indices
                and close > active_high.price
            ):
                event_type = (
                    StructureEventType.BOS
                    if direction in (StructureDirection.NEUTRAL, StructureDirection.BULLISH)
                    else StructureEventType.CHOCH
                )
                events.append(
                    StructureEvent(
                        event=event_type,
                        direction=StructureDirection.BULLISH,
                        index=i,
                        price=close,
                        broken_level=active_high.price,
                        scope=scope,
                    )
                )
                broken_high_indices.add(active_high.index)
                direction = StructureDirection.BULLISH

            if (
                active_low is not None
                and active_low.index not in broken_low_indices
                and close < active_low.price
            ):
                event_type = (
                    StructureEventType.BOS
                    if direction in (StructureDirection.NEUTRAL, StructureDirection.BEARISH)
                    else StructureEventType.CHOCH
                )
                events.append(
                    StructureEvent(
                        event=event_type,
                        direction=StructureDirection.BEARISH,
                        index=i,
                        price=close,
                        broken_level=active_low.price,
                        scope=scope,
                    )
                )
                broken_low_indices.add(active_low.index)
                direction = StructureDirection.BEARISH

        return events, direction

    @staticmethod
    def mss_events(result: MarketStructureResult) -> list[StructureEvent]:
        # In the universal ontology MSS is represented by a confirmed CHOCH.
        return [
            StructureEvent(
                event=StructureEventType.MSS,
                direction=x.direction,
                index=x.index,
                price=x.price,
                broken_level=x.broken_level,
                scope=x.scope,
            )
            for x in result.events
            if x.event == StructureEventType.CHOCH
        ]

    @staticmethod
    def _scope(value: StructureScope | str) -> StructureScope:
        if isinstance(value, StructureScope):
            return value
        raw = str(value or "").strip().upper()
        try:
            return StructureScope(raw)
        except ValueError as exc:
            raise MarketStructureError(f"unsupported_structure_scope:{value}") from exc

    @staticmethod
    def _positive_int(value: Any, name: str) -> int:
        try:
            result = int(value)
        except (TypeError, ValueError) as exc:
            raise MarketStructureError(f"invalid_structure_parameter:{name}") from exc
        if result <= 0:
            raise MarketStructureError(f"invalid_structure_parameter:{name}")
        return result

    @staticmethod
    def _rows(rates: Any) -> list[dict[str, Any]]:
        if hasattr(rates, "to_dict"):
            try:
                rows = rates.to_dict("records")
                if isinstance(rows, list) and rows:
                    return [dict(x) for x in rows]
            except Exception:
                pass
        if isinstance(rates, (list, tuple)) and rates:
            return [dict(x) for x in rates]
        raise MarketStructureError("structure_rates_required")

    @staticmethod
    def _series(rows: list[dict[str, Any]], field: str) -> list[float]:
        out: list[float] = []
        for row in rows:
            if field not in row:
                raise MarketStructureError(f"structure_field_missing:{field}")
            try:
                out.append(float(row[field]))
            except (TypeError, ValueError) as exc:
                raise MarketStructureError(f"structure_field_not_numeric:{field}") from exc
        return out
