from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .finder import (
    FVGFinder,
    FVGFinderConfig,
)
from .inverse import (
    IFVGBuilder,
    IFVGConfig,
)
from .mitigation import (
    FVGMitigationAnalyzer,
    FVGMitigationConfig,
)
from .models import (
    FVGEventType,
    FVGState,
    FVGStatus,
    FVGType,
    FVGZone,
)
from .scoring import (
    FVGScorer,
    FVGScorerConfig,
)


@dataclass(slots=True)
class FVGServiceConfig:
    minimum_gap_size: float = 0.0
    minimum_gap_ratio: float = 0.0

    use_last_closed_candle: bool = True

    require_middle_displacement: bool = False
    minimum_middle_body_ratio: float = 0.0

    partial_fill_threshold: float = 0.25
    mitigated_fill_threshold: float = 0.75
    invalidate_on_close_through: bool = True

    gap_size_target: float = 0.0010
    gap_ratio_target: float = 0.0010
    displacement_body_target: float = 0.80
    freshness_decay_per_bar: float = 5.0

    minimum_quality: float = 0.0

    build_ifvg: bool = True
    require_invalidated_source_for_ifvg: bool = True
    inherit_ifvg_quality: bool = True
    ifvg_quality_multiplier: float = 1.0
    minimum_ifvg_source_quality: float = 0.0


