from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .models import (
    LiquidityDirection,
    LiquidityEvent,
    LiquidityEventType,
    LiquidityPool,
    LiquiditySide,
)


@dataclass(slots=True)
class LiquiditySweepConfig:
    minimum_penetration: float = 0.0
    minimum_penetration_ratio: float = 0.05
    minimum_reclaim_ratio: float = 0.0
    require_first_touch: bool = True
    use_last_closed_candle: bool = True


class LiquiditySweepAnalyzer:
    """
    Определяет Sweep и Run относительно Liquidity Pool.

    BUY_SIDE:
    - Sweep: high выше уровня, close обратно ниже уровня.
    - Run: close остаётся выше уровня.

    SELL_SIDE:
    - Sweep: low ниже уровня, close обратно выше уровня.
    - Run: close остаётся ниже уровня.
    """

    def __init__(
        self,
        config: LiquiditySweepConfig | None = None,
    ) -> None:
        self.config = (
            config
            if config is not None
            else LiquiditySweepConfig()
        )

        self._validate_config()

    def analyze(
        self,
        rates: Any,
        pools: Iterable[LiquidityPool],
    ) -> list[LiquidityEvent]:
        candles = self._as_list(rates)

        if len(candles) < 2:
            return []

        last_index = (
            len(candles) - 2
            if self.config.use_last_closed_candle
            else len(candles) - 1
        )

        if last_index < 0:
            return []

        events: list[LiquidityEvent] = []

        for pool in pools:
            if not pool.active:
                continue

            if pool.invalidated:
                continue

            event = self._find_event(
                candles=candles,
                pool=pool,
                last_index=last_index,
            )

            if event is None:
                continue

            events.append(event)

        events.sort(
            key=lambda event: (
                event.index,
                event.time,
            )
        )

        return self._remove_duplicates(
            events
        )

    def _find_event(
        self,
        *,
        candles: list[Any],
        pool: LiquidityPool,
        last_index: int,
    ) -> LiquidityEvent | None:
        level = float(pool.price)

        if level <= 0:
            return None

        start_index = max(
            int(pool.end_index) + 1,
            0,
        )

        touched_before = False

        for index in range(
            start_index,
            last_index + 1,
        ):
            candle = candles[index]

            open_price = self._get_float(
                candle,
                "open",
            )
            high = self._get_float(
                candle,
                "high",
            )
            low = self._get_float(
                candle,
                "low",
            )
            close = self._get_float(
                candle,
                "close",
            )

            total_range = high - low

            if total_range <= 0:
                continue

            if pool.side == LiquiditySide.BUY_SIDE:
                touched = high >= level

                if not touched:
                    continue

                penetration = high - level
                penetration_ratio = (
                    penetration / total_range
                )

                if (
                    penetration
                    < self.config.minimum_penetration
                ):
                    touched_before = True
                    continue

                if (
                    penetration_ratio
                    < self.config.minimum_penetration_ratio
                ):
                    touched_before = True
                    continue

                closed_back_inside = close < level
                continued_beyond = close > level

                if closed_back_inside:
                    event_type = LiquidityEventType.SWEEP
                    direction = LiquidityDirection.BEARISH
                    extreme_price = high

                elif continued_beyond:
                    event_type = LiquidityEventType.RUN
                    direction = LiquidityDirection.BULLISH
                    extreme_price = high

                else:
                    touched_before = True
                    continue

            elif pool.side == LiquiditySide.SELL_SIDE:
                touched = low <= level

                if not touched:
                    continue

                penetration = level - low
                penetration_ratio = (
                    penetration / total_range
                )

                if (
                    penetration
                    < self.config.minimum_penetration
                ):
                    touched_before = True
                    continue

                if (
                    penetration_ratio
                    < self.config.minimum_penetration_ratio
                ):
                    touched_before = True
                    continue

                closed_back_inside = close > level
                continued_beyond = close < level

                if closed_back_inside:
                    event_type = LiquidityEventType.SWEEP
                    direction = LiquidityDirection.BULLISH
                    extreme_price = low

                elif continued_beyond:
                    event_type = LiquidityEventType.RUN
                    direction = LiquidityDirection.BEARISH
                    extreme_price = low

                else:
                    touched_before = True
                    continue

            else:
                continue

            if (
                self.config.require_first_touch
                and touched_before
            ):
                return None

            if pool.side == LiquiditySide.BUY_SIDE:
                reclaim_distance = (
                    level - close
                    if event_type == LiquidityEventType.SWEEP
                    else close - level
                )
            else:
                reclaim_distance = (
                    close - level
                    if event_type == LiquidityEventType.SWEEP
                    else level - close
                )

            reclaim_ratio = max(
                reclaim_distance,
                0.0,
            ) / total_range

            if (
                event_type
                == LiquidityEventType.SWEEP
                and reclaim_ratio
                < self.config.minimum_reclaim_ratio
            ):
                touched_before = True
                continue

            quality_score = self._quality_score(
                penetration_ratio=penetration_ratio,
                reclaim_ratio=reclaim_ratio,
                event_type=event_type,
            )

            return LiquidityEvent(
                event_type=event_type,
                side=pool.side,
                direction=direction,
                index=int(index),
                time=self._get_int(
                    candle,
                    "time",
                ),
                level=float(level),
                close_price=float(close),
                extreme_price=float(
                    extreme_price
                ),
                penetration=float(
                    penetration
                ),
                penetration_ratio=float(
                    penetration_ratio
                ),
                closed_back_inside=bool(
                    closed_back_inside
                ),
                continued_beyond=bool(
                    continued_beyond
                ),
                confirmed=True,
                quality_score=float(
                    quality_score
                ),
                source_pool_id=(
                    pool.pool_id
                ),
                metadata={
                    "candle_open": float(
                        open_price
                    ),
                    "candle_high": float(
                        high
                    ),
                    "candle_low": float(
                        low
                    ),
                    "candle_close": float(
                        close
                    ),
                    "reclaim_distance": float(
                        reclaim_distance
                    ),
                    "reclaim_ratio": float(
                        reclaim_ratio
                    ),
                    "pool_strength": float(
                        pool.strength
                    ),
                },
            )

        return None

    @staticmethod
    def _quality_score(
        *,
        penetration_ratio: float,
        reclaim_ratio: float,
        event_type: LiquidityEventType,
    ) -> float:
        penetration_quality = min(
            max(
                penetration_ratio / 0.50,
                0.0,
            ),
            1.0,
        )

        reclaim_quality = min(
            max(
                reclaim_ratio / 0.50,
                0.0,
            ),
            1.0,
        )

        score = (
            penetration_quality * 50.0
            + reclaim_quality * 50.0
        )

        return round(
            min(
                max(score, 0.0),
                100.0,
            ),
            2,
        )

    @staticmethod
    def _remove_duplicates(
        events: Iterable[LiquidityEvent],
    ) -> list[LiquidityEvent]:
        filtered: list[LiquidityEvent] = []

        seen: set[
            tuple[str, str, int]
        ] = set()

        for event in events:
            key = (
                event.event_type.value,
                event.side.value,
                int(event.time),
            )

            if key in seen:
                continue

            seen.add(key)
            filtered.append(event)

        return filtered

    def _validate_config(
        self,
    ) -> None:
        if self.config.minimum_penetration < 0:
            raise ValueError(
                "minimum_penetration cannot "
                "be negative"
            )

        if (
            self.config.minimum_penetration_ratio
            < 0
        ):
            raise ValueError(
                "minimum_penetration_ratio "
                "cannot be negative"
            )

        if not (
            0.0
            <= self.config.minimum_reclaim_ratio
            <= 1.0
        ):
            raise ValueError(
                "minimum_reclaim_ratio "
                "must be between 0 and 1"
            )

    @staticmethod
    def _as_list(
        rates: Any,
    ) -> list[Any]:
        if rates is None:
            return []

        # pandas.DataFrame -> candle records.
        # list(DataFrame) returns column names, not rows.
        if hasattr(rates, "columns") and hasattr(rates, "to_dict"):
            try:
                return list(
                    rates.to_dict(
                        orient="records"
                    )
                )
            except Exception:
                return []

        try:
            return list(rates)
        except TypeError:
            return []

    @staticmethod
    def _get_float(
        candle: Any,
        field: str,
    ) -> float:
        try:
            return float(
                candle[field]
            )
        except (
            KeyError,
            IndexError,
            TypeError,
            ValueError,
        ):
            return 0.0

    @staticmethod
    def _get_int(
        candle: Any,
        field: str,
    ) -> int:
        try:
            return int(
                candle[field]
            )
        except (
            KeyError,
            IndexError,
            TypeError,
            ValueError,
        ):
            return 0