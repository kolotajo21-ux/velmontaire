from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from strategy_schema import StrategySchema

from .models import ParseSessionStatus, StrategyParseSession
from .normalizer import NormalizationResult, StrategyTextNormalizer
from .parser import StrategyTextParser
from .pipeline import StrategyParsingPipeline


@dataclass(slots=True)
class StrategyBuildResult:
    session: StrategyParseSession
    normalization: NormalizationResult
    schema: StrategySchema | None = None

    @property
    def ready(self) -> bool:
        return self.schema is not None

    @property
    def questions(self) -> list[str]:
        return [
            question.question
            for question in self.session.draft.questions
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "session": self.session.to_dict(),
            "normalization": self.normalization.to_dict(),
            "schema": self.schema.to_dict() if self.schema else None,
            "questions": self.questions,
        }


class StrategySchemaBuilder:
    """
    Day 45 integration gateway.

    Raw user text
      -> conservative normalization
      -> parser
      -> clarification session
      -> validated StrategySchema

    Missing information is never invented.
    """

    def __init__(
        self,
        *,
        normalizer: StrategyTextNormalizer | None = None,
        parser: StrategyTextParser | None = None,
    ) -> None:
        self.normalizer = normalizer or StrategyTextNormalizer()
        self.parser = parser or StrategyTextParser()
        self.pipeline = StrategyParsingPipeline(parser=self.parser)

    def start(
        self,
        text: str,
        *,
        session_id: str | None = None,
        strategy_id: str | None = None,
        name: str = "Parsed Strategy",
        version: str = "1.0",
    ) -> StrategyBuildResult:
        normalization = self.normalizer.normalize(text)
        session = self.pipeline.start(
            normalization.normalized_text,
            session_id=session_id,
        )

        # Preserve exactly what the user originally supplied.
        session.original_text = normalization.source_text
        session.draft.source_text = normalization.source_text
        session.draft.metadata["normalization"] = normalization.to_dict()

        schema = self._try_build(
            session,
            strategy_id=strategy_id or session.session_id,
            name=name,
            version=version,
        )
        return StrategyBuildResult(session, normalization, schema)

    def answer(
        self,
        result: StrategyBuildResult,
        answers: dict[str, Any],
        *,
        overwrite: bool = False,
        strategy_id: str | None = None,
        name: str = "Parsed Strategy",
        version: str = "1.0",
    ) -> StrategyBuildResult:
        self.pipeline.answer(
            result.session,
            answers,
            overwrite=overwrite,
        )
        result.schema = self._try_build(
            result.session,
            strategy_id=strategy_id or result.session.session_id,
            name=name,
            version=version,
        )
        return result

    def resolve_conflict(
        self,
        result: StrategyBuildResult,
        path: str,
        value: Any,
        *,
        strategy_id: str | None = None,
        name: str = "Parsed Strategy",
        version: str = "1.0",
    ) -> StrategyBuildResult:
        self.pipeline.resolve_conflict(
            result.session,
            path,
            value,
        )
        result.schema = self._try_build(
            result.session,
            strategy_id=strategy_id or result.session.session_id,
            name=name,
            version=version,
        )
        return result

    def require_schema(
        self,
        result: StrategyBuildResult,
    ) -> StrategySchema:
        if result.schema is None:
            raise ValueError("strategy_schema_not_ready")
        return result.schema

    def _try_build(
        self,
        session: StrategyParseSession,
        *,
        strategy_id: str,
        name: str,
        version: str,
    ) -> StrategySchema | None:
        if session.status != ParseSessionStatus.READY_FOR_SCHEMA:
            return None

        schema = self.pipeline.build_schema(
            session,
            strategy_id=strategy_id,
            name=name,
            version=version,
        )

        # Keep the original user text, not the normalized derivative.
        schema.source_text = session.original_text
        schema.metadata["parse_session_id"] = session.session_id
        schema.metadata["clarification_turns"] = len(
            session.clarification_history
        )

        validation = schema.validate()
        if not validation.valid:
            session.status = ParseSessionStatus.INVALID
            session.invalid_reason = "generated_schema_validation_failed"
            return None

        return schema