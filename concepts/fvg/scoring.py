from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import (
    FVGStatus,
    FVGZone,
)


@dataclass(slots=True)
class FVGScore:
    gap_size: float = 0.0
    gap_ratio: float = 0.0
    displacement: float = 0.0
    middle_candle: float = 0.0
    freshness: float = 0.0
    mitigation: float = 0.0

    total: float = 0.0

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "gap_size": float(
                self.gap_size
            ),
            "gap_ratio": float(
                self.gap_ratio
            ),
            "displacement": float(
                self.displacement
            ),
            "middle_candle": float(
                self.middle_candle
            ),
            "freshness": float(
                self.freshness
            ),
            "mitigation": float(
                self.mitigation
            ),
            "total": float(
                self.total
            ),
            "metadata": dict(
                self.metadata
            ),
        }


@dataclass(slots=True)
class FVGScorerConfig:
    gap_size_target: float = 0.0010
    gap_ratio_target: float = 0.0010

    displacement_body_target: float = 0.80

    freshness_decay_per_bar: float = 5.0

    weight_gap_size: float = 0.15
    weight_gap_ratio: float = 0.15
    weight_displacement: float = 0.20
    weight_middle_candle: float = 0.20
    weight_freshness: float = 0.15
    weight_mitigation: float = 0.15


