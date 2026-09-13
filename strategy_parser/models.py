from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ParserFieldStatus(str, Enum):
    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"
    CONFLICT = "CONFLICT"


class ParseSessionStatus(str, Enum):
    WAITING_FOR_CLARIFICATION = "WAITING_FOR_CLARIFICATION"
    READY_FOR_SCHEMA = "READY_FOR_SCHEMA"
    INVALID = "INVALID"


@dataclass(slots=True)
class ParsedFact:
    path: str
    value: Any
    source_text: str
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "value": self.value,
            "source_text": self.source_text,
            "confidence": float(self.confidence),
        }


@dataclass(slots=True)
class ParserQuestion:
    question_id: str
    path: str
    question: str
    reason: str
    required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "path": self.path,
            "question": self.question,
            "reason": self.reason,
            "required": bool(self.required),
        }


@dataclass(slots=True)
class StrategyParseDraft:
    source_text: str
    facts: dict[str, ParsedFact] = field(default_factory=dict)
    unresolved_fields: list[str] = field(default_factory=list)
    conflicts: dict[str, list[Any]] = field(default_factory=dict)
    questions: list[ParserQuestion] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def ready_for_schema(self) -> bool:
        return not self.unresolved_fields and not self.conflicts

    def value(self, path: str, default: Any = None) -> Any:
        fact = self.facts.get(path)
        return fact.value if fact is not None else default

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_text": self.source_text,
            "facts": {key: fact.to_dict() for key, fact in self.facts.items()},
            "unresolved_fields": list(self.unresolved_fields),
            "conflicts": {key: list(values) for key, values in self.conflicts.items()},
            "questions": [question.to_dict() for question in self.questions],
            "metadata": dict(self.metadata),
            "ready_for_schema": self.ready_for_schema,
        }


@dataclass(slots=True)
class ClarificationTurn:
    turn_index: int
    answers: dict[str, Any]
    accepted_paths: list[str] = field(default_factory=list)
    conflict_paths: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_index": self.turn_index,
            "answers": dict(self.answers),
            "accepted_paths": list(self.accepted_paths),
            "conflict_paths": list(self.conflict_paths),
        }


@dataclass(slots=True)
class StrategyParseSession:
    session_id: str
    original_text: str
    draft: StrategyParseDraft
    status: ParseSessionStatus
    clarification_history: list[ClarificationTurn] = field(default_factory=list)
    invalid_reason: str | None = None

    @property
    def ready_for_schema(self) -> bool:
        return self.status == ParseSessionStatus.READY_FOR_SCHEMA and self.draft.ready_for_schema

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "original_text": self.original_text,
            "draft": self.draft.to_dict(),
            "status": self.status.value,
            "clarification_history": [x.to_dict() for x in self.clarification_history],
            "invalid_reason": self.invalid_reason,
            "ready_for_schema": self.ready_for_schema,
        }