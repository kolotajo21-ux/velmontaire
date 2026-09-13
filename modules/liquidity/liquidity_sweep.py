from __future__ import annotations

from typing import Any

from core.context import (
    ModuleExecutionResult,
    StrategyContext,
)
from core.detector import (
    DetectorContext,
)
from core.interfaces import (
    LiquidityModule,
)
from core.strategy import (
    ModuleRole,
    StrategyModuleDefinition,
)

from concepts.liquidity.detector import (
    LiquidityDetector,
)


class LiquiditySweepModule(
    LiquidityModule
):
    """
    Adapter:
        concepts.liquidity.LiquidityDetector
        -> Universal Strategy Engine

    Старый LiquidityDetector зависит от Structure.
    Поэтому адаптер восстанавливает legacy snapshot
    из результата нового StructureTrendModule.
    """

    provider = "liquidity_sweep"
    role = ModuleRole.LIQUIDITY
    version = "1.0.1"

    capabilities = (
        "liquidity_detection",
        "liquidity_sweep",
        "equal_high_detection",
        "equal_low_detection",
        "pool_detection",
        "buy_side_liquidity",
        "sell_side_liquidity",
    )

    dependencies = (
        ModuleRole.TREND,
    )

    def __init__(
        self,
        definition: (
            StrategyModuleDefinition
            | None
        ) = None,
    ) -> None:
        super().__init__(
            definition=definition
        )

        self.detector = (
            LiquidityDetector()
        )

    def execute(
        self,
        context: StrategyContext,
    ) -> ModuleExecutionResult:
        selected_timeframe = self._select_available_timeframe(context)
        if selected_timeframe:
            self.detector.config.timeframe = selected_timeframe

        trend_result = context.get_result(
            role=ModuleRole.TREND,
            provider="structure_trend",
        )

        if trend_result is None:
            return self.failure(
                error="structure_result_missing",
            )

        structure_data = self._extract_structure_data(
            trend_result.data
        )

        if not structure_data:
            return self.failure(
                error="structure_data_missing",
            )

        detector_context = DetectorContext(
            symbol=context.symbol,
            rates_by_timeframe=(
                context.rates_by_timeframe
            ),
            current_time=context.current_time,
        )

        legacy_snapshot = {
            "results": {
                "structure": {
                    "success": True,
                    "data": structure_data,
                    "events": list(
                        trend_result.events
                    ),
                    "diagnostics": dict(
                        trend_result.diagnostics
                    ),
                }
            },
            "errors": {},
        }

        result = self.detector.analyze(
            detector_context,
            legacy_snapshot,
        )

        if not result.success:
            return self.failure(
                error=(
                    result.error
                    or "liquidity_detector_failed"
                ),
                diagnostics=dict(
                    result.diagnostics
                    or {}
                ),
            )

        data = dict(
            result.data
            or {}
        )

        events = [
            dict(event)
            for event in (
                result.events
                or []
            )
        ]

        last_sweep = (
            self._extract_last_sweep(
                data=data,
                events=events,
            )
        )

        sweep_found = (
            last_sweep is not None
        )

        direction = (
            self._extract_direction(
                last_sweep
            )
        )

        side = (
            self._extract_side(
                last_sweep
            )
        )

        normalized_data = {
            "sweep_found": bool(
                sweep_found
            ),
            "direction": direction,
            "side": side,
            "last_sweep": (
                dict(last_sweep)
                if last_sweep
                is not None
                else None
            ),
            "event_count": len(
                events
            ),
            "raw": data,
        }

        diagnostics = dict(
            result.diagnostics
            or {}
        )

        diagnostics.update(
            {
                "adapter": (
                    "LiquiditySweepModule"
                ),
                "provider": (
                    self.provider
                ),
                "sweep_found": (
                    sweep_found
                ),
                "direction": (
                    direction
                ),
                "side": (
                    side
                ),
                "structure_bridge": True,
            }
        )

        return self.success(
            passed=sweep_found,
            data=normalized_data,
            events=events,
            diagnostics=diagnostics,
        )

    def _select_available_timeframe(
        self,
        context: StrategyContext,
    ) -> str | None:
        """Select a configured strategy timeframe that actually has rates."""
        definition = getattr(self, "definition", None)
        parameters = dict(getattr(definition, "parameters", {}) or {})
        event_metadata = dict(parameters.get("event_metadata") or {})

        candidates: list[str] = []
        for value in (
            event_metadata.get("timeframe"),
            parameters.get("timeframe"),
            getattr(self.detector.config, "timeframe", None),
            *(getattr(context.strategy, "timeframes", []) or []),
            *context.rates_by_timeframe.keys(),
        ):
            timeframe = str(value or "").strip().upper()
            if timeframe and timeframe not in candidates:
                candidates.append(timeframe)

        for timeframe in candidates:
            rates = context.rates_by_timeframe.get(timeframe)
            if self._rates_available(rates):
                return timeframe

        return None

    @staticmethod
    def _rates_available(rates: Any) -> bool:
        if rates is None:
            return False

        empty = getattr(rates, "empty", None)
        if empty is not None:
            try:
                return not bool(empty)
            except Exception:
                return False

        try:
            return len(rates) > 0
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _extract_structure_data(
        trend_data: dict[str, Any],
    ) -> dict[str, Any]:
        raw = trend_data.get(
            "raw"
        )

        if isinstance(
            raw,
            dict,
        ):
            return dict(
                raw
            )

        return dict(
            trend_data
        )

    @staticmethod
    def _extract_last_sweep(
        *,
        data: dict[str, Any],
        events: list[
            dict[str, Any]
        ],
    ) -> dict[str, Any] | None:
        last_sweep = data.get(
            "last_sweep"
        )

        if isinstance(
            last_sweep,
            dict,
        ):
            return dict(
                last_sweep
            )

        for event in reversed(
            events
        ):
            event_type = str(
                event.get(
                    "event_type",
                    event.get(
                        "type",
                        "",
                    ),
                )
            ).upper()

            if event_type == "SWEEP":
                return dict(
                    event
                )

        return None

    @staticmethod
    def _extract_direction(
        sweep: dict[str, Any]
        | None,
    ) -> str:
        if sweep is None:
            return "NEUTRAL"

        direction = str(
            sweep.get(
                "direction",
                "",
            )
        ).upper()

        if direction in {
            "BULLISH",
            "BEARISH",
        }:
            return direction

        side = str(
            sweep.get(
                "side",
                "",
            )
        ).upper()

        if side == "BUY_SIDE":
            return "BEARISH"

        if side == "SELL_SIDE":
            return "BULLISH"

        return "NEUTRAL"

    @staticmethod
    def _extract_side(
        sweep: dict[str, Any]
        | None,
    ) -> str | None:
        if sweep is None:
            return None

        side = str(
            sweep.get(
                "side",
                "",
            )
        ).upper()

        if side in {
            "BUY_SIDE",
            "SELL_SIDE",
        }:
            return side

        return None
