from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .models import (
    StructureDirection,
    StructureEvent,
    StructureEventType,
    SwingPoint,
    SwingType,
)


@dataclass(slots=True)
class BosAnalyzerConfig:
    minimum_body_ratio: float = 0.45
    minimum_break_ratio: float = 0.10
    require_first_close_beyond: bool = True
    use_last_closed_candle: bool = True


class BosAnalyzer:
    """
    Находит подтверждённые Break of Structure.

    Bullish BOS:
    свеча впервые закрылась выше подтверждённого Swing High.

    Bearish BOS:
    свеча впервые закрылась ниже подтверждённого Swing Low.

    Дополнительные фильтры:
    - минимальное отношение тела свечи к её диапазону;
    - минимальная глубина закрытия за пробитым уровнем;
    - один swing может быть пробит только один раз.
    """

    def __init__(
        self,
        config: BosAnalyzerConfig | None = None,
    ) -> None:
        self.config = (
            config
            if config is not None
            else BosAnalyzerConfig()
        )

        self._validate_config()

    def analyze(
        self,
        rates: Any,
        swings: Iterable[SwingPoint],
    ) -> list[StructureEvent]:
        candles = self._as_list(rates)

        if len(candles) < 3:
            return []

        last_index = (
            len(candles) - 2
            if self.config.use_last_closed_candle
            else len(candles) - 1
        )

        if last_index < 1:
            return []

        ordered_swings = sorted(
            list(swings),
            key=lambda swing: (
                swing.index,
                swing.time,
            ),
        )

        events: list[StructureEvent] = []
        broken_swing_ids: set[
            tuple[str, int, int]
        ] = set()

        for swing in ordered_swings:
            if not swing.confirmed:
                continue

            if swing.index < 0:
                continue

            if swing.index >= last_index:
                continue

            swing_id = (
                swing.swing_type.value,
                int(swing.index),
                int(swing.time),
            )

            if swing_id in broken_swing_ids:
                continue

            event = self._find_break(
                candles=candles,
                swing=swing,
                last_index=last_index,
            )

            if event is None:
                continue

            events.append(event)
            broken_swing_ids.add(swing_id)

        events.sort(
            key=lambda event: (
                event.index,
                event.time,
            )
        )

        return self._remove_duplicate_events(
            events
        )

    def _find_break(
        self,
        *,
        candles: list[Any],
        swing: SwingPoint,
        last_index: int,
    ) -> StructureEvent | None:
        level = float(swing.price)

        if level <= 0:
            return None

        start_index = max(
            int(swing.index) + 1,
            1,
        )

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

            body_ratio = (
                abs(close - open_price)
                / total_range
            )

            previous_close = self._get_float(
                candles[index - 1],
                "close",
            )

            if swing.swing_type == SwingType.HIGH:
                direction = (
                    StructureDirection.BULLISH
                )

                break_distance = (
                    close - level
                )

                broke_level = close > level

                already_beyond = (
                    previous_close > level
                )

            elif swing.swing_type == SwingType.LOW:
                direction = (
                    StructureDirection.BEARISH
                )

                break_distance = (
                    level - close
                )

                broke_level = close < level

                already_beyond = (
                    previous_close < level
                )

            else:
                continue

            if not broke_level:
                continue

            if (
                self.config.require_first_close_beyond
                and already_beyond
            ):
                continue

            break_ratio = (
                break_distance
                / total_range
            )

            if (
                body_ratio
                < self.config.minimum_body_ratio
            ):
                continue

            if (
                break_ratio
                < self.config.minimum_break_ratio
            ):
                continue

            quality_score = self._quality_score(
                body_ratio=body_ratio,
                break_ratio=break_ratio,
            )

            return StructureEvent(
                event_type=StructureEventType.BOS,
                direction=direction,
                index=int(index),
                time=self._get_int(
                    candle,
                    "time",
                ),
                broken_level=float(level),
                close_price=float(close),
                source_swing_index=int(
                    swing.index
                ),
                source_swing_time=int(
                    swing.time
                ),
                body_ratio=float(
                    body_ratio
                ),
                break_distance=float(
                    break_distance
                ),
                break_ratio=float(
                    break_ratio
                ),
                confirmed=True,
                quality_score=float(
                    quality_score
                ),
                metadata={
                    "source_swing_type": (
                        swing.swing_type.value
                    ),
                    "source_point_type": (
                        swing.point_type.value
                    ),
                    "previous_close": float(
                        previous_close
                    ),
                    "candle_open": float(
                        open_price
                    ),
                    "candle_high": float(
                        high
                    ),
                    "candle_low": float(
                        low
                    ),
                },
            )

        return None

    @staticmethod
    def _quality_score(
        *,
        body_ratio: float,
        break_ratio: float,
    ) -> float:
        body_quality = min(
            max(body_ratio, 0.0),
            1.0,
        )

        break_quality = min(
            max(
                break_ratio / 0.50,
                0.0,
            ),
            1.0,
        )

        score = (
            body_quality * 60.0
            + break_quality * 40.0
        )

        return round(
            min(score, 100.0),
            2,
        )

    @staticmethod
    def _remove_duplicate_events(
        events: Iterable[StructureEvent],
    ) -> list[StructureEvent]:
        filtered: list[
            StructureEvent
        ] = []

        seen: set[
            tuple[str, int, int | None]
        ] = set()

        for event in events:
            event_key = (
                event.direction.value,
                int(event.time),
                event.source_swing_index,
            )

            if event_key in seen:
                continue

            seen.add(event_key)
            filtered.append(event)

        return filtered

    def _validate_config(
        self,
    ) -> None:
        if not (
            0.0
            <= self.config.minimum_body_ratio
            <= 1.0
        ):
            raise ValueError(
                "minimum_body_ratio must be "
                "between 0 and 1"
            )

        if self.config.minimum_break_ratio < 0:
            raise ValueError(
                "minimum_break_ratio cannot "
                "be negative"
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