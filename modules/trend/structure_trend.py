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
    TrendModule,
)
from core.strategy import (
    ModuleRole,
    StrategyModuleDefinition,
)

from concepts.structure.detector import (
    StructureDetector,
)


class StructureTrendModule(TrendModule):
    """
    Adapter:
        concepts.structure.StructureDetector
        -> Universal Strategy Engine

    Старый Structure Engine не переписываем.
    Этот модуль только приводит его результат
    к новому ModuleExecutionResult.
    """

    provider = "structure_trend"
    role = ModuleRole.TREND
    version = "1.0.0"

    capabilities = (
        "trend_detection",
        "market_structure",
        "bos_detection",
        "choch_detection",
        "direction_bias",
    )

    dependencies = ()

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
            StructureDetector()
        )

    def execute(
        self,
        context: StrategyContext,
    ) -> ModuleExecutionResult:
        detector_context = (
            DetectorContext(
                symbol=context.symbol,
                rates_by_timeframe=(
                    context.rates_by_timeframe
                ),
                current_time=(
                    context.current_time
                ),
            )
        )

        result = self.detector.analyze(
            detector_context,
            {},
        )

        if not result.success:
            return self.failure(
                error=(
                    result.error
                    or "structure_detector_failed"
                ),
                diagnostics=dict(
                    result.diagnostics
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

        direction = self._extract_direction(
            data=data,
            events=events,
        )

        passed = (
            direction
            in {
                "BULLISH",
                "BEARISH",
            }
        )

        normalized_data = {
            "direction": direction,
            "raw": data,
            "event_count": len(
                events
            ),
        }

        diagnostics = dict(
            result.diagnostics
            or {}
        )

        diagnostics.update(
            {
                "adapter": (
                    "StructureTrendModule"
                ),
                "provider": (
                    self.provider
                ),
                "direction": (
                    direction
                ),
            }
        )

        return self.success(
            passed=passed,
            data=normalized_data,
            events=events,
            diagnostics=diagnostics,
        )

    @staticmethod
    def _extract_direction(
        *,
        data: dict[str, Any],
        events: list[
            dict[str, Any]
        ],
    ) -> str:
        candidates = (
            "direction",
            "trend",
            "bias",
            "structure_direction",
        )

        for key in candidates:
            value = data.get(
                key
            )

            if value is None:
                continue

            normalized = (
                str(value)
                .upper()
                .strip()
            )

            if normalized in {
                "BULLISH",
                "BEARISH",
            }:
                return normalized

        last_bos = data.get(
            "last_bos"
        )

        if isinstance(
            last_bos,
            dict,
        ):
            direction = str(
                last_bos.get(
                    "direction",
                    "",
                )
            ).upper()

            if direction in {
                "BULLISH",
                "BEARISH",
            }:
                return direction

        last_choch = data.get(
            "last_choch"
        )

        if isinstance(
            last_choch,
            dict,
        ):
            direction = str(
                last_choch.get(
                    "direction",
                    "",
                )
            ).upper()

            if direction in {
                "BULLISH",
                "BEARISH",
            }:
                return direction

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

            if event_type not in {
                "BOS",
                "CHOCH",
            }:
                continue

            direction = str(
                event.get(
                    "direction",
                    "",
                )
            ).upper()

            if direction in {
                "BULLISH",
                "BEARISH",
            }:
                return direction

        return "NEUTRAL"