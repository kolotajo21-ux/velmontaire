from __future__ import annotations

import hashlib
from typing import Any

from .models import (
    ClarificationTurn,
    ParsedFact,
    ParseSessionStatus,
    StrategyParseSession,
)
from .parser import StrategyTextParser


class StrategyParsingPipeline:
    """Day 43 stateful, conservative multi-step parsing pipeline."""

    def __init__(self, parser: StrategyTextParser | None = None) -> None:
        self.parser = parser or StrategyTextParser()

    def start(self, text: str, *, session_id: str | None = None) -> StrategyParseSession:
        source = str(text or "").strip()
        if not source:
            raise ValueError("strategy text is required")

        draft = self.parser.parse(source)
        sid = session_id or self._stable_session_id(source)
        return StrategyParseSession(
            session_id=sid,
            original_text=source,
            draft=draft,
            status=self._status_for(draft),
        )

    def answer(
        self,
        session: StrategyParseSession,
        answers: dict[str, Any],
        *,
        overwrite: bool = False,
    ) -> StrategyParseSession:
        if session.status == ParseSessionStatus.INVALID:
            raise ValueError("strategy_parse_session_invalid")

        clean = {str(k): v for k, v in answers.items() if v is not None and v != ""}
        accepted: list[str] = []
        conflicts: list[str] = []

        for path, value in clean.items():
            existing = session.draft.facts.get(path)

            if existing is not None and existing.value != value and not overwrite:
                values = [existing.value, value]
                session.draft.conflicts[path] = list(dict.fromkeys(map(self._hashable_display, values)))
                conflicts.append(path)
                continue

            session.draft.facts[path] = ParsedFact(
                path=path,
                value=value,
                source_text="USER_CLARIFICATION",
                confidence=1.0,
            )
            session.draft.conflicts.pop(path, None)
            accepted.append(path)

        session.clarification_history.append(
            ClarificationTurn(
                turn_index=len(session.clarification_history) + 1,
                answers=clean,
                accepted_paths=accepted,
                conflict_paths=conflicts,
            )
        )
        self.parser._finalize(session.draft)
        session.status = self._status_for(session.draft)
        return session

    def resolve_conflict(
        self,
        session: StrategyParseSession,
        path: str,
        value: Any,
    ) -> StrategyParseSession:
        return self.answer(session, {path: value}, overwrite=True)

    def build_schema(self, session: StrategyParseSession, **kwargs: Any):
        if not session.ready_for_schema:
            raise ValueError("strategy_parse_session_not_ready")
        return self.parser.build_schema(session.draft, **kwargs)

    @staticmethod
    def _status_for(draft) -> ParseSessionStatus:
        if draft.ready_for_schema:
            return ParseSessionStatus.READY_FOR_SCHEMA
        return ParseSessionStatus.WAITING_FOR_CLARIFICATION

    @staticmethod
    def _stable_session_id(source: str) -> str:
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:20]
        return f"parse_{digest}"

    @staticmethod
    def _hashable_display(value: Any) -> Any:
        if isinstance(value, (dict, list)):
            return repr(value)
        return value