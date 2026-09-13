from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from core.detector import (
    BaseDetector,
    DetectorContext,
    DetectorResult,
)

from .models import (
    FVGState,
)
from .services import (
    FVGService,
    FVGServiceConfig,
)


@dataclass(slots=True)
class FVGDetectorConfig:
    timeframe: str = "H4"

    minimum_quality: float = 0.0

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

    build_ifvg: bool = True
    require_invalidated_source_for_ifvg: bool = True
    inherit_ifvg_quality: bool = True
    ifvg_quality_multiplier: float = 1.0
    minimum_ifvg_source_quality: float = 0.0


class FVGDetector(BaseDetector):
    """
    Thin FVG detector.

    Heavy logic lives in FVGService:
    Finder -> Mitigation -> Scoring -> iFVG -> FVGState.
    """

    name = "fvg"
    version = "1.0.0"

    dependencies: tuple[str, ...] = ()

    def __init__(
        self,
        config: FVGDetectorConfig | None = None,
    ) -> None:
        self.config = (
            config
            if config is not None
            else FVGDetectorConfig()
        )

        self._validate_config()

        self.service = FVGService(
            FVGServiceConfig(
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
                partial_fill_threshold=(
                    self.config.partial_fill_threshold
                ),
                mitigated_fill_threshold=(
                    self.config.mitigated_fill_threshold
                ),
                invalidate_on_close_through=(
                    self.config.invalidate_on_close_through
                ),
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
                minimum_quality=(
                    self.config.minimum_quality
                ),
                build_ifvg=(
                    self.config.build_ifvg
                ),
                require_invalidated_source_for_ifvg=(
                    self.config
                    .require_invalidated_source_for_ifvg
                ),
                inherit_ifvg_quality=(
                    self.config.inherit_ifvg_quality
                ),
                ifvg_quality_multiplier=(
                    self.config.ifvg_quality_multiplier
                ),
                minimum_ifvg_source_quality=(
                    self.config.minimum_ifvg_source_quality
                ),
            )
        )

    def analyze(
        self,
        context: DetectorContext,
        snapshot: Mapping[str, Any],
    ) -> DetectorResult:
        timeframe = str(
            self.config.timeframe
        ).upper()

        rates = context.get_rates(
            timeframe
        )

        candles = self._as_list(
            rates
        )

        diagnostics: dict[str, Any] = {
            "symbol": context.symbol,
            "timeframe": timeframe,
            "candles": len(candles),
        }

        if not candles:
            diagnostics[
                "rejection_reason"
            ] = "rates_missing"

            return self.success(
                data=FVGState(
                    diagnostics=diagnostics,
                ).to_dict(),
                events=[],
                diagnostics=diagnostics,
            )

        state = self.service.analyze(
            rates=candles
        )

        diagnostics.update(
            state.diagnostics
        )

        diagnostics[
            "rejection_reason"
        ] = None

        data = state.to_dict()

        data[
            "symbol"
        ] = context.symbol

        data[
            "timeframe"
        ] = timeframe

        best_fvg = (
            self.service.best_active_fvg(
                state
            )
        )

        best_ifvg = (
            self.service.best_active_ifvg(
                state
            )
        )

        data[
            "best_fvg"
        ] = (
            best_fvg.to_dict()
            if best_fvg is not None
            else None
        )

        data[
            "best_ifvg"
        ] = (
            best_ifvg.to_dict()
            if best_ifvg is not None
            else None
        )

        events: list[
            dict[str, Any]
        ] = []

        for zone in (
            state.bullish_fvgs
            + state.bearish_fvgs
            + state.bullish_ifvgs
            + state.bearish_ifvgs
        ):
            event = zone.to_dict()

            event[
                "type"
            ] = zone.event_type.value

            event[
                "direction"
            ] = zone.zone_type.value

            event[
                "time"
            ] = int(
                zone.end_time
            )

            event[
                "index"
            ] = int(
                zone.end_index
            )

            events.append(
                event
            )

        return self.success(
            data=data,
            events=events,
            diagnostics=diagnostics,
        )

    def _validate_config(
        self,
    ) -> None:
        if not str(
            self.config.timeframe
        ).strip():
            raise ValueError(
                "FVG timeframe cannot be empty"
            )

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
