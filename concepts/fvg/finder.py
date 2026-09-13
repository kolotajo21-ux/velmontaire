from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import (
    FVGEventType,
    FVGType,
    FVGZone,
)


@dataclass(slots=True)
class FVGFinderConfig:
    minimum_gap_size: float = 0.0
    minimum_gap_ratio: float = 0.0

    use_last_closed_candle: bool = True

    require_middle_displacement: bool = False
    minimum_middle_body_ratio: float = 0.0


class FVGFinder:
    """
    Ищет классические Fair Value Gaps по 3-свечной модели.

    Bullish FVG:
        low третьей свечи > high первой свечи.

    Bearish FVG:
        high третьей свечи < low первой свечи.

    Зона:
        Bullish -> [high first, low third]
        Bearish -> [high third, low first]
    """

    def __init__(
        self,
        config: FVGFinderConfig | None = None,
    ) -> None:
        self.config = (
            config
            if config is not None
            else FVGFinderConfig()
        )

        self._validate_config()

    def find(
        self,
        rates: Any,
    ) -> list[FVGZone]:
        candles = self._as_list(
            rates
        )

        if len(candles) < 3:
            return []

        last_index = (
            len(candles) - 2
            if self.config.use_last_closed_candle
            else len(candles) - 1
        )

        if last_index < 2:
            return []

        zones: list[FVGZone] = []

        for end_index in range(
            2,
            last_index + 1,
        ):
            start_index = (
                end_index - 2
            )

            middle_index = (
                end_index - 1
            )

            first = candles[
                start_index
            ]

            middle = candles[
                middle_index
            ]

            third = candles[
                end_index
            ]

            first_high = self._get_float(
                first,
                "high",
            )

            first_low = self._get_float(
                first,
                "low",
            )

            third_high = self._get_float(
                third,
                "high",
            )

            third_low = self._get_float(
                third,
                "low",
            )

            if (
                first_high <= 0
                or first_low <= 0
                or third_high <= 0
                or third_low <= 0
            ):
                continue

            middle_metrics = (
                self._middle_metrics(
                    middle
                )
            )

            if (
                self.config
                .require_middle_displacement
                and middle_metrics[
                    "body_ratio"
                ]
                < self.config
                .minimum_middle_body_ratio
            ):
                continue

            bullish_gap = (
                third_low
                - first_high
            )

            if bullish_gap > 0:
                zone = self._build_zone(
                    zone_type=FVGType.BULLISH,
                    first=first,
                    middle=middle,
                    third=third,
                    start_index=start_index,
                    middle_index=middle_index,
                    end_index=end_index,
                    low=first_high,
                    high=third_low,
                    gap_size=bullish_gap,
                    middle_metrics=middle_metrics,
                )

                if self._passes_filters(
                    zone
                ):
                    zones.append(
                        zone
                    )

            bearish_gap = (
                first_low
                - third_high
            )

            if bearish_gap > 0:
                zone = self._build_zone(
                    zone_type=FVGType.BEARISH,
                    first=first,
                    middle=middle,
                    third=third,
                    start_index=start_index,
                    middle_index=middle_index,
                    end_index=end_index,
                    low=third_high,
                    high=first_low,
                    gap_size=bearish_gap,
                    middle_metrics=middle_metrics,
                )

                if self._passes_filters(
                    zone
                ):
                    zones.append(
                        zone
                    )

        zones.sort(
            key=lambda zone: (
                zone.end_index,
                zone.end_time,
            )
        )

        return self._remove_duplicates(
            zones
        )

    def _build_zone(
        self,
        *,
        zone_type: FVGType,
        first: Any,
        middle: Any,
        third: Any,
        start_index: int,
        middle_index: int,
        end_index: int,
        low: float,
        high: float,
        gap_size: float,
        middle_metrics: dict[str, float],
    ) -> FVGZone:
        start_time = self._get_int(
            first,
            "time",
        )

        middle_time = self._get_int(
            middle,
            "time",
        )

        end_time = self._get_int(
            third,
            "time",
        )

        reference_price = max(
            abs(high),
            abs(low),
            1e-12,
        )

        gap_ratio = (
            gap_size
            / reference_price
        )

        zone_id = (
            f"FVG:"
            f"{zone_type.value}:"
            f"{start_time}:"
            f"{end_time}"
        )

        return FVGZone(
            zone_id=zone_id,
            zone_type=zone_type,
            event_type=FVGEventType.FVG,
            high=float(
                high
            ),
            low=float(
                low
            ),
            start_index=int(
                start_index
            ),
            middle_index=int(
                middle_index
            ),
            end_index=int(
                end_index
            ),
            start_time=int(
                start_time
            ),
            middle_time=int(
                middle_time
            ),
            end_time=int(
                end_time
            ),
            gap_size=float(
                gap_size
            ),
            gap_ratio=float(
                gap_ratio
            ),
            metadata={
                "middle_body_ratio": float(
                    middle_metrics[
                        "body_ratio"
                    ]
                ),
                "middle_range": float(
                    middle_metrics[
                        "range"
                    ]
                ),
                "middle_body": float(
                    middle_metrics[
                        "body"
                    ]
                ),
            },
        )

    def _passes_filters(
        self,
        zone: FVGZone,
    ) -> bool:
        if (
            zone.gap_size
            < self.config.minimum_gap_size
        ):
            return False

        if (
            zone.gap_ratio
            < self.config.minimum_gap_ratio
        ):
            return False

        return True

    @staticmethod
    def _middle_metrics(
        candle: Any,
    ) -> dict[str, float]:
        open_price = FVGFinder._get_float(
            candle,
            "open",
        )

        high = FVGFinder._get_float(
            candle,
            "high",
        )

        low = FVGFinder._get_float(
            candle,
            "low",
        )

        close = FVGFinder._get_float(
            candle,
            "close",
        )

        total_range = (
            high - low
        )

        body = abs(
            close - open_price
        )

        body_ratio = (
            body / total_range
            if total_range > 0
            else 0.0
        )

        return {
            "range": float(
                max(
                    total_range,
                    0.0,
                )
            ),
            "body": float(
                body
            ),
            "body_ratio": float(
                body_ratio
            ),
        }

    @staticmethod
    def _remove_duplicates(
        zones: list[FVGZone],
    ) -> list[FVGZone]:
        filtered: list[FVGZone] = []

        seen: set[
            tuple[str, int, int]
        ] = set()

        for zone in zones:
            key = (
                zone.zone_type.value,
                int(zone.start_time),
                int(zone.end_time),
            )

            if key in seen:
                continue

            seen.add(
                key
            )

            filtered.append(
                zone
            )

        return filtered

    def _validate_config(
        self,
    ) -> None:
        if (
            self.config.minimum_gap_size
            < 0
        ):
            raise ValueError(
                "minimum_gap_size cannot "
                "be negative"
            )

        if (
            self.config.minimum_gap_ratio
            < 0
        ):
            raise ValueError(
                "minimum_gap_ratio cannot "
                "be negative"
            )

        if not (
            0.0
            <= self.config
            .minimum_middle_body_ratio
            <= 1.0
        ):
            raise ValueError(
                "minimum_middle_body_ratio "
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