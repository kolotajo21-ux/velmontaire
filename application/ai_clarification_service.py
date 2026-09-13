from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.application.strategy_management_service import StrategyManagementService


@dataclass(frozen=True, slots=True)
class ClarificationState:
    strategy_id: str
    version_id: str
    status: str
    questions: tuple[str, ...]
    blockers: tuple[str, ...]
    schema: Any = None
    diagnostics: Any = None


class AIStrategyClarificationService:
    """
    Product-facing bridge between Strategy Management and the existing
    AI parsing/clarification pipeline.

    Invariants:
    - only the owner's active strategy version can enter the AI flow;
    - unresolved strategies never become executable;
    - user answers are passed back to the existing AI pipeline;
    - no provider/module guessing is performed here;
    - a READY schema is persisted as a new immutable strategy version.
    """

    READY_STATUSES = {
        "READY",
        "READY_FOR_SCHEMA",
        "COMPILED",
    }

    def __init__(
        self,
        *,
        strategies: StrategyManagementService,
        pipeline: Any,
    ) -> None:
        self.strategies = strategies
        self.pipeline = pipeline

    def start(
        self,
        *,
        user_id: str,
        strategy_id: str,
    ) -> ClarificationState:
        active = self.strategies.active_version(
            user_id=user_id,
            strategy_id=strategy_id,
        )

        result = self._start_pipeline(
            active.source_text
        )

        return self._normalize(
            strategy_id=strategy_id,
            version_id=active.version_id,
            result=result,
        )

    def answer(
        self,
        *,
        user_id: str,
        strategy_id: str,
        answers: dict[str, Any],
    ) -> ClarificationState:
        active = self.strategies.active_version(
            user_id=user_id,
            strategy_id=strategy_id,
        )

        if not isinstance(answers, dict) or not answers:
            raise ValueError("clarification_answers_required")

        result = self._answer_pipeline(
            source_text=active.source_text,
            answers=answers,
        )

        return self._normalize(
            strategy_id=strategy_id,
            version_id=active.version_id,
            result=result,
        )

    def persist_ready_schema(
        self,
        *,
        user_id: str,
        strategy_id: str,
        state: ClarificationState,
    ) -> dict[str, Any]:
        if state.strategy_id != strategy_id:
            raise ValueError("clarification_strategy_mismatch")

        current = self.strategies.active_version(
            user_id=user_id,
            strategy_id=strategy_id,
        )

        if current.version_id != state.version_id:
            raise RuntimeError("clarification_version_is_stale")

        if state.status not in self.READY_STATUSES:
            raise RuntimeError("clarification_not_ready")

        if state.questions or state.blockers:
            raise RuntimeError("clarification_has_unresolved_items")

        if state.schema is None:
            raise RuntimeError("clarification_schema_missing")

        schema_json = self._schema_json(state.schema)

        created = self.strategies.create_version(
            user_id=user_id,
            strategy_id=strategy_id,
            source_text=current.source_text,
            schema_json=schema_json,
        )

        self.strategies.activate_version(
            user_id=user_id,
            strategy_id=strategy_id,
            version_id=created["version_id"],
        )

        return created

    def _start_pipeline(self, source_text: str) -> Any:
        # Adapter compatibility for the existing parser/pipeline generations.
        for name in ("start", "parse", "run"):
            fn = getattr(self.pipeline, name, None)
            if callable(fn):
                try:
                    return fn(source_text=source_text)
                except TypeError:
                    try:
                        return fn(source_text)
                    except TypeError:
                        continue
        raise RuntimeError("ai_pipeline_start_not_supported")

    def _answer_pipeline(
        self,
        *,
        source_text: str,
        answers: dict[str, Any],
    ) -> Any:
        for name in (
            "answer",
            "clarify",
            "continue_with_answers",
            "resolve",
        ):
            fn = getattr(self.pipeline, name, None)
            if callable(fn):
                attempts = (
                    lambda: fn(source_text=source_text, answers=answers),
                    lambda: fn(answers=answers),
                    lambda: fn(source_text, answers),
                    lambda: fn(answers),
                )
                for attempt in attempts:
                    try:
                        return attempt()
                    except TypeError:
                        continue
        raise RuntimeError("ai_pipeline_answer_not_supported")

    @classmethod
    def _normalize(
        cls,
        *,
        strategy_id: str,
        version_id: str,
        result: Any,
    ) -> ClarificationState:
        status = cls._value(
            result,
            "status",
            default="UNKNOWN",
        )

        questions = cls._sequence(
            cls._value(
                result,
                "questions",
                default=(),
            )
        )

        blockers = cls._sequence(
            cls._value(
                result,
                "blockers",
                default=(),
            )
        )

        schema = cls._first_value(
            result,
            (
                "schema",
                "generated_schema",
                "strategy_schema",
                "definition",
            ),
        )

        diagnostics = cls._value(
            result,
            "diagnostics",
            default=None,
        )

        return ClarificationState(
            strategy_id=strategy_id,
            version_id=version_id,
            status=str(status),
            questions=questions,
            blockers=blockers,
            schema=schema,
            diagnostics=diagnostics,
        )

    @staticmethod
    def _value(
        obj: Any,
        name: str,
        *,
        default: Any,
    ) -> Any:
        if isinstance(obj, dict):
            value = obj.get(name, default)
        else:
            value = getattr(obj, name, default)

        if hasattr(value, "value"):
            return value.value

        return value

    @classmethod
    def _first_value(
        cls,
        obj: Any,
        names: tuple[str, ...],
    ) -> Any:
        for name in names:
            value = cls._value(
                obj,
                name,
                default=None,
            )
            if value is not None:
                return value
        return None

    @staticmethod
    def _sequence(value: Any) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            return (value,)
        return tuple(str(item) for item in value)

    @staticmethod
    def _schema_json(schema: Any) -> str:
        import json
        from dataclasses import asdict, is_dataclass

        if hasattr(schema, "model_dump"):
            payload = schema.model_dump()
        elif hasattr(schema, "to_dict"):
            payload = schema.to_dict()
        elif is_dataclass(schema):
            payload = asdict(schema)
        elif isinstance(schema, dict):
            payload = schema
        else:
            payload = {
                "repr": str(schema),
            }

        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
        )
