from __future__ import annotations

from typing import Any
from datetime import datetime, timezone

from application.strategy_management_service import StrategyManagementService
from application.strategy_review_service import StrategyReviewService
from strategy_parser.ai_builder import AIStrategyBuilder, AIStrategyBuilderResult


class WebStrategyApplication:
    """
    Browser-facing strategy lifecycle.

    Flow:
      create
      -> parse
      -> clarification if required
      -> persist immutable schema version
      -> human review
      -> approval
    """

    def __init__(self, *, repository: Any) -> None:
        self.strategies = StrategyManagementService(repository)
        self.reviews = StrategyReviewService(self.strategies)
        self.builder = AIStrategyBuilder()

        self._sessions: dict[
            tuple[str, str],
            AIStrategyBuilderResult,
        ] = {}

    def create(
        self,
        *,
        user_id: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        name = str(
            body.get("name", "")
        ).strip()

        source_text = str(
            body.get("source_text", "")
        ).strip()

        created = self.strategies.create_strategy(
            user_id=user_id,
            name=name,
            source_text=source_text,
        )

        strategy_id = created["strategy_id"]

        result = self.builder.start(
            source_text,
            strategy_id=strategy_id,
            name=name,
            version="1.0",
        )

        key = (
            user_id,
            strategy_id,
        )

        self._sessions[key] = result

        payload = self._builder_payload(
            result
        )

        # IMPORTANT:
        # Parser may already have everything it needs from the
        # original strategy text. In that case there is no
        # clarification round, so the completed schema MUST be
        # persisted here immediately.
        if result.ready:
            schema_json = self._schema_json(
                result
            )

            persisted = (
                self.strategies.create_version(
                    user_id=user_id,
                    strategy_id=strategy_id,
                    source_text=source_text,
                    schema_json=schema_json,
                )
            )

            self.strategies.activate_version(
                user_id=user_id,
                strategy_id=strategy_id,
                version_id=persisted[
                    "version_id"
                ],
            )

            self._sessions.pop(
                key,
                None,
            )

            payload[
                "persisted_version"
            ] = persisted

        return {
            "ok": True,
            "strategy": created,
            "clarification": payload,
        }

    def resume_compilation(
        self,
        *,
        user_id: str,
        strategy_id: str,
    ) -> dict[str, Any]:
        key = (
            user_id,
            strategy_id,
        )

        active = self.strategies.active_version(
            user_id=user_id,
            strategy_id=strategy_id,
        )

        result = self.builder.start(
            active.source_text,
            strategy_id=strategy_id,
            name=getattr(
                active,
                "name",
                strategy_id,
            ),
            version=str(
                active.version_number
            ),
        )

        self._sessions[key] = result

        payload = self._builder_payload(
            result
        )

        if result.ready:
            schema_json = self._schema_json(
                result
            )

            persisted = (
                self.strategies.create_version(
                    user_id=user_id,
                    strategy_id=strategy_id,
                    source_text=active.source_text,
                    schema_json=schema_json,
                )
            )

            self.strategies.activate_version(
                user_id=user_id,
                strategy_id=strategy_id,
                version_id=persisted[
                    "version_id"
                ],
            )

            self._sessions.pop(
                key,
                None,
            )

            payload[
                "persisted_version"
            ] = persisted

        return {
            "ok": True,
            "clarification": payload,
        }

    def answer(
        self,
        *,
        user_id: str,
        strategy_id: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        key = (
            user_id,
            strategy_id,
        )

        active = (
            self.strategies.active_version(
                user_id=user_id,
                strategy_id=strategy_id,
            )
        )

        current = self._sessions.get(
            key
        )

        if current is None:
            current = self.builder.start(
                active.source_text,
                strategy_id=strategy_id,
                version=str(
                    active.version_number
                ),
            )

        answers = body.get(
            "answers"
        )

        if (
            not isinstance(
                answers,
                dict,
            )
            or not answers
        ):
            raise ValueError(
                "clarification_answers_required"
            )

        result = self.builder.answer(
            current,
            answers,
            strategy_id=strategy_id,
            version=str(
                active.version_number
            ),
        )

        self._sessions[key] = result

        payload = self._builder_payload(
            result
        )

        if result.ready:
            schema_json = self._schema_json(
                result
            )

            persisted = (
                self.strategies.create_version(
                    user_id=user_id,
                    strategy_id=strategy_id,
                    source_text=active.source_text,
                    schema_json=schema_json,
                )
            )

            self.strategies.activate_version(
                user_id=user_id,
                strategy_id=strategy_id,
                version_id=persisted[
                    "version_id"
                ],
            )

            self._sessions.pop(
                key,
                None,
            )

            payload[
                "persisted_version"
            ] = persisted

        return {
            "ok": True,
            "clarification": payload,
        }

    def review(
        self,
        *,
        user_id: str,
        strategy_id: str,
    ) -> dict[str, Any]:
        review = self.reviews.build_review(
            user_id=user_id,
            strategy_id=strategy_id,
        )

        return {
            "ok": True,
            "review": review.to_dict(),
        }

    def approve(
        self,
        *,
        user_id: str,
        strategy_id: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        version_id = str(
            body.get(
                "version_id",
                "",
            )
        ).strip()

        if not version_id:
            raise ValueError(
                "version_id_required"
            )

        self.reviews.approve(
            user_id=user_id,
            strategy_id=strategy_id,
            version_id=version_id,
        )

        return {
            "ok": True,
            "status": "HUMAN_APPROVED",
            "strategy_id": strategy_id,
            "version_id": version_id,
        }

    def list_strategies(
        self,
        *,
        user_id: str,
    ) -> dict[str, Any]:
        records = self.strategies.repo.list_strategies(user_id)
        items: list[dict[str, Any]] = []

        for record in reversed(records):
            versions = self.strategies._versions(user_id, record.strategy_id)
            active = None
            if record.active_version_id:
                active = self.strategies.repo.get_strategy_version(
                    user_id,
                    record.active_version_id,
                )

            metadata = self._library_metadata(
                user_id,
                record.strategy_id,
            )

            # Library metadata (favorite/archive) must NOT change
            # strategy recency. Otherwise starring a card makes it jump to
            # the top of "Recently updated", which looks like the first card
            # was favorited instead of the clicked one.
            updated_at = (
                versions[-1].created_at if versions else record.created_at
            )

            items.append({
                "strategy_id": record.strategy_id,
                "name": record.name,
                "active_version_id": record.active_version_id,
                "active_version_number": (
                    active.version_number if active is not None else None
                ),
                "active_source_text": (
                    active.source_text if active is not None else ""
                ),
                "has_schema": bool(active and active.schema_json),
                "version_count": len(versions),
                "favorite": metadata["favorite"],
                "archived": metadata["archived"],
                "created_at": record.created_at,
                "updated_at": updated_at,
            })

        return {
            "ok": True,
            "strategies": items,
            "count": len(items),
        }

    def version_history(
        self,
        *,
        user_id: str,
        strategy_id: str,
    ) -> dict[str, Any]:
        strategy = self.strategies.repo.get_strategy(user_id, strategy_id)
        if strategy is None:
            raise PermissionError("strategy_not_owned")

        versions = self.strategies._versions(user_id, strategy_id)
        return {
            "ok": True,
            "strategy": {
                "strategy_id": strategy.strategy_id,
                "name": strategy.name,
                "active_version_id": strategy.active_version_id,
            },
            "versions": [
                {
                    "version_id": version.version_id,
                    "version_number": version.version_number,
                    "source_text": version.source_text,
                    "has_schema": bool(version.schema_json),
                    "created_at": version.created_at,
                    "active": version.version_id == strategy.active_version_id,
                }
                for version in reversed(versions)
            ],
        }


    def strategy_detail(
        self,
        *,
        user_id: str,
        strategy_id: str,
    ) -> dict[str, Any]:
        strategy = self.strategies.repo.get_strategy(user_id, strategy_id)
        if strategy is None:
            raise PermissionError("strategy_not_owned")

        active = None
        if strategy.active_version_id:
            active = self.strategies.repo.get_strategy_version(
                user_id,
                strategy.active_version_id,
            )

        metadata = self._library_metadata(user_id, strategy_id)

        return {
            "ok": True,
            "strategy": {
                "strategy_id": strategy.strategy_id,
                "name": strategy.name,
                "active_version_id": strategy.active_version_id,
                "active_version_number": (
                    active.version_number if active is not None else None
                ),
                "source_text": (
                    active.source_text if active is not None else ""
                ),
                "has_schema": bool(active and active.schema_json),
                "favorite": metadata["favorite"],
                "archived": metadata["archived"],
                "created_at": strategy.created_at,
            },
        }

    def rename_strategy(
        self,
        *,
        user_id: str,
        strategy_id: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        strategy = self.strategies.repo.get_strategy(user_id, strategy_id)
        if strategy is None:
            raise PermissionError("strategy_not_owned")

        name = str(body.get("name", "")).strip()
        if not name:
            raise ValueError("strategy_name_required")
        if len(name) > 120:
            raise ValueError("strategy_name_too_long")

        with self.strategies.repo.db.connect() as conn:
            existing = conn.execute(
                """SELECT strategy_id FROM strategies
                WHERE user_id=? AND lower(name)=lower(?) AND strategy_id<>?""",
                (user_id, name, strategy_id),
            ).fetchone()
            if existing is not None:
                raise ValueError("strategy_name_already_exists")

            conn.execute(
                """UPDATE strategies SET name=?
                WHERE strategy_id=? AND user_id=?""",
                (name, strategy_id, user_id),
            )

        self._touch_library_metadata(user_id, strategy_id)

        return {
            "ok": True,
            "strategy_id": strategy_id,
            "name": name,
        }

    def set_favorite(
        self,
        *,
        user_id: str,
        strategy_id: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        self._owned_strategy(user_id, strategy_id)
        favorite = body.get("favorite")
        if not isinstance(favorite, bool):
            raise ValueError("favorite_boolean_required")

        self._set_library_metadata(
            user_id=user_id,
            strategy_id=strategy_id,
            favorite=favorite,
        )
        return {
            "ok": True,
            "strategy_id": strategy_id,
            "favorite": favorite,
        }

    def archive_library_strategy(
        self,
        *,
        user_id: str,
        strategy_id: str,
    ) -> dict[str, Any]:
        self._owned_strategy(user_id, strategy_id)
        self._set_library_metadata(
            user_id=user_id,
            strategy_id=strategy_id,
            archived=True,
        )
        return {
            "ok": True,
            "strategy_id": strategy_id,
            "archived": True,
        }

    def restore_library_strategy(
        self,
        *,
        user_id: str,
        strategy_id: str,
    ) -> dict[str, Any]:
        self._owned_strategy(user_id, strategy_id)
        self._set_library_metadata(
            user_id=user_id,
            strategy_id=strategy_id,
            archived=False,
        )
        return {
            "ok": True,
            "strategy_id": strategy_id,
            "archived": False,
        }

    def duplicate_strategy(
        self,
        *,
        user_id: str,
        strategy_id: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        strategy = self._owned_strategy(user_id, strategy_id)
        active = self.strategies.active_version(
            user_id=user_id,
            strategy_id=strategy_id,
        )

        requested_name = str(body.get("name", "")).strip()
        new_name = requested_name or self._next_copy_name(
            user_id=user_id,
            base_name=strategy.name,
        )

        created = self.strategies.create_strategy(
            user_id=user_id,
            name=new_name,
            source_text=active.source_text,
        )

        active_version_id = created["active_version_id"]
        active_version_number = created["version_number"]

        # Preserve the exact compiled schema when one exists instead of
        # re-parsing and potentially changing the duplicate.
        if active.schema_json:
            persisted = self.strategies.create_version(
                user_id=user_id,
                strategy_id=created["strategy_id"],
                source_text=active.source_text,
                schema_json=active.schema_json,
            )
            self.strategies.activate_version(
                user_id=user_id,
                strategy_id=created["strategy_id"],
                version_id=persisted["version_id"],
            )
            active_version_id = persisted["version_id"]
            active_version_number = persisted["version_number"]

        return {
            "ok": True,
            "strategy": {
                "strategy_id": created["strategy_id"],
                "name": new_name,
                "active_version_id": active_version_id,
                "active_version_number": active_version_number,
            },
        }

    def delete_strategy(
        self,
        *,
        user_id: str,
        strategy_id: str,
    ) -> dict[str, Any]:
        self._owned_strategy(user_id, strategy_id)

        with self.strategies.repo.db.connect() as conn:
            backtests = conn.execute(
                """SELECT COUNT(*) AS n FROM backtests
                WHERE user_id=? AND strategy_id=?""",
                (user_id, strategy_id),
            ).fetchone()["n"]

            bots = conn.execute(
                """SELECT COUNT(*) AS n FROM bot_instances
                WHERE user_id=? AND strategy_id=?""",
                (user_id, strategy_id),
            ).fetchone()["n"]

            if backtests or bots:
                raise RuntimeError(
                    "strategy_delete_blocked:"
                    f"backtests={backtests}:bots={bots}"
                )

            conn.execute(
                """DELETE FROM strategy_library_metadata
                WHERE user_id=? AND strategy_id=?""",
                (user_id, strategy_id),
            )
            conn.execute(
                """DELETE FROM strategy_versions
                WHERE user_id=? AND strategy_id=?""",
                (user_id, strategy_id),
            )
            cursor = conn.execute(
                """DELETE FROM strategies
                WHERE user_id=? AND strategy_id=?""",
                (user_id, strategy_id),
            )
            if cursor.rowcount != 1:
                raise PermissionError("strategy_not_owned")

        self._sessions.pop((user_id, strategy_id), None)

        return {
            "ok": True,
            "strategy_id": strategy_id,
            "deleted": True,
        }

    def _owned_strategy(self, user_id: str, strategy_id: str):
        strategy = self.strategies.repo.get_strategy(user_id, strategy_id)
        if strategy is None:
            raise PermissionError("strategy_not_owned")
        return strategy

    def _ensure_library_metadata(self) -> None:
        with self.strategies.repo.db.connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS strategy_library_metadata (
                    user_id TEXT NOT NULL,
                    strategy_id TEXT NOT NULL,
                    favorite INTEGER NOT NULL DEFAULT 0,
                    archived INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(user_id, strategy_id),
                    FOREIGN KEY(strategy_id) REFERENCES strategies(strategy_id),
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                )"""
            )
            conn.execute(
                """CREATE INDEX IF NOT EXISTS idx_strategy_library_owner
                ON strategy_library_metadata(user_id, archived, favorite)"""
            )

    def _library_metadata(
        self,
        user_id: str,
        strategy_id: str,
    ) -> dict[str, Any]:
        self._ensure_library_metadata()
        with self.strategies.repo.db.connect() as conn:
            row = conn.execute(
                """SELECT favorite, archived, updated_at
                FROM strategy_library_metadata
                WHERE user_id=? AND strategy_id=?""",
                (user_id, strategy_id),
            ).fetchone()

        if row is None:
            return {
                "favorite": False,
                "archived": False,
                "updated_at": None,
            }

        return {
            "favorite": bool(row["favorite"]),
            "archived": bool(row["archived"]),
            "updated_at": row["updated_at"],
        }

    def _set_library_metadata(
        self,
        *,
        user_id: str,
        strategy_id: str,
        favorite: bool | None = None,
        archived: bool | None = None,
    ) -> None:
        self._ensure_library_metadata()
        current = self._library_metadata(user_id, strategy_id)
        new_favorite = current["favorite"] if favorite is None else favorite
        new_archived = current["archived"] if archived is None else archived
        now = datetime.now(timezone.utc).isoformat()

        with self.strategies.repo.db.connect() as conn:
            conn.execute(
                """INSERT INTO strategy_library_metadata
                (user_id,strategy_id,favorite,archived,updated_at)
                VALUES(?,?,?,?,?)
                ON CONFLICT(user_id,strategy_id)
                DO UPDATE SET
                    favorite=excluded.favorite,
                    archived=excluded.archived,
                    updated_at=excluded.updated_at""",
                (
                    user_id,
                    strategy_id,
                    1 if new_favorite else 0,
                    1 if new_archived else 0,
                    now,
                ),
            )

    def _touch_library_metadata(self, user_id: str, strategy_id: str) -> None:
        self._set_library_metadata(
            user_id=user_id,
            strategy_id=strategy_id,
        )

    def _next_copy_name(self, *, user_id: str, base_name: str) -> str:
        records = self.strategies.repo.list_strategies(user_id)
        existing = {record.name.casefold() for record in records}

        candidate = f"{base_name} Copy"
        if candidate.casefold() not in existing:
            return candidate

        index = 2
        while True:
            candidate = f"{base_name} Copy {index}"
            if candidate.casefold() not in existing:
                return candidate
            index += 1


    @staticmethod
    def _builder_payload(
        result: AIStrategyBuilderResult,
    ) -> dict[str, Any]:
        draft_questions = list(
            result.build.session.draft.questions
        )

        return {
            "ready": result.ready,
            "status": result.status.value,
            # Keep the legacy string list for backward compatibility.
            "questions": list(
                result.questions
            ),
            # IMPORTANT: the browser must bind an answer to the parser's exact
            # path. Blockers are diagnostic messages and can contain additional
            # conflict:* entries, so positional questions[i] <-> blockers[i]
            # mapping is unsafe and can write an answer into the wrong field.
            "question_items": [
                {
                    "question_id": question.question_id,
                    "path": question.path,
                    "question": question.question,
                    "reason": question.reason,
                    "required": bool(question.required),
                }
                for question in draft_questions
            ],
            "blockers": list(
                result.blockers
            ),
            "warnings": list(
                result.warnings
            ),
        }

    @staticmethod
    def _schema_json(
        result: AIStrategyBuilderResult,
    ) -> str:
        import json

        schema = result.build.schema

        if schema is None:
            raise RuntimeError(
                "clarification_schema_missing"
            )

        if hasattr(
            schema,
            "to_dict",
        ):
            payload = (
                schema.to_dict()
            )

        elif hasattr(
            schema,
            "__dict__",
        ):
            payload = dict(
                schema.__dict__
            )

        else:
            payload = schema

        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )