from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from core.detector import (
    BaseDetector,
    DetectorContext,
    DetectorResult,
)

from concepts.structure.models import (
    StructurePointType,
    SwingPoint,
    SwingType,
)

from .equal_levels import (
    EqualLevelsAnalyzer,
    EqualLevelsConfig,
)
from .models import (
    LiquidityEventType,
    LiquidityState,
)
from .pools import (
    LiquidityPoolBuilder,
    LiquidityPoolConfig,
)
from .sweep import (
    LiquiditySweepAnalyzer,
    LiquiditySweepConfig,
)


@dataclass(slots=True)
class LiquidityDetectorConfig:
    timeframe: str = "H4"

    absolute_tolerance: float = 0.00020
    relative_tolerance: float = 0.0

    minimum_bars_between: int = 3
    maximum_bars_between: int = 200
    minimum_touches: int = 2

    minimum_pool_strength: float = 0.0
    merge_price_tolerance: float = 0.00020
    merge_time_distance: int = 100

    minimum_penetration: float = 0.0
    minimum_penetration_ratio: float = 0.05
    minimum_reclaim_ratio: float = 0.0

    require_first_touch: bool = True
    use_last_closed_candle: bool = True


class LiquidityDetector(BaseDetector):
    """
    Полный модуль ликвидности.

    Использует результат StructureDetector:
    - берёт подтверждённые swing points;
    - находит EQH/EQL;
    - строит liquidity pools;
    - определяет Sweep и Run;
    - возвращает LiquidityState.
    """

    name = "liquidity"
    version = "1.0.0"
    dependencies: tuple[str, ...] = (
        "structure",
    )

    def __init__(
        self,
        config: LiquidityDetectorConfig | None = None,
    ) -> None:
        self.config = (
            config
            if config is not None
            else LiquidityDetectorConfig()
        )

        self._validate_config()

        self.equal_levels_analyzer = (
            EqualLevelsAnalyzer(
                EqualLevelsConfig(
                    absolute_tolerance=(
                        self.config
                        .absolute_tolerance
                    ),
                    relative_tolerance=(
                        self.config
                        .relative_tolerance
                    ),
                    minimum_bars_between=(
                        self.config
                        .minimum_bars_between
                    ),
                    maximum_bars_between=(
                        self.config
                        .maximum_bars_between
                    ),
                    minimum_touches=(
                        self.config
                        .minimum_touches
                    ),
                )
            )
        )

        self.pool_builder = (
            LiquidityPoolBuilder(
                LiquidityPoolConfig(
                    minimum_strength=(
                        self.config
                        .minimum_pool_strength
                    ),
                    merge_price_tolerance=(
                        self.config
                        .merge_price_tolerance
                    ),
                    merge_time_distance=(
                        self.config
                        .merge_time_distance
                    ),
                )
            )
        )

        self.sweep_analyzer = (
            LiquiditySweepAnalyzer(
                LiquiditySweepConfig(
                    minimum_penetration=(
                        self.config
                        .minimum_penetration
                    ),
                    minimum_penetration_ratio=(
                        self.config
                        .minimum_penetration_ratio
                    ),
                    minimum_reclaim_ratio=(
                        self.config
                        .minimum_reclaim_ratio
                    ),
                    require_first_touch=(
                        self.config
                        .require_first_touch
                    ),
                    use_last_closed_candle=(
                        self.config
                        .use_last_closed_candle
                    ),
                )
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

        structure_data = snapshot.get(
            "results",
            {},
        ).get(
            "structure",
            {},
        ).get(
            "data",
            {},
        )

        swings_data = structure_data.get(
            "swings",
            [],
        )

        diagnostics: dict[str, Any] = {
            "symbol": context.symbol,
            "timeframe": timeframe,
            "candles": len(candles),
            "structure_swings": len(
                swings_data
            ),
        }

        if not candles:
            return self.failure(
                error="liquidity_rates_missing",
                diagnostics=diagnostics,
            )

        if not swings_data:
            return self.failure(
                error="structure_swings_missing",
                diagnostics=diagnostics,
            )

        swings = [
            self._swing_from_dict(
                item
            )
            for item in swings_data
            if isinstance(
                item,
                Mapping,
            )
        ]

        swings = [
            swing
            for swing in swings
            if swing is not None
        ]

        equal_highs, equal_lows = (
            self.equal_levels_analyzer.analyze(
                swings
            )
        )

        pools = self.pool_builder.build(
            equal_highs=equal_highs,
            equal_lows=equal_lows,
        )

        liquidity_events = (
            self.sweep_analyzer.analyze(
                rates=candles,
                pools=pools,
            )
        )

        sweep_events = [
            event
            for event in liquidity_events
            if event.event_type
            == LiquidityEventType.SWEEP
        ]

        run_events = [
            event
            for event in liquidity_events
            if event.event_type
            == LiquidityEventType.RUN
        ]

        swept_pool_ids = {
            event.source_pool_id
            for event in liquidity_events
            if (
                event.source_pool_id
                is not None
            )
        }

        for pool in pools:
            if pool.pool_id in swept_pool_ids:
                pool.swept = True
                pool.active = False

        last_sweep = (
            sweep_events[-1]
            if sweep_events
            else None
        )

        last_run = (
            run_events[-1]
            if run_events
            else None
        )

        state = LiquidityState(
            equal_highs=equal_highs,
            equal_lows=equal_lows,
            pools=pools,
            events=liquidity_events,
            last_sweep=last_sweep,
            last_run=last_run,
        )

        diagnostics.update(
            {
                "usable_swings": len(
                    swings
                ),
                "equal_highs": len(
                    equal_highs
                ),
                "equal_lows": len(
                    equal_lows
                ),
                "pool_count": len(
                    pools
                ),
                "sweep_count": len(
                    sweep_events
                ),
                "run_count": len(
                    run_events
                ),
            }
        )

        data = state.to_dict()

        data["symbol"] = context.symbol
        data["timeframe"] = timeframe

        events: list[
            dict[str, Any]
        ] = []

        events.extend(
            {
                "event_type": (
                    level.level_type.value
                ),
                "type": (
                    level.level_type.value
                ),
                "side": (
                    level.side.value
                ),
                "direction": "NEUTRAL",
                "time": int(
                    level.second_time
                ),
                "index": int(
                    level.second_index
                ),
                "price": float(
                    level.price
                ),
                "level_id": (
                    level.level_id
                ),
            }
            for level in [
                *equal_highs,
                *equal_lows,
            ]
        )

        events.extend(
            event.to_dict()
            for event in liquidity_events
        )

        return self.success(
            data=data,
            events=events,
            diagnostics=diagnostics,
        )

    @staticmethod
    def _swing_from_dict(
        item: Mapping[str, Any],
    ) -> SwingPoint | None:
        try:
            swing_type = SwingType(
                str(
                    item.get(
                        "swing_type",
                        "",
                    )
                ).upper()
            )

            point_type_value = str(
                item.get(
                    "point_type",
                    "UNKNOWN",
                )
            ).upper()

            try:
                point_type = (
                    StructurePointType(
                        point_type_value
                    )
                )
            except ValueError:
                point_type = (
                    StructurePointType.UNKNOWN
                )

            return SwingPoint(
                index=int(
                    item.get(
                        "index",
                        0,
                    )
                ),
                time=int(
                    item.get(
                        "time",
                        0,
                    )
                ),
                price=float(
                    item.get(
                        "price",
                        0.0,
                    )
                ),
                swing_type=swing_type,
                point_type=point_type,
                strength=int(
                    item.get(
                        "strength",
                        1,
                    )
                ),
                confirmed=bool(
                    item.get(
                        "confirmed",
                        True,
                    )
                ),
                metadata=dict(
                    item.get(
                        "metadata",
                        {},
                    )
                ),
            )

        except (
            TypeError,
            ValueError,
        ):
            return None

    def _validate_config(
        self,
    ) -> None:
        if not str(
            self.config.timeframe
        ).strip():
            raise ValueError(
                "Liquidity timeframe "
                "cannot be empty"
            )

        if (
            self.config.absolute_tolerance
            < 0
        ):
            raise ValueError(
                "absolute_tolerance "
                "cannot be negative"
            )

        if (
            self.config.minimum_bars_between
            < 1
        ):
            raise ValueError(
                "minimum_bars_between "
                "must be at least 1"
            )

        if (
            self.config.maximum_bars_between
            < self.config.minimum_bars_between
        ):
            raise ValueError(
                "maximum_bars_between cannot "
                "be smaller than "
                "minimum_bars_between"
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
