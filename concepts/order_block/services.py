from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .finder import (
    OrderBlockFinder,
    OrderBlockFinderConfig,
)
from .mitigation import (
    MitigationAnalyzer,
    MitigationConfig,
)
from .models import (
    OrderBlock,
    OrderBlockState,
    OrderBlockType,
)
from .scoring import (
    OrderBlockScore,
    OrderBlockScorer,
)


@dataclass(slots=True)
class OrderBlockServiceConfig:
    minimum_quality: float = 70.0

    search_bars_before_bos: int = 12
    minimum_candle_body_ratio: float = 0.0

    require_sweep_before_bos: bool = True
    require_direction_alignment: bool = True

    partial_fill_threshold: float = 0.25
    mitigated_fill_threshold: float = 0.75
    invalidate_on_close_through: bool = True
    use_last_closed_candle: bool = True


@dataclass(slots=True)
class OrderBlockEvaluation:
    accepted: bool

    reason: str | None = None

    block: OrderBlock | None = None
    score: OrderBlockScore | None = None
    state: OrderBlockState = field(
        default_factory=OrderBlockState
    )

    diagnostics: dict[str, Any] = field(
        default_factory=dict
    )


class OrderBlockService:
    """
    Высокоуровневый сервис Order Block.

    Он объединяет:
    - поиск кандидата;
    - scoring;
    - mitigation;
    - фильтрацию по качеству;
    - построение OrderBlockState.

    Detector должен только получить данные,
    вызвать этот сервис и вернуть результат.
    """

    def __init__(
        self,
        config: OrderBlockServiceConfig | None = None,
    ) -> None:
        self.config = (
            config
            if config is not None
            else OrderBlockServiceConfig()
        )

        self._validate_config()

        self.finder = OrderBlockFinder(
            OrderBlockFinderConfig(
                search_bars_before_bos=(
                    self.config.search_bars_before_bos
                ),
                require_sweep_before_bos=(
                    self.config.require_sweep_before_bos
                ),
                require_direction_alignment=(
                    self.config.require_direction_alignment
                ),
                minimum_candle_body_ratio=(
                    self.config.minimum_candle_body_ratio
                ),
            )
        )

        self.scorer = OrderBlockScorer()

        self.mitigation = MitigationAnalyzer(
            MitigationConfig(
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

    def evaluate(
        self,
        *,
        rates: Any,
        bos: Mapping[str, Any] | None,
        sweep: Mapping[str, Any] | None,
    ) -> OrderBlockEvaluation:
        candles = self._as_list(rates)

        diagnostics: dict[str, Any] = {
            "candles": len(candles),
            "bos_available": bos is not None,
            "sweep_available": sweep is not None,
        }

        if not candles:
            return OrderBlockEvaluation(
                accepted=False,
                reason="rates_missing",
                diagnostics=diagnostics,
            )

        block = self.finder.find(
            rates=candles,
            bos=bos,
            sweep=sweep,
        )

        if block is None:
            return OrderBlockEvaluation(
                accepted=False,
                reason="order_block_not_found",
                diagnostics=diagnostics,
            )

        score = self._score_block(
            block=block,
            bos=bos,
            sweep=sweep,
            candles=candles,
        )

        block.quality_score = float(
            score.total
        )

        block.metadata[
            "score"
        ] = score.to_dict()

        diagnostics.update(
            {
                "block_id": block.block_id,
                "quality_score": float(
                    block.quality_score
                ),
                "minimum_quality": float(
                    self.config.minimum_quality
                ),
            }
        )

        if (
            block.quality_score
            < self.config.minimum_quality
        ):
            return OrderBlockEvaluation(
                accepted=False,
                reason="quality_score_too_low",
                block=block,
                score=score,
                diagnostics=diagnostics,
            )

        block = self.mitigation.update(
            rates=candles,
            block=block,
        )

        diagnostics.update(
            {
                "mitigation_status": (
                    block.mitigation.status.value
                ),
                "filled_percent": float(
                    block.mitigation.filled_percent
                ),
                "touch_count": int(
                    block.mitigation.touch_count
                ),
                "active": bool(
                    block.active
                ),
            }
        )

        if not block.active:
            return OrderBlockEvaluation(
                accepted=False,
                reason=(
                    block.mitigation.status.value.lower()
                ),
                block=block,
                score=score,
                diagnostics=diagnostics,
            )

        state = self._build_state(
            block
        )

        return OrderBlockEvaluation(
            accepted=True,
            reason=None,
            block=block,
            score=score,
            state=state,
            diagnostics=diagnostics,
        )

    def _score_block(
        self,
        *,
        block: OrderBlock,
        bos: Mapping[str, Any] | None,
        sweep: Mapping[str, Any] | None,
        candles: list[Any],
    ) -> OrderBlockScore:
        body_ratio = self._safe_float(
            block.metadata.get(
                "body_ratio",
                0.0,
            )
        )

        bos_body_ratio = self._safe_float(
            (
                bos or {}
            ).get(
                "body_ratio",
                0.0,
            )
        )

        bos_break_ratio = self._safe_float(
            (
                bos or {}
            ).get(
                "break_ratio",
                0.0,
            )
        )

        sweep_quality = self._safe_float(
            (
                sweep or {}
            ).get(
                "quality_score",
                0.0,
            )
        )

        bars_to_bos = int(
            block.metadata.get(
                "bars_to_bos",
                0,
            )
            or 0
        )

        score = OrderBlockScore(
            impulse=self._scale_0_100(
                bos_body_ratio,
                target=0.80,
            ),
            body=self._scale_0_100(
                body_ratio,
                target=0.70,
            ),
            displacement=self._scale_0_100(
                bos_break_ratio,
                target=0.30,
            ),
            liquidity=max(
                0.0,
                min(
                    sweep_quality,
                    100.0,
                ),
            ),
            freshness=max(
                0.0,
                min(
                    100.0,
                    100.0
                    - max(
                        bars_to_bos - 1,
                        0,
                    )
                    * 10.0,
                ),
            ),
            mitigation=100.0,
            reaction=self._reaction_score(
                block=block,
                candles=candles,
            ),
            metadata={
                "bos_body_ratio": float(
                    bos_body_ratio
                ),
                "bos_break_ratio": float(
                    bos_break_ratio
                ),
                "ob_body_ratio": float(
                    body_ratio
                ),
                "bars_to_bos": int(
                    bars_to_bos
                ),
                "sweep_quality": float(
                    sweep_quality
                ),
            },
        )

        return self.scorer.calculate(
            score
        )

    def _reaction_score(
        self,
        *,
        block: OrderBlock,
        candles: list[Any],
    ) -> float:
        impulse_index = int(
            block.impulse_index
        )

        if (
            impulse_index < 0
            or impulse_index >= len(candles)
        ):
            return 0.0

        candle = candles[
            impulse_index
        ]

        open_price = self._field_float(
            candle,
            "open",
        )
        close_price = self._field_float(
            candle,
            "close",
        )
        high = self._field_float(
            candle,
            "high",
        )
        low = self._field_float(
            candle,
            "low",
        )

        candle_range = (
            high - low
        )

        if candle_range <= 0:
            return 0.0

        body_ratio = (
            abs(
                close_price
                - open_price
            )
            / candle_range
        )

        return self._scale_0_100(
            body_ratio,
            target=0.80,
        )

    @staticmethod
    def _build_state(
        block: OrderBlock,
    ) -> OrderBlockState:
        if (
            block.block_type
            == OrderBlockType.BULLISH
        ):
            return OrderBlockState(
                bullish_blocks=[
                    block
                ],
                bearish_blocks=[],
                last_bullish=block,
                last_bearish=None,
            )

        return OrderBlockState(
            bullish_blocks=[],
            bearish_blocks=[
                block
            ],
            last_bullish=None,
            last_bearish=block,
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
            self.config.search_bars_before_bos
            < 1
        ):
            raise ValueError(
                "search_bars_before_bos "
                "must be at least 1"
            )

    @staticmethod
    def _scale_0_100(
        value: float,
        *,
        target: float,
    ) -> float:
        if target <= 0:
            return 0.0

        return round(
            max(
                0.0,
                min(
                    value / target,
                    1.0,
                ),
            )
            * 100.0,
            2,
        )

    @staticmethod
    def _safe_float(
        value: Any,
    ) -> float:
        try:
            return float(value)
        except (
            TypeError,
            ValueError,
        ):
            return 0.0

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
    def _field_float(
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