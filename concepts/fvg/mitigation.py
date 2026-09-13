from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .models import (
    FVGStatus,
    FVGType,
    FVGZone,
)


@dataclass(slots=True)
class FVGMitigationConfig:
    partial_fill_threshold: float = 0.25
    mitigated_fill_threshold: float = 0.75
    invalidate_on_close_through: bool = True
    use_last_closed_candle: bool = True


class FVGMitigationAnalyzer:
    """
    Отслеживает жизненный цикл FVG.

    Mitigation начинается только после формирования третьей свечи FVG.

    Bullish FVG:
    - касание происходит, когда цена возвращается вниз в зону;
    - полное закрытие ниже нижней границы может инвалидировать FVG.

    Bearish FVG:
    - касание происходит, когда цена возвращается вверх в зону;
    - полное закрытие выше верхней границы может инвалидировать FVG.
    """

    def __init__(
        self,
        config: FVGMitigationConfig | None = None,
    ) -> None:
        self.config = (
            config
            if config is not None
            else FVGMitigationConfig()
        )

        self._validate_config()

    def update(
        self,
        *,
        rates: Any,
        zone: FVGZone,
    ) -> FVGZone:
        candles = self._as_list(rates)

        if not candles:
            return zone

        last_index = (
            len(candles) - 2
            if self.config.use_last_closed_candle
            else len(candles) - 1
        )

        start_index = int(
            zone.end_index
        ) + 1

        if last_index < start_index:
            return zone

        first_touch_time = (
            zone.first_touch_time
        )

        last_touch_time = (
            zone.last_touch_time
        )

        touch_count = int(
            zone.touch_count
        )

        maximum_fill = float(
            zone.filled_percent
        )

        status = zone.status

        for index in range(
            start_index,
            last_index + 1,
        ):
            candle = candles[index]

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
            candle_time = self._get_int(
                candle,
                "time",
            )

            if self._is_invalidated(
                zone=zone,
                close=close,
            ):
                status = FVGStatus.INVALIDATED
                zone.active = False

                zone.metadata[
                    "invalidation_time"
                ] = int(candle_time)

                zone.metadata[
                    "invalidation_close"
                ] = float(close)

                break

            if not self._is_touched(
                zone=zone,
                high=high,
                low=low,
            ):
                continue

            touch_count += 1

            if first_touch_time is None:
                first_touch_time = int(
                    candle_time
                )

            last_touch_time = int(
                candle_time
            )

            fill_percent = (
                self._fill_percent(
                    zone=zone,
                    high=high,
                    low=low,
                )
            )

            maximum_fill = max(
                maximum_fill,
                fill_percent,
            )

            status = self._status_from_fill(
                maximum_fill
            )

            if status == FVGStatus.MITIGATED:
                zone.active = False
                break

        zone.first_touch_time = (
            first_touch_time
        )

        zone.last_touch_time = (
            last_touch_time
        )

        zone.touch_count = int(
            touch_count
        )

        zone.filled_percent = round(
            min(
                max(
                    maximum_fill,
                    0.0,
                ),
                100.0,
            ),
            2,
        )

        zone.status = status

        zone.metadata.update(
            {
                "partial_fill_threshold": float(
                    self.config
                    .partial_fill_threshold
                ),
                "mitigated_fill_threshold": float(
                    self.config
                    .mitigated_fill_threshold
                ),
                "mitigation_start_index": int(
                    start_index
                ),
            }
        )

        return zone

    def update_many(
        self,
        *,
        rates: Any,
        zones: Iterable[FVGZone],
    ) -> list[FVGZone]:
        return [
            self.update(
                rates=rates,
                zone=zone,
            )
            for zone in zones
        ]

    @staticmethod
    def _is_touched(
        *,
        zone: FVGZone,
        high: float,
        low: float,
    ) -> bool:
        return (
            low <= zone.high
            and high >= zone.low
        )

    def _is_invalidated(
        self,
        *,
        zone: FVGZone,
        close: float,
    ) -> bool:
        if not (
            self.config
            .invalidate_on_close_through
        ):
            return False

        if zone.zone_type == FVGType.BULLISH:
            return close < zone.low

        return close > zone.high

    @staticmethod
    def _fill_percent(
        *,
        zone: FVGZone,
        high: float,
        low: float,
    ) -> float:
        zone_range = (
            zone.high - zone.low
        )

        if zone_range <= 0:
            return 0.0

        if zone.zone_type == FVGType.BULLISH:
            deepest_price = max(
                min(
                    low,
                    zone.high,
                ),
                zone.low,
            )

            filled = (
                zone.high
                - deepest_price
            )

        else:
            deepest_price = min(
                max(
                    high,
                    zone.low,
                ),
                zone.high,
            )

            filled = (
                deepest_price
                - zone.low
            )

        return (
            filled
            / zone_range
            * 100.0
        )

    def _status_from_fill(
        self,
        fill_percent: float,
    ) -> FVGStatus:
        partial_threshold = (
            self.config
            .partial_fill_threshold
            * 100.0
        )

        mitigated_threshold = (
            self.config
            .mitigated_fill_threshold
            * 100.0
        )

        if (
            fill_percent
            >= mitigated_threshold
        ):
            return FVGStatus.MITIGATED

        if (
            fill_percent
            >= partial_threshold
        ):
            return FVGStatus.PARTIAL

        if fill_percent > 0:
            return FVGStatus.PARTIAL

        return FVGStatus.FRESH

    def _validate_config(
        self,
    ) -> None:
        if not (
            0.0
            <= self.config
            .partial_fill_threshold
            <= 1.0
        ):
            raise ValueError(
                "partial_fill_threshold must "
                "be between 0 and 1"
            )

        if not (
            0.0
            <= self.config
            .mitigated_fill_threshold
            <= 1.0
        ):
            raise ValueError(
                "mitigated_fill_threshold must "
                "be between 0 and 1"
            )

        if (
            self.config
            .mitigated_fill_threshold
            < self.config
            .partial_fill_threshold
        ):
            raise ValueError(
                "mitigated_fill_threshold cannot "
                "be smaller than "
                "partial_fill_threshold"
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