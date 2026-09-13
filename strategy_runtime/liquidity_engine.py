from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable


class LiquidityEngineError(ValueError):
    """Fail-closed liquidity evaluation error."""


class LiquiditySide(str, Enum):
    BSL = "BSL"
    SSL = "SSL"


class LiquidityEventType(str, Enum):
    SWEEP = "LIQUIDITY_SWEEP"
    GRAB = "LIQUIDITY_GRAB"


class LiquidityLevelType(str, Enum):
    PREVIOUS_HIGH = "PREVIOUS_HIGH"
    PREVIOUS_LOW = "PREVIOUS_LOW"
    SESSION_HIGH = "SESSION_HIGH"
    SESSION_LOW = "SESSION_LOW"
    EQH = "EQH"
    EQL = "EQL"
    CUSTOM = "CUSTOM"


@dataclass(frozen=True, slots=True)
class LiquidityLevel:
    level_type: LiquidityLevelType
    side: LiquiditySide
    price: float
    source: str
    index: int | None = None


@dataclass(frozen=True, slots=True)
class LiquidityPool:
    pool_type: LiquidityLevelType
    side: LiquiditySide
    price: float
    indices: tuple[int, ...]
    tolerance: float


@dataclass(frozen=True, slots=True)
class LiquidityEvent:
    event: LiquidityEventType
    side: LiquiditySide
    level_type: LiquidityLevelType
    level: float
    index: int
    extreme: float
    close: float
    reclaimed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event.value,
            "side": self.side.value,
            "level_type": self.level_type.value,
            "level": self.level,
            "index": self.index,
            "extreme": self.extreme,
            "close": self.close,
            "reclaimed": self.reclaimed,
        }


