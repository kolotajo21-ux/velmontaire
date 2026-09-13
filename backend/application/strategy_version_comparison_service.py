from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True, slots=True)
class MetricDelta:
    previous: float | int | None
    candidate: float | int | None
    delta: float | int | None
    direction: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class StrategyVersionComparisonService:
    """
    Compares two immutable strategy/backtest versions for product UI.

    Important:
    - comparison is descriptive, not an automatic activation decision;
    - lower drawdown is treated as improvement;
    - higher profit/PF/win-rate/expectancy is treated as improvement;
    - missing metrics stay UNKNOWN instead of being guessed.
    """

    HIGHER_IS_BETTER = {
        "net_profit",
        "net_r",
        "win_rate",
        "profit_factor",
        "expectancy_r",
        "average_r",
    }
    LOWER_IS_BETTER = {
        "max_drawdown",
        "max_drawdown_r",
    }

    def compare(
        self,
        *,
        strategy_id: str,
        previous_version_id: str,
        candidate_version_id: str,
        previous_statistics: dict[str, Any],
        candidate_statistics: dict[str, Any],
        schema_changes: list[str] | tuple[str, ...],
    ) -> dict[str, Any]:
        if previous_version_id == candidate_version_id:
            raise ValueError("comparison_requires_two_distinct_versions")

        metric_names = (
            "net_profit",
            "net_r",
            "win_rate",
            "profit_factor",
            "max_drawdown",
            "max_drawdown_r",
            "trades",
            "expectancy_r",
            "average_r",
        )

        deltas = {
            name: self._metric_delta(
                name,
                previous_statistics.get(name),
                candidate_statistics.get(name),
            ).to_dict()
            for name in metric_names
        }

        improved = sum(
            1 for item in deltas.values()
            if item["direction"] == "IMPROVED"
        )
        worsened = sum(
            1 for item in deltas.values()
            if item["direction"] == "WORSENED"
        )

        if improved > worsened:
            summary = "MORE_METRICS_IMPROVED"
        elif worsened > improved:
            summary = "MORE_METRICS_WORSENED"
        else:
            summary = "MIXED_OR_UNCHANGED"

        return {
            "strategy_id": strategy_id,
            "previous_version_id": previous_version_id,
            "candidate_version_id": candidate_version_id,
            "schema_changes": list(schema_changes),
            "metrics": deltas,
            "summary": summary,
            "automatic_activation": False,
        }

    def _metric_delta(
        self,
        name: str,
        previous: Any,
        candidate: Any,
    ) -> MetricDelta:
        if previous is None or candidate is None:
            return MetricDelta(previous, candidate, None, "UNKNOWN")

        previous_n = float(previous)
        candidate_n = float(candidate)
        delta = candidate_n - previous_n

        if delta == 0:
            direction = "UNCHANGED"
        elif name in self.LOWER_IS_BETTER:
            direction = "IMPROVED" if delta < 0 else "WORSENED"
        elif name in self.HIGHER_IS_BETTER:
            direction = "IMPROVED" if delta > 0 else "WORSENED"
        else:
            # E.g. number of trades: change is informative but not inherently good/bad.
            direction = "CHANGED"

        return MetricDelta(
            previous=previous,
            candidate=candidate,
            delta=round(delta, 8),
            direction=direction,
        )
