from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .models import (
    FVGEventType,
    FVGStatus,
    FVGType,
    FVGZone,
)


@dataclass(slots=True)
class IFVGConfig:
    require_invalidated_source: bool = True

    inherit_quality: bool = True
    quality_multiplier: float = 1.0

    reset_touch_state: bool = True

    keep_original_bounds: bool = True

    minimum_source_quality: float = 0.0


class IFVGBuilder:
    """
    Преобразует инвалидированный FVG в inverse FVG.

    Bullish FVG -> Bearish iFVG
    Bearish FVG -> Bullish iFVG

    Новый iFVG:
    - хранит ссылку на исходный FVG через source_fvg_id;
    - меняет направление;
    - сохраняет границы исходной зоны;
    - начинает новый жизненный цикл как FRESH;
    - не создаёт дубликаты.
    """

    def __init__(
        self,
        config: IFVGConfig | None = None,
    ) -> None:
        self.config = (
            config
            if config is not None
            else IFVGConfig()
        )

        self._validate_config()

    def build(
        self,
        zones: Iterable[FVGZone],
    ) -> list[FVGZone]:
        source_zones = list(
            zones
        )

        if not source_zones:
            return []

        inverse_zones: list[FVGZone] = []

        for source in source_zones:
            inverse = self.from_zone(
                source
            )

            if inverse is None:
                continue

            inverse_zones.append(
                inverse
            )

        inverse_zones.sort(
            key=lambda zone: (
                zone.end_index,
                zone.end_time,
            )
        )

        return self._remove_duplicates(
            inverse_zones
        )

    def from_zone(
        self,
        source: FVGZone,
    ) -> FVGZone | None:
        if (
            source.event_type
            != FVGEventType.FVG
        ):
            return None

        if (
            self.config
            .require_invalidated_source
            and source.status
            != FVGStatus.INVALIDATED
        ):
            return None

        if (
            source.quality_score
            < self.config
            .minimum_source_quality
        ):
            return None

        inverse_type = (
            FVGType.BEARISH
            if source.zone_type
            == FVGType.BULLISH
            else FVGType.BULLISH
        )

        high, low = self._bounds(
            source
        )

        quality_score = (
            self._inverse_quality(
                source
            )
        )

        inverse_id = (
            f"IFVG:"
            f"{inverse_type.value}:"
            f"{source.end_time}:"
            f"{source.zone_id}"
        )

        if self.config.reset_touch_state:
            filled_percent = 0.0
            touch_count = 0
            first_touch_time = None
            last_touch_time = None
            status = FVGStatus.FRESH
            active = True
        else:
            filled_percent = float(
                source.filled_percent
            )
            touch_count = int(
                source.touch_count
            )
            first_touch_time = (
                source.first_touch_time
            )
            last_touch_time = (
                source.last_touch_time
            )
            status = FVGStatus.FRESH
            active = True

        metadata = dict(
            source.metadata
        )

        metadata.update(
            {
                "source_zone_type": (
                    source.zone_type.value
                ),
                "source_event_type": (
                    source.event_type.value
                ),
                "source_status": (
                    source.status.value
                ),
                "source_quality_score": float(
                    source.quality_score
                ),
                "inverse_direction": (
                    inverse_type.value
                ),
                "created_from_invalidation": True,
            }
        )

        return FVGZone(
            zone_id=inverse_id,
            zone_type=inverse_type,
            event_type=FVGEventType.IFVG,
            high=float(
                high
            ),
            low=float(
                low
            ),
            start_index=int(
                source.start_index
            ),
            middle_index=int(
                source.middle_index
            ),
            end_index=int(
                source.end_index
            ),
            start_time=int(
                source.start_time
            ),
            middle_time=int(
                source.middle_time
            ),
            end_time=int(
                source.end_time
            ),
            gap_size=float(
                source.gap_size
            ),
            gap_ratio=float(
                source.gap_ratio
            ),
            status=status,
            filled_percent=float(
                filled_percent
            ),
            touch_count=int(
                touch_count
            ),
            first_touch_time=(
                int(first_touch_time)
                if first_touch_time
                is not None
                else None
            ),
            last_touch_time=(
                int(last_touch_time)
                if last_touch_time
                is not None
                else None
            ),
            quality_score=float(
                quality_score
            ),
            active=bool(
                active
            ),
            source_fvg_id=str(
                source.zone_id
            ),
            metadata=metadata,
        )

    def build_from_invalidated(
        self,
        zones: Iterable[FVGZone],
    ) -> list[FVGZone]:
        invalidated = [
            zone
            for zone in zones
            if (
                zone.event_type
                == FVGEventType.FVG
                and zone.status
                == FVGStatus.INVALIDATED
            )
        ]

        return self.build(
            invalidated
        )

    def _inverse_quality(
        self,
        source: FVGZone,
    ) -> float:
        if not self.config.inherit_quality:
            return 0.0

        score = (
            float(
                source.quality_score
            )
            * float(
                self.config
                .quality_multiplier
            )
        )

        return round(
            max(
                0.0,
                min(
                    score,
                    100.0,
                ),
            ),
            2,
        )

    def _bounds(
        self,
        source: FVGZone,
    ) -> tuple[float, float]:
        if self.config.keep_original_bounds:
            return (
                float(
                    source.high
                ),
                float(
                    source.low
                ),
            )

        high = max(
            float(source.high),
            float(source.low),
        )

        low = min(
            float(source.high),
            float(source.low),
        )

        return (
            high,
            low,
        )

    @staticmethod
    def _remove_duplicates(
        zones: Iterable[FVGZone],
    ) -> list[FVGZone]:
        filtered: list[FVGZone] = []

        seen: set[
            tuple[str, str]
        ] = set()

        for zone in zones:
            key = (
                zone.zone_type.value,
                str(
                    zone.source_fvg_id
                ),
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
            self.config
            .quality_multiplier
            < 0
        ):
            raise ValueError(
                "quality_multiplier "
                "cannot be negative"
            )

        if not (
            0.0
            <= self.config
            .minimum_source_quality
            <= 100.0
        ):
            raise ValueError(
                "minimum_source_quality "
                "must be between 0 and 100"
            )