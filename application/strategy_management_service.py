from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import Any

from backend.domain.persistence_models import StrategyRecord, StrategyVersionRecord
from backend.infrastructure.repositories import PersistenceRepository


class StrategyManagementService:
    """
    Day 106 strategy lifecycle service.

    Lifecycle:
      create -> version -> activate -> compile/backtest against active version -> archive

    All operations are explicitly user-scoped.
    """

    def __init__(self, repository: PersistenceRepository) -> None:
        self.repo = repository
        self._archived: set[tuple[str, str]] = set()

    def create_strategy(
        self,
        *,
        user_id: str,
        name: str,
        source_text: str,
    ) -> dict[str, Any]:
        self._require(user_id, "user_id_required")
        self._require(name, "strategy_name_required")
        self._require(source_text, "strategy_source_required")

        strategy_id = self._id("strategy", user_id, name, source_text)
        version_id = self._id("version", strategy_id, "1", source_text)

        self.repo.create_strategy(
            StrategyRecord(strategy_id, user_id, name.strip())
        )
        self.repo.create_strategy_version(
            StrategyVersionRecord(
                version_id,
                strategy_id,
                user_id,
                1,
                source_text.strip(),
            )
        )
        self.repo.set_active_version(user_id, strategy_id, version_id)

        return {
            "strategy_id": strategy_id,
            "active_version_id": version_id,
            "version_number": 1,
            "status": "ACTIVE",
        }

    def get_strategy(self, *, user_id: str, strategy_id: str) -> dict[str, Any] | None:
        strategy = self.repo.get_strategy(user_id, strategy_id)
        if strategy is None:
            return None

        return {
            "strategy_id": strategy.strategy_id,
            "name": strategy.name,
            "active_version_id": strategy.active_version_id,
            "status": (
                "ARCHIVED"
                if (user_id, strategy_id) in self._archived
                else "ACTIVE"
            ),
        }

    def create_version(
        self,
        *,
        user_id: str,
        strategy_id: str,
        source_text: str,
        schema_json: str | None = None,
    ) -> dict[str, Any]:
        strategy = self._owned_active_strategy(user_id, strategy_id)
        self._require(source_text, "strategy_source_required")

        versions = self._versions(user_id, strategy_id)
        number = max((v.version_number for v in versions), default=0) + 1
        version_id = self._id("version", strategy_id, str(number), source_text)

        self.repo.create_strategy_version(
            StrategyVersionRecord(
                version_id,
                strategy.strategy_id,
                user_id,
                number,
                source_text.strip(),
                schema_json,
            )
        )

        return {
            "strategy_id": strategy_id,
            "version_id": version_id,
            "version_number": number,
        }

    def activate_version(
        self,
        *,
        user_id: str,
        strategy_id: str,
        version_id: str,
    ) -> None:
        self._owned_active_strategy(user_id, strategy_id)
        self.repo.set_active_version(user_id, strategy_id, version_id)

    def archive_strategy(self, *, user_id: str, strategy_id: str) -> None:
        self._owned_active_strategy(user_id, strategy_id)
        self._archived.add((user_id, strategy_id))

    def restore_strategy(self, *, user_id: str, strategy_id: str) -> None:
        if self.repo.get_strategy(user_id, strategy_id) is None:
            raise PermissionError("strategy_not_owned")
        self._archived.discard((user_id, strategy_id))

    def active_version(
        self,
        *,
        user_id: str,
        strategy_id: str,
    ) -> StrategyVersionRecord:
        strategy = self._owned_active_strategy(user_id, strategy_id)
        if not strategy.active_version_id:
            raise RuntimeError("active_version_missing")

        version = self.repo.get_strategy_version(user_id, strategy.active_version_id)
        if version is None or version.strategy_id != strategy_id:
            raise RuntimeError("active_version_invalid")
        return version

    def compiler_payload(self, *, user_id: str, strategy_id: str) -> dict[str, Any]:
        version = self.active_version(user_id=user_id, strategy_id=strategy_id)
        return {
            "strategy_id": strategy_id,
            "version_id": version.version_id,
            "version_number": version.version_number,
            "source_text": version.source_text,
            "schema_json": version.schema_json,
        }

    def backtest_payload(self, *, user_id: str, strategy_id: str) -> dict[str, Any]:
        # Same frozen active-version boundary as compilation.
        return dict(self.compiler_payload(user_id=user_id, strategy_id=strategy_id))

    def _owned_active_strategy(self, user_id: str, strategy_id: str) -> StrategyRecord:
        strategy = self.repo.get_strategy(user_id, strategy_id)
        if strategy is None:
            raise PermissionError("strategy_not_owned")
        if (user_id, strategy_id) in self._archived:
            raise RuntimeError("strategy_archived")
        return strategy

    def _versions(self, user_id: str, strategy_id: str) -> list[StrategyVersionRecord]:
        # Day 103 repository intentionally exposed focused methods only.
        # Query stays inside persistence boundary and remains owner-scoped.
        with self.repo.db.connect() as conn:
            rows = conn.execute(
                """SELECT * FROM strategy_versions
                WHERE user_id=? AND strategy_id=?
                ORDER BY version_number""",
                (user_id, strategy_id),
            ).fetchall()
        return [StrategyVersionRecord(**dict(row)) for row in rows]

    @staticmethod
    def _require(value: str, error: str) -> None:
        if not str(value).strip():
            raise ValueError(error)

    @staticmethod
    def _id(prefix: str, *parts: str) -> str:
        raw = "|".join(str(x) for x in parts)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
        return f"{prefix}_{digest}"
