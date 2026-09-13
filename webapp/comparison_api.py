from __future__ import annotations

import json
from typing import Any

from backend.application.strategy_version_comparison_service import StrategyVersionComparisonService


class WebStrategyComparisonApplication:
    def __init__(self, repository: Any) -> None:
        self.repo = repository
        self.service = StrategyVersionComparisonService()

    def compare(self, *, user_id: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if not isinstance(body, dict):
            return 400, {"ok": False, "error": "invalid_request"}

        previous_id = str(body.get("previous_backtest_id", "")).strip()
        candidate_id = str(body.get("candidate_backtest_id", "")).strip()

        if not previous_id or not candidate_id:
            return 400, {"ok": False, "error": "two_backtest_ids_required"}
        if previous_id == candidate_id:
            return 400, {"ok": False, "error": "comparison_requires_two_distinct_backtests"}

        previous = self.repo.get_backtest(user_id, previous_id)
        candidate = self.repo.get_backtest(user_id, candidate_id)
        if previous is None or candidate is None:
            return 404, {"ok": False, "error": "comparison_resource_not_found"}

        if previous.status != "COMPLETED" or candidate.status != "COMPLETED":
            return 409, {"ok": False, "error": "comparison_requires_completed_backtests"}
        if previous.strategy_id != candidate.strategy_id:
            return 409, {"ok": False, "error": "comparison_requires_same_strategy"}
        if previous.version_id == candidate.version_id:
            return 409, {"ok": False, "error": "comparison_requires_distinct_versions"}

        previous_request = self._json(previous.request_json)
        candidate_request = self._json(candidate.request_json)
        if previous_request != candidate_request:
            return 409, {
                "ok": False,
                "error": "comparison_requires_identical_backtest_configuration",
                "previous_configuration": previous_request,
                "candidate_configuration": candidate_request,
            }

        previous_result = self._json(previous.result_json)
        candidate_result = self._json(candidate.result_json)
        previous_metrics = previous_result.get("metrics")
        candidate_metrics = candidate_result.get("metrics")
        if not isinstance(previous_metrics, dict) or not isinstance(candidate_metrics, dict):
            return 409, {"ok": False, "error": "comparison_metrics_missing"}

        previous_version = self.repo.get_strategy_version(user_id, previous.version_id)
        candidate_version = self.repo.get_strategy_version(user_id, candidate.version_id)
        if previous_version is None or candidate_version is None:
            return 409, {"ok": False, "error": "comparison_version_missing"}

        changes = self._schema_changes(
            self._json(previous_version.schema_json),
            self._json(candidate_version.schema_json),
        )

        comparison = self.service.compare(
            strategy_id=previous.strategy_id,
            previous_version_id=previous.version_id,
            candidate_version_id=candidate.version_id,
            previous_statistics=previous_metrics,
            candidate_statistics=candidate_metrics,
            schema_changes=changes,
        )

        return 200, {
            "ok": True,
            "comparison": comparison,
            "configuration": previous_request,
            "previous_backtest_id": previous.backtest_id,
            "candidate_backtest_id": candidate.backtest_id,
            "previous_equity_curve": previous_result.get("equity_curve", []),
            "candidate_equity_curve": candidate_result.get("equity_curve", []),
        }

    @staticmethod
    def _json(raw: Any) -> dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        if raw is None or raw == "":
            return {}
        value = json.loads(str(raw))
        return value if isinstance(value, dict) else {}

    @classmethod
    def _schema_changes(cls, previous: Any, candidate: Any) -> list[str]:
        changes: list[str] = []
        cls._diff("", previous, candidate, changes)
        return changes

    @classmethod
    def _diff(cls, path: str, previous: Any, candidate: Any, out: list[str]) -> None:
        if type(previous) is not type(candidate):
            out.append(path or "$")
            return
        if isinstance(previous, dict):
            for key in sorted(set(previous) | set(candidate)):
                child = f"{path}.{key}" if path else str(key)
                if key not in previous or key not in candidate:
                    out.append(child)
                else:
                    cls._diff(child, previous[key], candidate[key], out)
            return
        if isinstance(previous, list):
            if len(previous) != len(candidate):
                out.append(path or "$")
                return
            for index, (a, b) in enumerate(zip(previous, candidate)):
                cls._diff(f"{path}[{index}]", a, b, out)
            return
        if previous != candidate:
            out.append(path or "$")
