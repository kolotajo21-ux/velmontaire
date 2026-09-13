from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .context import (
    ModuleExecutionResult,
    StrategyContext,
)
from .strategy import (
    ModuleRole,
    StrategyModuleDefinition,
)


@dataclass(slots=True)
class POICandidate:
    provider: str
    direction: str

    quality_score: float
    provider_priority: int

    poi_type: str | None = None

    active_zone: dict[str, Any] = field(
        default_factory=dict
    )

    source_result: (
        ModuleExecutionResult
        | None
    ) = None

    score: float = 0.0

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "direction": self.direction,
            "quality_score": float(
                self.quality_score
            ),
            "provider_priority": int(
                self.provider_priority
            ),
            "poi_type": self.poi_type,
            "active_zone": dict(
                self.active_zone
            ),
            "score": float(
                self.score
            ),
            "metadata": dict(
                self.metadata
            ),
        }


@dataclass(slots=True)
class POISelectionResult:
    selected: POICandidate | None

    candidates: list[
        POICandidate
    ] = field(
        default_factory=list
    )

    rejected: list[
        dict[str, Any]
    ] = field(
        default_factory=list
    )

    diagnostics: dict[
        str,
        Any,
    ] = field(
        default_factory=dict
    )

    @property
    def found(self) -> bool:
        return self.selected is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "found": self.found,
            "selected": (
                self.selected.to_dict()
                if self.selected
                is not None
                else None
            ),
            "candidates": [
                candidate.to_dict()
                for candidate
                in self.candidates
            ],
            "rejected": [
                dict(item)
                for item in self.rejected
            ],
            "diagnostics": dict(
                self.diagnostics
            ),
        }


