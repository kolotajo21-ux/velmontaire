from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class SMCError(ValueError):
    """Fail-closed SMC/ICT evaluation error."""


class Direction(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"


@dataclass(frozen=True, slots=True)
class Zone:
    kind: str
    direction: Direction
    low: float
    high: float
    index: int
    metadata: dict[str, Any] | None = None

    @property
    def midpoint(self) -> float:
        return (self.low + self.high) / 2.0

    def contains(self, price: float) -> bool:
        return self.low <= float(price) <= self.high


@dataclass(frozen=True, slots=True)
class FairValueGap:
    direction: Direction
    low: float
    high: float
    index: int
    inverted: bool = False

    @property
    def midpoint(self) -> float:
        return (self.low + self.high) / 2.0


class UniversalSMCICTEngine:
    """
    Generic, deterministic SMC/ICT primitives.

    This engine deliberately models universal price-action definitions rather
    than claiming one author's discretionary interpretation is canonical.
    """

    def fair_value_gaps(self, rates: Any) -> list[FairValueGap]:
        rows = self._rows(rates)
        if len(rows) < 3:
            raise SMCError(f"insufficient_smc_history:3:{len(rows)}")

        gaps: list[FairValueGap] = []
        for i in range(2, len(rows)):
            first = rows[i - 2]
            third = rows[i]
            first_high = self._n(first, "high")
            first_low = self._n(first, "low")
            third_high = self._n(third, "high")
            third_low = self._n(third, "low")

            if third_low > first_high:
                gaps.append(FairValueGap(
                    Direction.BULLISH, first_high, third_low, i
                ))
            elif third_high < first_low:
                gaps.append(FairValueGap(
                    Direction.BEARISH, third_high, first_low, i
                ))
        return gaps

    def inverted_fvgs(self, rates: Any, gaps: list[FairValueGap] | None = None) -> list[FairValueGap]:
        rows = self._rows(rates)
        gaps = self.fair_value_gaps(rows) if gaps is None else gaps
        result: list[FairValueGap] = []

        for gap in gaps:
            for i in range(gap.index + 1, len(rows)):
                close = self._n(rows[i], "close")
                if gap.direction == Direction.BULLISH and close < gap.low:
                    result.append(FairValueGap(
                        Direction.BEARISH, gap.low, gap.high, i, True
                    ))
                    break
                if gap.direction == Direction.BEARISH and close > gap.high:
                    result.append(FairValueGap(
                        Direction.BULLISH, gap.low, gap.high, i, True
                    ))
                    break
        return result

    def displacement(
        self,
        rates: Any,
        *,
        lookback: int = 5,
        body_multiplier: float = 1.5,
    ) -> list[dict[str, Any]]:
        rows = self._rows(rates)
        lb = self._positive_int(lookback, "lookback")
        mult = self._positive_float(body_multiplier, "body_multiplier")
        if len(rows) <= lb:
            raise SMCError(f"insufficient_smc_history:{lb + 1}:{len(rows)}")

        out = []
        for i in range(lb, len(rows)):
            previous_bodies = [
                abs(self._n(x, "close") - self._n(x, "open"))
                for x in rows[i - lb:i]
            ]
            avg = sum(previous_bodies) / lb
            body = abs(self._n(rows[i], "close") - self._n(rows[i], "open"))
            if avg > 0 and body >= avg * mult:
                direction = (
                    Direction.BULLISH
                    if self._n(rows[i], "close") > self._n(rows[i], "open")
                    else Direction.BEARISH
                )
                out.append({
                    "index": i,
                    "direction": direction.value,
                    "body": body,
                    "average_body": avg,
                    "ratio": body / avg,
                })
        return out

    def order_blocks(
        self,
        rates: Any,
        *,
        displacement_lookback: int = 5,
        body_multiplier: float = 1.5,
        search_back: int = 4,
    ) -> list[Zone]:
        rows = self._rows(rates)
        displacements = self.displacement(
            rows, lookback=displacement_lookback, body_multiplier=body_multiplier
        )
        zones: list[Zone] = []
        back = self._positive_int(search_back, "search_back")

        for move in displacements:
            i = int(move["index"])
            direction = Direction(move["direction"])
            target_bearish = direction == Direction.BULLISH

            for j in range(i - 1, max(-1, i - back - 1), -1):
                open_ = self._n(rows[j], "open")
                close = self._n(rows[j], "close")
                is_bearish = close < open_
                if is_bearish == target_bearish:
                    zones.append(Zone(
                        kind="ORDER_BLOCK",
                        direction=direction,
                        low=self._n(rows[j], "low"),
                        high=self._n(rows[j], "high"),
                        index=j,
                        metadata={"displacement_index": i},
                    ))
                    break
        return self._dedupe_zones(zones)

    def breaker_blocks(self, rates: Any, order_blocks: list[Zone] | None = None) -> list[Zone]:
        rows = self._rows(rates)
        obs = self.order_blocks(rows) if order_blocks is None else order_blocks
        result: list[Zone] = []

        for ob in obs:
            for i in range(max(ob.index + 1, 0), len(rows)):
                close = self._n(rows[i], "close")
                broken = (
                    ob.direction == Direction.BULLISH and close < ob.low
                ) or (
                    ob.direction == Direction.BEARISH and close > ob.high
                )
                if broken:
                    result.append(Zone(
                        "BREAKER_BLOCK",
                        Direction.BEARISH if ob.direction == Direction.BULLISH else Direction.BULLISH,
                        ob.low, ob.high, i,
                        {"origin_order_block_index": ob.index},
                    ))
                    break
        return result

    def mitigation_blocks(self, rates: Any, order_blocks: list[Zone] | None = None) -> list[Zone]:
        rows = self._rows(rates)
        obs = self.order_blocks(rows) if order_blocks is None else order_blocks
        result: list[Zone] = []

        for ob in obs:
            displacement_index = int((ob.metadata or {}).get("displacement_index", ob.index + 1))
            for i in range(displacement_index + 1, len(rows)):
                high = self._n(rows[i], "high")
                low = self._n(rows[i], "low")
                if high >= ob.low and low <= ob.high:
                    result.append(Zone(
                        "MITIGATION_BLOCK", ob.direction, ob.low, ob.high, i,
                        {"origin_order_block_index": ob.index},
                    ))
                    break
        return result

    def premium_discount(
        self,
        *,
        range_low: float,
        range_high: float,
        price: float,
    ) -> dict[str, Any]:
        low = self._float(range_low, "range_low")
        high = self._float(range_high, "range_high")
        p = self._float(price, "price")
        if high <= low:
            raise SMCError("invalid_dealing_range")
        eq = (low + high) / 2.0
        zone = "EQUILIBRIUM" if p == eq else ("DISCOUNT" if p < eq else "PREMIUM")
        return {
            "range_low": low,
            "range_high": high,
            "equilibrium": eq,
            "price": p,
            "zone": zone,
        }

    def ote_zone(
        self,
        *,
        swing_low: float,
        swing_high: float,
        direction: Direction | str,
        lower_ratio: float = 0.62,
        upper_ratio: float = 0.79,
    ) -> Zone:
        low = self._float(swing_low, "swing_low")
        high = self._float(swing_high, "swing_high")
        if high <= low:
            raise SMCError("invalid_ote_range")
        d = self._direction(direction)
        r1 = self._ratio(lower_ratio, "lower_ratio")
        r2 = self._ratio(upper_ratio, "upper_ratio")
        if r1 >= r2:
            raise SMCError("invalid_ote_ratios")

        size = high - low
        if d == Direction.BULLISH:
            zone_high = high - size * r1
            zone_low = high - size * r2
        else:
            zone_low = low + size * r1
            zone_high = low + size * r2

        return Zone("OTE", d, zone_low, zone_high, -1, {
            "lower_ratio": r1, "upper_ratio": r2
        })

    def imbalances(self, rates: Any) -> list[FairValueGap]:
        return self.fair_value_gaps(rates)

    @staticmethod
    def _dedupe_zones(zones: list[Zone]) -> list[Zone]:
        seen = set()
        out = []
        for z in zones:
            key = (z.kind, z.direction, z.low, z.high, z.index)
            if key not in seen:
                seen.add(key)
                out.append(z)
        return out

    @staticmethod
    def _direction(value: Direction | str) -> Direction:
        if isinstance(value, Direction):
            return value
        try:
            return Direction(str(value or "").strip().upper())
        except ValueError as exc:
            raise SMCError(f"unsupported_smc_direction:{value}") from exc

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
        raise SMCError("smc_rates_required")

    @classmethod
    def _n(cls, row: dict[str, Any], field: str) -> float:
        if field not in row:
            raise SMCError(f"smc_field_missing:{field}")
        return cls._float(row[field], field)

    @staticmethod
    def _float(value: Any, name: str) -> float:
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise SMCError(f"smc_value_not_numeric:{name}") from exc

    @classmethod
    def _positive_int(cls, value: Any, name: str) -> int:
        try:
            result = int(value)
        except (TypeError, ValueError) as exc:
            raise SMCError(f"invalid_smc_parameter:{name}") from exc
        if result <= 0:
            raise SMCError(f"invalid_smc_parameter:{name}")
        return result

    @classmethod
    def _positive_float(cls, value: Any, name: str) -> float:
        result = cls._float(value, name)
        if result <= 0:
            raise SMCError(f"invalid_smc_parameter:{name}")
        return result

    @classmethod
    def _ratio(cls, value: Any, name: str) -> float:
        result = cls._float(value, name)
        if not 0 < result < 1:
            raise SMCError(f"invalid_smc_ratio:{name}")
        return result
