from __future__ import annotations

from typing import Any

from core.context import ModuleExecutionResult, StrategyContext
from core.detector import DetectorContext
from core.interfaces import POIModule
from core.strategy import ModuleRole, StrategyModuleDefinition

from concepts.order_block.detector import OrderBlockDetector


class OrderBlockPOIModule(POIModule):
    """
    Adapter:
        concepts.order_block.OrderBlockDetector
        -> Universal Strategy Engine

    Восстанавливает legacy snapshot из результатов
    StructureTrendModule + LiquiditySweepModule.
    """

    provider = "order_block_poi"
    role = ModuleRole.POI
    version = "1.0.0"

    capabilities = (
        "poi_detection",
        "order_block_detection",
        "bullish_order_block",
        "bearish_order_block",
        "order_block_quality",
        "order_block_mitigation",
    )

    dependencies = (
        ModuleRole.TREND,
        ModuleRole.LIQUIDITY,
    )

    def __init__(
        self,
        definition: StrategyModuleDefinition | None = None,
    ) -> None:
        super().__init__(definition=definition)
        self.detector = OrderBlockDetector()

    def execute(
        self,
        context: StrategyContext,
    ) -> ModuleExecutionResult:
        trend_result = context.get_result(
            role=ModuleRole.TREND,
            provider="structure_trend",
        )

        liquidity_result = context.get_result(
            role=ModuleRole.LIQUIDITY,
            provider="liquidity_sweep",
        )

        if trend_result is None:
            return self.failure(error="structure_result_missing")

        if liquidity_result is None:
            return self.failure(error="liquidity_result_missing")

        structure_data = self._extract_raw_data(trend_result.data)
        liquidity_data = self._extract_raw_data(liquidity_result.data)

        detector_context = DetectorContext(
            symbol=context.symbol,
            rates_by_timeframe=context.rates_by_timeframe,
            current_time=context.current_time,
        )

        legacy_snapshot = {
            "results": {
                "structure": {
                    "success": bool(trend_result.success),
                    "data": structure_data,
                    "events": list(trend_result.events),
                    "diagnostics": dict(trend_result.diagnostics),
                },
                "liquidity": {
                    "success": bool(liquidity_result.success),
                    "data": liquidity_data,
                    "events": list(liquidity_result.events),
                    "diagnostics": dict(liquidity_result.diagnostics),
                },
            },
            "errors": {},
        }

        result = self.detector.analyze(
            detector_context,
            legacy_snapshot,
        )

        if not result.success:
            return self.failure(
                error=result.error or "order_block_detector_failed",
                diagnostics=dict(result.diagnostics or {}),
            )

        data = dict(result.data or {})
        events = [dict(event) for event in (result.events or [])]

        best_block = data.get("best_block")
        if not isinstance(best_block, dict):
            best_block = None

        poi_found = best_block is not None
        direction = self._extract_direction(best_block)
        quality_score = self._extract_quality(best_block)

        normalized_data = {
            "poi_found": bool(poi_found),
            "poi_type": "ORDER_BLOCK" if poi_found else None,
            "provider_type": "ORDER_BLOCK" if poi_found else None,
            "direction": direction,
            "quality_score": quality_score,
            "active_zone": dict(best_block) if best_block is not None else None,
            "best_block": dict(best_block) if best_block is not None else None,
            "event_count": len(events),
            "raw": data,
        }

        diagnostics = dict(result.diagnostics or {})
        diagnostics.update(
            {
                "adapter": "OrderBlockPOIModule",
                "provider": self.provider,
                "poi_found": poi_found,
                "direction": direction,
                "quality_score": quality_score,
                "structure_bridge": True,
                "liquidity_bridge": True,
            }
        )

        return self.success(
            passed=poi_found,
            data=normalized_data,
            events=events,
            diagnostics=diagnostics,
        )

    @staticmethod
    def _extract_raw_data(
        module_data: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(module_data, dict):
            return {}

        result = dict(module_data)
        raw = module_data.get("raw")

        if isinstance(raw, dict):
            merged = dict(raw)
            merged.update(
                {
                    key: value
                    for key, value in result.items()
                    if key != "raw"
                }
            )
            return merged

        return result

    @staticmethod
    def _extract_direction(
        block: dict[str, Any] | None,
    ) -> str:
        if block is None:
            return "NEUTRAL"

        direction = str(
            block.get("block_type", block.get("direction", ""))
        ).upper()

        if direction in {"BULLISH", "BEARISH"}:
            return direction

        return "NEUTRAL"

    @staticmethod
    def _extract_quality(
        block: dict[str, Any] | None,
    ) -> float | None:
        if block is None:
            return None

        value = block.get("quality_score")
        if value is None:
            return None

        try:
            return float(value)
        except (TypeError, ValueError):
            return None