from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from core.detector import (
    BaseDetector,
    DetectorContext,
    DetectorResult,
)

from .models import (
    OrderBlockState,
)
from .services import (
    OrderBlockService,
    OrderBlockServiceConfig,
)


@dataclass(slots=True)
class OrderBlockDetectorConfig:
    timeframe: str = "H4"

    minimum_quality: float = 70.0

    require_liquidity_sweep: bool = True
    require_bos: bool = True

    use_last_closed_candle: bool = True

    search_bars_before_bos: int = 12
    minimum_candle_body_ratio: float = 0.0

    require_direction_alignment: bool = True

    partial_fill_threshold: float = 0.25
    mitigated_fill_threshold: float = 0.75
    invalidate_on_close_through: bool = True


class OrderBlockDetector(BaseDetector):

    name = "order_block"
    version = "3.0.0"

    dependencies = (
        "structure",
        "liquidity",
    )

    def __init__(
        self,
        config: OrderBlockDetectorConfig | None = None,
    ) -> None:

        self.config = (
            config
            if config is not None
            else OrderBlockDetectorConfig()
        )

        self.service = OrderBlockService(
            OrderBlockServiceConfig(
                minimum_quality=(
                    self.config.minimum_quality
                ),
                search_bars_before_bos=(
                    self.config.search_bars_before_bos
                ),
                minimum_candle_body_ratio=(
                    self.config.minimum_candle_body_ratio
                ),
                require_sweep_before_bos=(
                    self.config.require_liquidity_sweep
                ),
                require_direction_alignment=(
                    self.config.require_direction_alignment
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
                use_last_closed_candle=(
                    self.config.use_last_closed_candle
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

        structure = self._result_data(
            snapshot=snapshot,
            detector_name="structure",
        )

        liquidity = self._result_data(
            snapshot=snapshot,
            detector_name="liquidity",
        )

        rates = context.get_rates(
            timeframe
        )

        last_bos = self._last_event(
            data=structure,
            direct_key="last_bos",
            event_type="BOS",
        )

        last_sweep = self._last_event(
            data=liquidity,
            direct_key="last_sweep",
            event_type="SWEEP",
        )

        diagnostics: dict[str, Any] = {
            "symbol": context.symbol,
            "timeframe": timeframe,
            "structure_loaded": bool(
                structure
            ),
            "liquidity_loaded": bool(
                liquidity
            ),
            "bos_found": (
                last_bos is not None
            ),
            "sweep_found": (
                last_sweep is not None
            ),
            "require_bos": bool(
                self.config.require_bos
            ),
            "require_liquidity_sweep": bool(
                self.config.require_liquidity_sweep
            ),
        }

        if (
            self.config.require_bos
            and last_bos is None
        ):
            diagnostics[
                "rejection_reason"
            ] = "bos_missing"

            return self.success(
                data=OrderBlockState().to_dict(),
                events=[],
                diagnostics=diagnostics,
            )

        if (
            self.config.require_liquidity_sweep
            and last_sweep is None
        ):
            diagnostics[
                "rejection_reason"
            ] = "liquidity_sweep_missing"

            return self.success(
                data=OrderBlockState().to_dict(),
                events=[],
                diagnostics=diagnostics,
            )

        evaluation = self.service.evaluate(
            rates=rates,
            bos=last_bos,
            sweep=last_sweep,
        )

        diagnostics.update(
            evaluation.diagnostics
        )

        diagnostics[
            "accepted"
        ] = bool(
            evaluation.accepted
        )

        diagnostics[
            "rejection_reason"
        ] = evaluation.reason

        if not evaluation.accepted:
            data = (
                evaluation.state.to_dict()
                if evaluation.state is not None
                else OrderBlockState().to_dict()
            )

            data[
                "symbol"
            ] = context.symbol

            data[
                "timeframe"
            ] = timeframe

            return self.success(
                data=data,
                events=[],
                diagnostics=diagnostics,
            )

        block = evaluation.block

        if block is None:
            diagnostics[
                "accepted"
            ] = False

            diagnostics[
                "rejection_reason"
            ] = "accepted_without_block"

            return self.success(
                data=OrderBlockState().to_dict(),
                events=[],
                diagnostics=diagnostics,
            )

        data = evaluation.state.to_dict()

        data[
            "symbol"
        ] = context.symbol

        data[
            "timeframe"
        ] = timeframe

        data[
            "best_block"
        ] = block.to_dict()

        event = {
            "event_type": "ORDER_BLOCK",
            "type": block.block_type.value,
            "direction": block.block_type.value,
            "time": int(
                block.time
            ),
            "index": int(
                block.index
            ),
            "high": float(
                block.high
            ),
            "low": float(
                block.low
            ),
            "quality_score": float(
                block.quality_score
            ),
            "mitigation_status": (
                block.mitigation.status.value
            ),
            "filled_percent": float(
                block.mitigation.filled_percent
            ),
            "active": bool(
                block.active
            ),
            "block_id": block.block_id,
        }

        return self.success(
            data=data,
            events=[
                event
            ],
            diagnostics=diagnostics,
        )

    @staticmethod
    def _result_data(
        *,
        snapshot: Mapping[str, Any],
        detector_name: str,
    ) -> dict[str, Any]:

        result = (
            snapshot
            .get("results", {})
            .get(detector_name, {})
        )

        if not isinstance(
            result,
            Mapping,
        ):
            return {}

        data = result.get(
            "data",
            {}
        )

        if not isinstance(
            data,
            Mapping,
        ):
            return {}

        return dict(
            data
        )

    @staticmethod
    def _last_event(
        *,
        data: Mapping[str, Any],
        direct_key: str,
        event_type: str,
    ) -> dict[str, Any] | None:

        direct = data.get(
            direct_key
        )

        if isinstance(
            direct,
            Mapping,
        ):
            return dict(
                direct
            )

        events = data.get(
            "events",
            [],
        )

        if not isinstance(
            events,
            list,
        ):
            return None

        filtered = [
            event
            for event in events
            if (
                isinstance(
                    event,
                    Mapping,
                )
                and str(
                    event.get(
                        "event_type",
                        "",
                    )
                ).upper()
                == event_type.upper()
            )
        ]

        if not filtered:
            return None

        return dict(
            filtered[-1]
        )