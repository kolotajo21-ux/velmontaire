from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from core.detector import (
    BaseDetector,
    DetectorContext,
    DetectorResult,
)

from .analyzer import (
    SwingAnalyzer,
    SwingAnalyzerConfig,
)
from .bos import (
    BosAnalyzer,
    BosAnalyzerConfig,
)
from .choch import (
    ChochAnalyzer,
    ChochAnalyzerConfig,
)
from .classifier import (
    SwingClassifier,
    SwingClassifierConfig,
)
from .models import (
    StructureEventType,
    StructureState,
)


@dataclass(slots=True)
class StructureDetectorConfig:
    timeframe: str = "H4"

    left_bars: int = 2
    right_bars: int = 2

    allow_equal_highs: bool = False
    allow_equal_lows: bool = False

    minimum_price_distance: float = 0.0
    minimum_difference: float = 0.0
    equal_tolerance: float = 0.0

    minimum_bos_body_ratio: float = 0.45
    minimum_bos_break_ratio: float = 0.10
    require_first_close_beyond: bool = True
    use_last_closed_candle: bool = True

    update_bias_after_choch: bool = True
    range_uses_first_break_as_bias: bool = True

    minimum_candles: int = 20


class StructureDetector(BaseDetector):
    """
    Анализирует рыночную структуру.

    Возможности:
    - Swing High / Swing Low;
    - HH / HL / LH / LL;
    - предварительный тренд;
    - bullish / bearish BOS;
    - bullish / bearish CHoCH;
    - финальный market bias.
    """

    name = "structure"
    version = "1.2.0"
    dependencies: tuple[str, ...] = ()

    def __init__(
        self,
        config: StructureDetectorConfig | None = None,
    ) -> None:
        self.config = (
            config
            if config is not None
            else StructureDetectorConfig()
        )

        self._validate_config()

        self.analyzer = SwingAnalyzer(
            SwingAnalyzerConfig(
                left_bars=self.config.left_bars,
                right_bars=self.config.right_bars,
                allow_equal_highs=(
                    self.config.allow_equal_highs
                ),
                allow_equal_lows=(
                    self.config.allow_equal_lows
                ),
                minimum_price_distance=(
                    self.config.minimum_price_distance
                ),
            )
        )

        self.classifier = SwingClassifier(
            SwingClassifierConfig(
                minimum_difference=(
                    self.config.minimum_difference
                ),
                equal_tolerance=(
                    self.config.equal_tolerance
                ),
            )
        )

        self.bos_analyzer = BosAnalyzer(
            BosAnalyzerConfig(
                minimum_body_ratio=(
                    self.config.minimum_bos_body_ratio
                ),
                minimum_break_ratio=(
                    self.config.minimum_bos_break_ratio
                ),
                require_first_close_beyond=(
                    self.config.require_first_close_beyond
                ),
                use_last_closed_candle=(
                    self.config.use_last_closed_candle
                ),
            )
        )

        self.choch_analyzer = ChochAnalyzer(
            ChochAnalyzerConfig(
                update_bias_after_choch=(
                    self.config.update_bias_after_choch
                ),
                range_uses_first_break_as_bias=(
                    self.config
                    .range_uses_first_break_as_bias
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

        candles = self._as_list(
            context.get_rates(
                timeframe
            )
        )

        diagnostics: dict[str, Any] = {
            "symbol": context.symbol,
            "timeframe": timeframe,
            "candles": len(candles),
            "minimum_candles": (
                self.config.minimum_candles
            ),
        }

        if len(candles) < self.config.minimum_candles:
            return self.failure(
                error="not_enough_structure_data",
                diagnostics=diagnostics,
            )

        swings = self.analyzer.analyze(
            candles
        )

        classified_swings = (
            self.classifier.classify(
                swings
            )
        )

        inferred_direction = (
            self.classifier.infer_direction(
                classified_swings
            )
        )

        raw_break_events = (
            self.bos_analyzer.analyze(
                rates=candles,
                swings=classified_swings,
            )
        )

        structure_events, final_direction = (
            self.choch_analyzer.classify(
                break_events=raw_break_events,
                initial_direction=inferred_direction,
            )
        )

        bos_events = [
            event
            for event in structure_events
            if event.event_type
            == StructureEventType.BOS
        ]

        choch_events = [
            event
            for event in structure_events
            if event.event_type
            == StructureEventType.CHOCH
        ]

        last_bos = (
            bos_events[-1]
            if bos_events
            else None
        )

        last_choch = (
            choch_events[-1]
            if choch_events
            else None
        )

        state = StructureState(
            trend=final_direction,
            swings=classified_swings,
            events=structure_events,
            last_bos=last_bos,
            last_choch=last_choch,
        )

        diagnostics.update(
            {
                "swing_count": len(
                    classified_swings
                ),
                "high_count": sum(
                    1
                    for swing in classified_swings
                    if swing.swing_type.value
                    == "HIGH"
                ),
                "low_count": sum(
                    1
                    for swing in classified_swings
                    if swing.swing_type.value
                    == "LOW"
                ),
                "raw_break_count": len(
                    raw_break_events
                ),
                "bos_count": len(
                    bos_events
                ),
                "choch_count": len(
                    choch_events
                ),
                "bullish_bos_count": sum(
                    1
                    for event in bos_events
                    if event.direction.value
                    == "BULLISH"
                ),
                "bearish_bos_count": sum(
                    1
                    for event in bos_events
                    if event.direction.value
                    == "BEARISH"
                ),
                "bullish_choch_count": sum(
                    1
                    for event in choch_events
                    if event.direction.value
                    == "BULLISH"
                ),
                "bearish_choch_count": sum(
                    1
                    for event in choch_events
                    if event.direction.value
                    == "BEARISH"
                ),
                "inferred_trend": (
                    inferred_direction.value
                ),
                "final_trend": (
                    final_direction.value
                ),
            }
        )

        events: list[
            dict[str, Any]
        ] = []

        for swing in classified_swings:
            point_type = (
                swing.point_type.value
            )

            if point_type == "UNKNOWN":
                continue

            events.append(
                {
                    "event_type": (
                        "STRUCTURE_POINT"
                    ),
                    "type": point_type,
                    "direction": (
                        "BULLISH"
                        if point_type
                        in {"HH", "HL"}
                        else "BEARISH"
                    ),
                    "index": int(
                        swing.index
                    ),
                    "time": int(
                        swing.time
                    ),
                    "price": float(
                        swing.price
                    ),
                    "swing_type": (
                        swing.swing_type.value
                    ),
                    "point_type": (
                        point_type
                    ),
                }
            )

        events.extend(
            event.to_dict()
            for event in structure_events
        )

        data = state.to_dict()

        data["timeframe"] = timeframe
        data["symbol"] = context.symbol
        data["market_bias"] = (
            final_direction.value
        )

        data["latest_swing"] = (
            classified_swings[-1].to_dict()
            if classified_swings
            else None
        )

        data["bos_events"] = [
            event.to_dict()
            for event in bos_events
        ]

        data["choch_events"] = [
            event.to_dict()
            for event in choch_events
        ]

        data["raw_break_events"] = [
            event.to_dict()
            for event in raw_break_events
        ]

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
                "Structure timeframe cannot be empty"
            )

        if self.config.minimum_candles < 5:
            raise ValueError(
                "minimum_candles must be at least 5"
            )

        if self.config.left_bars < 1:
            raise ValueError(
                "left_bars must be at least 1"
            )

        if self.config.right_bars < 1:
            raise ValueError(
                "right_bars must be at least 1"
            )

        if not (
            0.0
            <= self.config.minimum_bos_body_ratio
            <= 1.0
        ):
            raise ValueError(
                "minimum_bos_body_ratio must "
                "be between 0 and 1"
            )

        if self.config.minimum_bos_break_ratio < 0:
            raise ValueError(
                "minimum_bos_break_ratio "
                "cannot be negative"
            )

    @staticmethod
    def _as_list(
        rates: Any,
    ) -> list[Any]:
        if rates is None:
            return []

        # pandas.DataFrame: list(df) returns column names, not candle rows.
        # Convert DataFrame-like objects explicitly to record dictionaries.
        if hasattr(rates, "to_dict"):
            try:
                rows = rates.to_dict("records")
                if isinstance(rows, list):
                    return [dict(row) for row in rows]
            except Exception:
                pass

        if isinstance(rates, (list, tuple)):
            try:
                return [
                    dict(row) if isinstance(row, Mapping) else row
                    for row in rates
                ]
            except Exception:
                return list(rates)

        try:
            return list(rates)
        except TypeError:
            return []