class UniversalLiquidityEngine:
    """
    Generic liquidity engine.

    Supports:
    - BSL / SSL levels;
    - previous high / previous low;
    - session high / session low;
    - equal highs / equal lows;
    - sweep: wick trades through a level and closes back through it;
    - grab: price trades through a level, with reclaim optional;
    - custom liquidity levels;
    - tolerance in absolute price units.
    """

    def previous_high(self, rates: Any, *, offset: int = 1) -> LiquidityLevel:
        rows = self._rows(rates)
        row = self._offset_row(rows, offset)
        return LiquidityLevel(
            LiquidityLevelType.PREVIOUS_HIGH,
            LiquiditySide.BSL,
            self._number(row, "high"),
            f"previous_high:{offset}",
            len(rows) - 1 - offset,
        )

    def previous_low(self, rates: Any, *, offset: int = 1) -> LiquidityLevel:
        rows = self._rows(rates)
        row = self._offset_row(rows, offset)
        return LiquidityLevel(
            LiquidityLevelType.PREVIOUS_LOW,
            LiquiditySide.SSL,
            self._number(row, "low"),
            f"previous_low:{offset}",
            len(rows) - 1 - offset,
        )

    def session_high(self, price: float, *, session: str) -> LiquidityLevel:
        return LiquidityLevel(
            LiquidityLevelType.SESSION_HIGH,
            LiquiditySide.BSL,
            self._float(price, "session_high"),
            str(session),
        )

    def session_low(self, price: float, *, session: str) -> LiquidityLevel:
        return LiquidityLevel(
            LiquidityLevelType.SESSION_LOW,
            LiquiditySide.SSL,
            self._float(price, "session_low"),
            str(session),
        )

    def custom_level(
        self,
        price: float,
        *,
        side: LiquiditySide | str,
        source: str = "custom",
    ) -> LiquidityLevel:
        parsed_side = self._side(side)
        return LiquidityLevel(
            LiquidityLevelType.CUSTOM,
            parsed_side,
            self._float(price, "custom_level"),
            str(source),
        )

    def equal_highs(
        self,
        rates: Any,
        *,
        tolerance: float,
        min_touches: int = 2,
        lookback: int | None = None,
    ) -> list[LiquidityPool]:
        return self._equal_levels(
            rates,
            field="high",
            side=LiquiditySide.BSL,
            pool_type=LiquidityLevelType.EQH,
            tolerance=tolerance,
            min_touches=min_touches,
            lookback=lookback,
        )

    def equal_lows(
        self,
        rates: Any,
        *,
        tolerance: float,
        min_touches: int = 2,
        lookback: int | None = None,
    ) -> list[LiquidityPool]:
        return self._equal_levels(
            rates,
            field="low",
            side=LiquiditySide.SSL,
            pool_type=LiquidityLevelType.EQL,
            tolerance=tolerance,
            min_touches=min_touches,
            lookback=lookback,
        )

    def detect(
        self,
        rates: Any,
        level: LiquidityLevel,
        *,
        start_index: int = 0,
        tolerance: float = 0.0,
        classify_grab_without_reclaim: bool = True,
    ) -> list[LiquidityEvent]:
        rows = self._rows(rates)
        if not isinstance(level, LiquidityLevel):
            raise LiquidityEngineError("invalid_liquidity_level")

        tol = self._non_negative_float(tolerance, "tolerance")
        start = int(start_index)
        if start < 0 or start >= len(rows):
            raise LiquidityEngineError(f"invalid_start_index:{start_index}")

        events: list[LiquidityEvent] = []

        for i in range(start, len(rows)):
            row = rows[i]
            high = self._number(row, "high")
            low = self._number(row, "low")
            close = self._number(row, "close")

            if level.side == LiquiditySide.BSL:
                pierced = high > level.price + tol
                reclaimed = close <= level.price + tol
                extreme = high
            else:
                pierced = low < level.price - tol
                reclaimed = close >= level.price - tol
                extreme = low

            if not pierced:
                continue

            if reclaimed:
                event_type = LiquidityEventType.SWEEP
            elif classify_grab_without_reclaim:
                event_type = LiquidityEventType.GRAB
            else:
                continue

            events.append(
                LiquidityEvent(
                    event=event_type,
                    side=level.side,
                    level_type=level.level_type,
                    level=level.price,
                    index=i,
                    extreme=extreme,
                    close=close,
                    reclaimed=reclaimed,
                )
            )

        return events

    def detect_pool(
        self,
        rates: Any,
        pool: LiquidityPool,
        *,
        start_index: int = 0,
    ) -> list[LiquidityEvent]:
        if not isinstance(pool, LiquidityPool):
            raise LiquidityEngineError("invalid_liquidity_pool")
        level = LiquidityLevel(
            level_type=pool.pool_type,
            side=pool.side,
            price=pool.price,
            source=pool.pool_type.value,
        )
        return self.detect(
            rates,
            level,
            start_index=start_index,
            tolerance=pool.tolerance,
        )

    def _equal_levels(
        self,
        rates: Any,
        *,
        field: str,
        side: LiquiditySide,
        pool_type: LiquidityLevelType,
        tolerance: float,
        min_touches: int,
        lookback: int | None,
    ) -> list[LiquidityPool]:
        rows = self._rows(rates)
        tol = self._non_negative_float(tolerance, "tolerance")
        touches = int(min_touches)
        if touches < 2:
            raise LiquidityEngineError("min_touches_must_be_at_least_2")

        start = 0
        if lookback is not None:
            lb = int(lookback)
            if lb <= 0:
                raise LiquidityEngineError("lookback_must_be_positive")
            start = max(0, len(rows) - lb)

        values = [(i, self._number(rows[i], field)) for i in range(start, len(rows))]
        used: set[int] = set()
        pools: list[LiquidityPool] = []

        for pos, (idx, price) in enumerate(values):
            if idx in used:
                continue
            group = [(idx, price)]
            for other_idx, other_price in values[pos + 1:]:
                if other_idx in used:
                    continue
                if abs(other_price - price) <= tol:
                    group.append((other_idx, other_price))

            if len(group) >= touches:
                indices = tuple(x[0] for x in group)
                avg_price = sum(x[1] for x in group) / len(group)
                pools.append(
                    LiquidityPool(
                        pool_type=pool_type,
                        side=side,
                        price=avg_price,
                        indices=indices,
                        tolerance=tol,
                    )
                )
                used.update(indices)

        return pools

    @staticmethod
    def _offset_row(rows: list[dict[str, Any]], offset: int) -> dict[str, Any]:
        value = int(offset)
        if value <= 0:
            raise LiquidityEngineError("previous_offset_must_be_positive")
        if len(rows) <= value:
            raise LiquidityEngineError(
                f"insufficient_liquidity_history:{value + 1}:{len(rows)}"
            )
        return rows[-1 - value]

    @staticmethod
    def _side(value: LiquiditySide | str) -> LiquiditySide:
        if isinstance(value, LiquiditySide):
            return value
        raw = str(value or "").strip().upper()
        aliases = {
            "BSL": LiquiditySide.BSL,
            "BUY_SIDE": LiquiditySide.BSL,
            "BUY_SIDE_LIQUIDITY": LiquiditySide.BSL,
            "SSL": LiquiditySide.SSL,
            "SELL_SIDE": LiquiditySide.SSL,
            "SELL_SIDE_LIQUIDITY": LiquiditySide.SSL,
        }
        result = aliases.get(raw)
        if result is None:
            raise LiquidityEngineError(f"unsupported_liquidity_side:{value}")
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
        raise LiquidityEngineError("liquidity_rates_required")

    @classmethod
    def _number(cls, row: dict[str, Any], field: str) -> float:
        if field not in row:
            raise LiquidityEngineError(f"liquidity_field_missing:{field}")
        return cls._float(row[field], field)

    @staticmethod
    def _float(value: Any, name: str) -> float:
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise LiquidityEngineError(f"liquidity_value_not_numeric:{name}") from exc

    @classmethod
    def _non_negative_float(cls, value: Any, name: str) -> float:
        result = cls._float(value, name)
        if result < 0:
            raise LiquidityEngineError(f"{name}_must_be_non_negative")
        return result
