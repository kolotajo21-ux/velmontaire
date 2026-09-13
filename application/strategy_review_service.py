from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from backend.application.strategy_management_service import (
    StrategyManagementService,
)


@dataclass(frozen=True, slots=True)
class StrategyReview:
    strategy_id: str
    version_id: str
    version_number: int
    entry: Any
    filters: Any
    stop_loss: Any
    take_profit: Any
    risk: Any
    management: Any
    unresolved_items: tuple[str, ...]
    previous_version_id: str | None
    changes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class StrategyReviewService:
    """Human-readable, fail-closed review boundary before execution."""

    def __init__(self, strategies: StrategyManagementService) -> None:
        self.strategies = strategies
        self._approved: set[tuple[str, str, str]] = set()

    def build_review(self, *, user_id: str, strategy_id: str) -> StrategyReview:
        current = self.strategies.active_version(
            user_id=user_id,
            strategy_id=strategy_id,
        )
        schema = self._schema(current.schema_json)
        previous = self._previous_version(
            user_id=user_id,
            strategy_id=strategy_id,
            current_number=current.version_number,
        )
        previous_schema = self._schema(previous.schema_json) if previous else {}

        unresolved = tuple(
            str(x)
            for x in (
                schema.get("unresolved_fields")
                or schema.get("unresolved_items")
                or []
            )
        )

        entry = self._pick(schema, "entry", "entries")
        filters = self._pick(schema, "filters", "filter")
        stop_loss = self._pick(schema, "stop_loss", "sl")
        take_profit = self._pick(schema, "take_profit", "tp")
        risk = self._pick(schema, "risk")
        management = self._pick(schema, "management")

        if filters is None:
            filters = []
        if management is None:
            management = []

        return StrategyReview(
            strategy_id=strategy_id,
            version_id=current.version_id,
            version_number=current.version_number,
            entry=entry,
            filters=filters,
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk=risk,
            management=management,
            unresolved_items=unresolved,
            previous_version_id=previous.version_id if previous else None,
            changes=self._diff(previous_schema, schema),
        )

    def approve(
        self,
        *,
        user_id: str,
        strategy_id: str,
        version_id: str,
    ) -> None:
        review = self.build_review(user_id=user_id, strategy_id=strategy_id)
        if review.version_id != version_id:
            raise RuntimeError("review_version_is_stale")
        if review.unresolved_items:
            raise RuntimeError("review_has_unresolved_items")
        if not review.entry:
            raise RuntimeError("review_entry_missing")
        if review.stop_loss is None:
            raise RuntimeError("review_stop_loss_missing")
        if review.take_profit is None:
            raise RuntimeError("review_take_profit_missing")
        if review.risk is None:
            raise RuntimeError("review_risk_missing")

        self._approved.add((user_id, strategy_id, version_id))

    def is_approved(
        self,
        *,
        user_id: str,
        strategy_id: str,
        version_id: str,
    ) -> bool:
        return (user_id, strategy_id, version_id) in self._approved

    def require_execution_approval(
        self,
        *,
        user_id: str,
        strategy_id: str,
    ) -> None:
        current = self.strategies.active_version(
            user_id=user_id,
            strategy_id=strategy_id,
        )
        if not self.is_approved(
            user_id=user_id,
            strategy_id=strategy_id,
            version_id=current.version_id,
        ):
            raise PermissionError("active_strategy_version_not_human_approved")

    def _previous_version(
        self,
        *,
        user_id: str,
        strategy_id: str,
        current_number: int,
    ):
        versions = self.strategies._versions(user_id, strategy_id)
        candidates = [
            version
            for version in versions
            if version.version_number < current_number
        ]
        return (
            max(candidates, key=lambda version: version.version_number)
            if candidates
            else None
        )

    @staticmethod
    def _schema(raw: str | None) -> dict[str, Any]:
        if not raw:
            return {}
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _pick(schema: dict[str, Any], *names: str) -> Any:
        # Legacy/top-level schema.
        for name in names:
            if name in schema:
                return schema[name]

        # Current executable rule structure.
        rules = schema.get("rules")
        if isinstance(rules, dict):
            for name in names:
                if name in rules:
                    return rules[name]

        # Parser-level filters and other review metadata are serialized here.
        metadata = schema.get("metadata")
        if isinstance(metadata, dict):
            for name in names:
                if name in metadata:
                    return metadata[name]

        return None

    @classmethod
    def _diff(
        cls,
        old: dict[str, Any],
        new: dict[str, Any],
    ) -> tuple[str, ...]:
        if not old:
            return ("initial_schema",)

        fields = (
            ("entry", ("entry", "entries")),
            ("filters", ("filters", "filter")),
            ("stop_loss", ("stop_loss", "sl")),
            ("take_profit", ("take_profit", "tp")),
            ("risk", ("risk",)),
            ("management", ("management",)),
        )
        changed = []
        for label, names in fields:
            if cls._pick(old, *names) != cls._pick(new, *names):
                changed.append(label)
        return tuple(changed)