class POISelector:
    """
    Универсальный selector для нескольких POI provider'ов.

    Базовый алгоритм:
    1. Берёт все результаты role=POI.
    2. Оставляет только success=True и poi_found=True.
    3. При необходимости фильтрует по направлению Trend.
    4. Нормализует quality.
    5. Учитывает provider priority из StrategyDefinition.
    6. Выбирает максимальный итоговый score.
    """

    def __init__(
        self,
        *,
        require_trend_alignment: bool = False,
        quality_weight: float = 1.0,
        priority_weight: float = 0.10,
    ) -> None:
        self.require_trend_alignment = bool(
            require_trend_alignment
        )

        self.quality_weight = float(
            quality_weight
        )

        self.priority_weight = float(
            priority_weight
        )

    def select(
        self,
        context: StrategyContext,
    ) -> POISelectionResult:
        trend_direction = (
            self._trend_direction(
                context
            )
        )

        definitions = (
            self._poi_definitions(
                context
            )
        )

        poi_results = (
            context.results_by_role(
                ModuleRole.POI
            )
        )

        candidates: list[
            POICandidate
        ] = []

        rejected: list[
            dict[str, Any]
        ] = []

        for result in poi_results:
            candidate, reason = (
                self._build_candidate(
                    result=result,
                    definitions=definitions,
                    trend_direction=(
                        trend_direction
                    ),
                )
            )

            if candidate is None:
                rejected.append(
                    {
                        "provider": (
                            result.provider
                        ),
                        "reason": (
                            reason
                            or "rejected"
                        ),
                    }
                )
                continue

            candidates.append(
                candidate
            )

        candidates.sort(
            key=lambda item: (
                item.score,
                item.quality_score,
                -item.provider_priority,
                item.provider,
            ),
            reverse=True,
        )

        selected = (
            candidates[0]
            if candidates
            else None
        )

        if selected is not None:
            context.put(
                "active_poi",
                selected.to_dict(),
            )

        diagnostics = {
            "trend_direction": (
                trend_direction
            ),
            "require_trend_alignment": (
                self.require_trend_alignment
            ),
            "poi_results": len(
                poi_results
            ),
            "candidate_count": len(
                candidates
            ),
            "rejected_count": len(
                rejected
            ),
            "selected_provider": (
                selected.provider
                if selected
                is not None
                else None
            ),
        }

        return POISelectionResult(
            selected=selected,
            candidates=candidates,
            rejected=rejected,
            diagnostics=diagnostics,
        )

    def _build_candidate(
        self,
        *,
        result: ModuleExecutionResult,
        definitions: dict[
            str,
            StrategyModuleDefinition,
        ],
        trend_direction: str,
    ) -> tuple[
        POICandidate | None,
        str | None,
    ]:
        if not result.success:
            return (
                None,
                "module_failed",
            )

        data = dict(
            result.data
            or {}
        )

        poi_found = bool(
            data.get(
                "poi_found",
                False,
            )
        )

        if not poi_found:
            return (
                None,
                "poi_not_found",
            )

        active_zone = data.get(
            "active_zone"
        )

        if not isinstance(
            active_zone,
            dict,
        ):
            active_zone = {}

        direction = str(
            data.get(
                "direction",
                active_zone.get(
                    "direction",
                    active_zone.get(
                        "zone_type",
                        active_zone.get(
                            "block_type",
                            "NEUTRAL",
                        ),
                    ),
                ),
            )
        ).upper()

        if direction not in {
            "BULLISH",
            "BEARISH",
        }:
            direction = "NEUTRAL"

        if (
            self.require_trend_alignment
            and trend_direction
            in {
                "BULLISH",
                "BEARISH",
            }
            and direction
            != trend_direction
        ):
            return (
                None,
                "trend_misalignment",
            )

        quality_score = (
            self._quality_score(
                data=data,
                active_zone=active_zone,
            )
        )

        definition = definitions.get(
            result.provider.lower()
        )

        provider_priority = (
            int(
                definition.priority
            )
            if definition
            is not None
            else 100
        )

        priority_component = max(
            0.0,
            100.0
            - float(
                provider_priority
            ),
        )

        score = (
            quality_score
            * self.quality_weight
            + priority_component
            * self.priority_weight
        )

        candidate = POICandidate(
            provider=result.provider,
            direction=direction,
            quality_score=(
                quality_score
            ),
            provider_priority=(
                provider_priority
            ),
            poi_type=(
                str(
                    data.get(
                        "poi_type",
                        data.get(
                            "provider_type",
                            "",
                        ),
                    )
                )
                or None
            ),
            active_zone=dict(
                active_zone
            ),
            source_result=result,
            score=float(
                score
            ),
            metadata={
                "passed": bool(
                    result.passed
                ),
            },
        )

        return (
            candidate,
            None,
        )

    @staticmethod
    def _quality_score(
        *,
        data: dict[str, Any],
        active_zone: dict[str, Any],
    ) -> float:
        values = (
            data.get(
                "quality_score"
            ),
            active_zone.get(
                "quality_score"
            ),
            active_zone.get(
                "quality"
            ),
        )

        for value in values:
            if value is None:
                continue

            try:
                score = float(
                    value
                )
            except (
                TypeError,
                ValueError,
            ):
                continue

            return max(
                0.0,
                min(
                    score,
                    100.0,
                ),
            )

        return 0.0

    @staticmethod
    def _trend_direction(
        context: StrategyContext,
    ) -> str:
        trend = context.get_result(
            role=ModuleRole.TREND
        )

        if trend is None:
            return "NEUTRAL"

        direction = str(
            trend.data.get(
                "direction",
                "NEUTRAL",
            )
        ).upper()

        if direction in {
            "BULLISH",
            "BEARISH",
        }:
            return direction

        return "NEUTRAL"

    @staticmethod
    def _poi_definitions(
        context: StrategyContext,
    ) -> dict[
        str,
        StrategyModuleDefinition,
    ]:
        definitions: dict[
            str,
            StrategyModuleDefinition,
        ] = {}

        for definition in (
            context.strategy.modules
        ):
            if (
                definition.role
                != ModuleRole.POI
            ):
                continue

            definitions[
                definition.provider
                .strip()
                .lower()
            ] = definition

        return definitions