class FVGScorer:
    """
    Оценивает качество FVG от 0 до 100.

    Компоненты:
    - размер gap;
    - относительный размер gap;
    - displacement;
    - сила средней свечи;
    - freshness;
    - состояние mitigation.
    """

    def __init__(
        self,
        config: FVGScorerConfig | None = None,
    ) -> None:

        self.config = (
            config
            if config is not None
            else FVGScorerConfig()
        )

        self._validate_config()

    def calculate(
        self,
        *,
        zone: FVGZone,
        current_index: int | None = None,
    ) -> FVGScore:

        gap_size_score = (
            self._scale_to_100(
                zone.gap_size,
                target=(
                    self.config
                    .gap_size_target
                ),
            )
        )

        gap_ratio_score = (
            self._scale_to_100(
                zone.gap_ratio,
                target=(
                    self.config
                    .gap_ratio_target
                ),
            )
        )

        middle_body_ratio = (
            self._safe_float(
                zone.metadata.get(
                    "middle_body_ratio",
                    0.0,
                )
            )
        )

        displacement_score = (
            self._scale_to_100(
                middle_body_ratio,
                target=(
                    self.config
                    .displacement_body_target
                ),
            )
        )

        middle_candle_score = (
            self._middle_candle_score(
                zone
            )
        )

        freshness_score = (
            self._freshness_score(
                zone=zone,
                current_index=current_index,
            )
        )

        mitigation_score = (
            self._mitigation_score(
                zone
            )
        )

        score = FVGScore(
            gap_size=float(
                gap_size_score
            ),
            gap_ratio=float(
                gap_ratio_score
            ),
            displacement=float(
                displacement_score
            ),
            middle_candle=float(
                middle_candle_score
            ),
            freshness=float(
                freshness_score
            ),
            mitigation=float(
                mitigation_score
            ),
            metadata={
                "raw_gap_size": float(
                    zone.gap_size
                ),
                "raw_gap_ratio": float(
                    zone.gap_ratio
                ),
                "middle_body_ratio": float(
                    middle_body_ratio
                ),
                "filled_percent": float(
                    zone.filled_percent
                ),
                "status": (
                    zone.status.value
                ),
            },
        )

        score.total = self._weighted_total(
            score
        )

        return score

    def apply(
        self,
        *,
        zone: FVGZone,
        current_index: int | None = None,
    ) -> FVGZone:

        score = self.calculate(
            zone=zone,
            current_index=current_index,
        )

        zone.quality_score = float(
            score.total
        )

        zone.metadata[
            "score"
        ] = score.to_dict()

        return zone

    def apply_many(
        self,
        *,
        zones: list[FVGZone],
        current_index: int | None = None,
    ) -> list[FVGZone]:

        return [
            self.apply(
                zone=zone,
                current_index=current_index,
            )
            for zone in zones
        ]

    def _weighted_total(
        self,
        score: FVGScore,
    ) -> float:

        total = (
            score.gap_size
            * self.config.weight_gap_size

            + score.gap_ratio
            * self.config.weight_gap_ratio

            + score.displacement
            * self.config.weight_displacement

            + score.middle_candle
            * self.config.weight_middle_candle

            + score.freshness
            * self.config.weight_freshness

            + score.mitigation
            * self.config.weight_mitigation
        )

        return round(
            max(
                0.0,
                min(
                    total,
                    100.0,
                ),
            ),
            2,
        )

    def _middle_candle_score(
        self,
        zone: FVGZone,
    ) -> float:

        body_ratio = self._safe_float(
            zone.metadata.get(
                "middle_body_ratio",
                0.0,
            )
        )

        middle_range = self._safe_float(
            zone.metadata.get(
                "middle_range",
                0.0,
            )
        )

        middle_body = self._safe_float(
            zone.metadata.get(
                "middle_body",
                0.0,
            )
        )

        body_quality = (
            self._scale_to_100(
                body_ratio,
                target=0.75,
            )
        )

        if middle_range > 0:
            body_share = (
                middle_body
                / middle_range
            )
        else:
            body_share = 0.0

        body_share_score = (
            self._scale_to_100(
                body_share,
                target=0.75,
            )
        )

        return round(
            (
                body_quality
                + body_share_score
            )
            / 2.0,
            2,
        )

    def _freshness_score(
        self,
        *,
        zone: FVGZone,
        current_index: int | None,
    ) -> float:

        if not zone.active:
            return 0.0

        if (
            zone.status
            == FVGStatus.INVALIDATED
        ):
            return 0.0

        if current_index is None:
            current_index = (
                zone.end_index
            )

        bars_old = max(
            int(current_index)
            - int(zone.end_index),
            0,
        )

        decay = (
            bars_old
            * self.config
            .freshness_decay_per_bar
        )

        score = (
            100.0 - decay
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

    @staticmethod
    def _mitigation_score(
        zone: FVGZone,
    ) -> float:

        if (
            zone.status
            == FVGStatus.FRESH
        ):
            return 100.0

        if (
            zone.status
            == FVGStatus.PARTIAL
        ):
            return max(
                0.0,
                100.0
                - float(
                    zone.filled_percent
                ),
            )

        if (
            zone.status
            in {
                FVGStatus.MITIGATED,
                FVGStatus.INVALIDATED,
            }
        ):
            return 0.0

        return 0.0

    @staticmethod
    def _scale_to_100(
        value: float,
        *,
        target: float,
    ) -> float:

        if target <= 0:
            return 0.0

        normalized = (
            value / target
        )

        return round(
            max(
                0.0,
                min(
                    normalized,
                    1.0,
                ),
            )
            * 100.0,
            2,
        )

    def _validate_config(
        self,
    ) -> None:

        if (
            self.config.gap_size_target
            <= 0
        ):
            raise ValueError(
                "gap_size_target must "
                "be greater than 0"
            )

        if (
            self.config.gap_ratio_target
            <= 0
        ):
            raise ValueError(
                "gap_ratio_target must "
                "be greater than 0"
            )

        if not (
            0.0
            < self.config
            .displacement_body_target
            <= 1.0
        ):
            raise ValueError(
                "displacement_body_target "
                "must be between 0 and 1"
            )

        if (
            self.config
            .freshness_decay_per_bar
            < 0
        ):
            raise ValueError(
                "freshness_decay_per_bar "
                "cannot be negative"
            )

        weights = [
            self.config.weight_gap_size,
            self.config.weight_gap_ratio,
            self.config.weight_displacement,
            self.config.weight_middle_candle,
            self.config.weight_freshness,
            self.config.weight_mitigation,
        ]

        if any(
            weight < 0
            for weight in weights
        ):
            raise ValueError(
                "FVG score weights "
                "cannot be negative"
            )

        total_weight = sum(
            weights
        )

        if abs(
            total_weight - 1.0
        ) > 1e-9:
            raise ValueError(
                "FVG score weights "
                "must sum to 1.0"
            )

    @staticmethod
    def _safe_float(
        value: Any,
    ) -> float:

        try:
            return float(
                value
            )

        except (
            TypeError,
            ValueError,
        ):
            return 0.0