class FVGService:
    """
    Высокоуровневый FVG Engine.

    Pipeline:
    Rates
    -> FVGFinder
    -> Mitigation
    -> Scoring
    -> iFVG Builder
    -> FVGState
    """

    def __init__(
        self,
        config: FVGServiceConfig | None = None,
    ) -> None:
        self.config = (
            config
            if config is not None
            else FVGServiceConfig()
        )

        self._validate_config()

        self.finder = FVGFinder(
            FVGFinderConfig(
                minimum_gap_size=(
                    self.config.minimum_gap_size
                ),
                minimum_gap_ratio=(
                    self.config.minimum_gap_ratio
                ),
                use_last_closed_candle=(
                    self.config.use_last_closed_candle
                ),
                require_middle_displacement=(
                    self.config.require_middle_displacement
                ),
                minimum_middle_body_ratio=(
                    self.config.minimum_middle_body_ratio
                ),
            )
        )

        self.mitigation = FVGMitigationAnalyzer(
            FVGMitigationConfig(
                partial_fill_threshold=(
                    self.config.partial_fill_threshold
                ),
                mitigated_fill_threshold=(
                    self.config.mitigated_fill_threshold
                ),
                invalidate_on_close_through=(
                    self.config.invalidate_on_close_through
                ),
                use_last_closed_candle=(
                    self.config.use_last_closed_candle
                ),
            )
        )

        self.scorer = FVGScorer(
            FVGScorerConfig(
                gap_size_target=(
                    self.config.gap_size_target
                ),
                gap_ratio_target=(
                    self.config.gap_ratio_target
                ),
                displacement_body_target=(
                    self.config.displacement_body_target
                ),
                freshness_decay_per_bar=(
                    self.config.freshness_decay_per_bar
                ),
            )
        )

        self.inverse = IFVGBuilder(
            IFVGConfig(
                require_invalidated_source=(
                    self.config
                    .require_invalidated_source_for_ifvg
                ),
                inherit_quality=(
                    self.config.inherit_ifvg_quality
                ),
                quality_multiplier=(
                    self.config.ifvg_quality_multiplier
                ),
                minimum_source_quality=(
                    self.config.minimum_ifvg_source_quality
                ),
            )
        )

    def analyze(
        self,
        *,
        rates: Any,
    ) -> FVGState:
        candles = self._as_list(rates)

        if not candles:
            return FVGState(
                diagnostics={
                    "candles": 0,
                    "reason": "rates_missing",
                }
            )

        current_index = len(candles) - 1

        zones = self.finder.find(
            candles
        )

        zones = self.mitigation.update_many(
            rates=candles,
            zones=zones,
        )

        zones = self.scorer.apply_many(
            zones=zones,
            current_index=current_index,
        )

        zones = [
            zone
            for zone in zones
            if (
                zone.quality_score
                >= self.config.minimum_quality
            )
        ]

        ifvgs: list[FVGZone] = []

        if self.config.build_ifvg:
            ifvgs = (
                self.inverse
                .build_from_invalidated(
                    zones
                )
            )

        bullish_fvgs = [
            zone
            for zone in zones
            if (
                zone.event_type
                == FVGEventType.FVG
                and zone.zone_type
                == FVGType.BULLISH
            )
        ]

        bearish_fvgs = [
            zone
            for zone in zones
            if (
                zone.event_type
                == FVGEventType.FVG
                and zone.zone_type
                == FVGType.BEARISH
            )
        ]

        bullish_ifvgs = [
            zone
            for zone in ifvgs
            if (
                zone.zone_type
                == FVGType.BULLISH
            )
        ]

        bearish_ifvgs = [
            zone
            for zone in ifvgs
            if (
                zone.zone_type
                == FVGType.BEARISH
            )
        ]

        last_fvg = (
            zones[-1]
            if zones
            else None
        )

        last_ifvg = (
            ifvgs[-1]
            if ifvgs
            else None
        )

        diagnostics = {
            "candles": len(candles),
            "fvg_count": len(zones),
            "bullish_fvg_count": len(
                bullish_fvgs
            ),
            "bearish_fvg_count": len(
                bearish_fvgs
            ),
            "ifvg_count": len(ifvgs),
            "bullish_ifvg_count": len(
                bullish_ifvgs
            ),
            "bearish_ifvg_count": len(
                bearish_ifvgs
            ),
            "fresh_count": sum(
                1
                for zone in zones
                if zone.status
                == FVGStatus.FRESH
            ),
            "partial_count": sum(
                1
                for zone in zones
                if zone.status
                == FVGStatus.PARTIAL
            ),
            "mitigated_count": sum(
                1
                for zone in zones
                if zone.status
                == FVGStatus.MITIGATED
            ),
            "invalidated_count": sum(
                1
                for zone in zones
                if zone.status
                == FVGStatus.INVALIDATED
            ),
        }

        return FVGState(
            bullish_fvgs=bullish_fvgs,
            bearish_fvgs=bearish_fvgs,
            bullish_ifvgs=bullish_ifvgs,
            bearish_ifvgs=bearish_ifvgs,
            last_fvg=last_fvg,
            last_ifvg=last_ifvg,
            diagnostics=diagnostics,
        )

    def best_active_fvg(
        self,
        state: FVGState,
        *,
        zone_type: FVGType | None = None,
    ) -> FVGZone | None:
        zones = [
            *state.bullish_fvgs,
            *state.bearish_fvgs,
        ]

        active = [
            zone
            for zone in zones
            if zone.active
        ]

        if zone_type is not None:
            active = [
                zone
                for zone in active
                if zone.zone_type
                == zone_type
            ]

        if not active:
            return None

        return max(
            active,
            key=lambda zone: (
                zone.quality_score,
                zone.end_index,
            ),
        )

    def best_active_ifvg(
        self,
        state: FVGState,
        *,
        zone_type: FVGType | None = None,
    ) -> FVGZone | None:
        zones = [
            *state.bullish_ifvgs,
            *state.bearish_ifvgs,
        ]

        active = [
            zone
            for zone in zones
            if zone.active
        ]

        if zone_type is not None:
            active = [
                zone
                for zone in active
                if zone.zone_type
                == zone_type
            ]

        if not active:
            return None

        return max(
            active,
            key=lambda zone: (
                zone.quality_score,
                zone.end_index,
            ),
        )

    def _validate_config(
        self,
    ) -> None:
        if not (
            0.0
            <= self.config.minimum_quality
            <= 100.0
        ):
            raise ValueError(
                "minimum_quality must be "
                "between 0 and 100"
            )

        if (
            self.config.ifvg_quality_multiplier
            < 0
        ):
            raise ValueError(
                "ifvg_quality_multiplier "
                "cannot be negative"
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
