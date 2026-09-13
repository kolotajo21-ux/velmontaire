from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
from typing import Any

from .unknown_concept_detector import ConceptDetection, ConceptStatus


class ClarificationEngineError(ValueError):
    """Fail-closed clarification workflow error."""


class ClarificationKind(str, Enum):
    CONFIRM_SUGGESTION = "CONFIRM_SUGGESTION"
    DEFINE_UNKNOWN_CONCEPT = "DEFINE_UNKNOWN_CONCEPT"
    DEFINE_BOUNDARIES = "DEFINE_BOUNDARIES"


class AnswerType(str, Enum):
    YES_NO = "YES_NO"
    TEXT = "TEXT"
    SINGLE_CHOICE = "SINGLE_CHOICE"


class ClarificationStatus(str, Enum):
    OPEN = "OPEN"
    ANSWERED = "ANSWERED"


@dataclass(frozen=True, slots=True)
class ClarificationQuestion:
    question_id: str
    source_term: str
    normalized_term: str
    kind: ClarificationKind
    answer_type: AnswerType
    prompt: str
    suggestions: tuple[str, ...] = ()
    choices: tuple[str, ...] = ()
    status: ClarificationStatus = ClarificationStatus.OPEN

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "source_term": self.source_term,
            "normalized_term": self.normalized_term,
            "kind": self.kind.value,
            "answer_type": self.answer_type.value,
            "prompt": self.prompt,
            "suggestions": list(self.suggestions),
            "choices": list(self.choices),
            "status": self.status.value,
        }


@dataclass(frozen=True, slots=True)
class ClarificationAnswer:
    question_id: str
    source_term: str
    kind: ClarificationKind
    value: Any
    resolved_concept: str | None = None
    structured_definition: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "source_term": self.source_term,
            "kind": self.kind.value,
            "value": self.value,
            "resolved_concept": self.resolved_concept,
            "structured_definition": dict(self.structured_definition),
        }


class AIClarificationEngine:
    """
    Converts unknown/ambiguous concept detections into deterministic questions
    and stores answers as structured data.

    It does not invent a definition for an unknown trading concept.
    """

    BOUNDARY_CHOICES = (
        "PRICE",
        "INDICATOR",
        "MARKET_STRUCTURE",
        "TIME_SESSION",
        "CANDLE_PATTERN",
        "OTHER",
    )

    def build_question(
        self,
        detection: ConceptDetection,
    ) -> ClarificationQuestion | None:
        if detection.status == ConceptStatus.KNOWN:
            return None

        if detection.status == ConceptStatus.NEEDS_CLARIFICATION:
            if not detection.suggestions:
                raise ClarificationEngineError(
                    "clarification_suggestions_required"
                )
            suggestion = detection.suggestions[0]
            return ClarificationQuestion(
                question_id=self._question_id(
                    detection.normalized,
                    ClarificationKind.CONFIRM_SUGGESTION,
                ),
                source_term=detection.source,
                normalized_term=detection.normalized,
                kind=ClarificationKind.CONFIRM_SUGGESTION,
                answer_type=AnswerType.YES_NO,
                prompt=(
                    f'Возможно, вы имели в виду "{suggestion}"?'
                ),
                suggestions=detection.suggestions,
                choices=("YES", "NO"),
            )

        if detection.status == ConceptStatus.UNKNOWN_CONCEPT:
            return ClarificationQuestion(
                question_id=self._question_id(
                    detection.normalized,
                    ClarificationKind.DEFINE_UNKNOWN_CONCEPT,
                ),
                source_term=detection.source,
                normalized_term=detection.normalized,
                kind=ClarificationKind.DEFINE_UNKNOWN_CONCEPT,
                answer_type=AnswerType.TEXT,
                prompt=(
                    f'Термин "{detection.source}" пока не определён. '
                    "Опишите точное правило: когда условие считается выполненным?"
                ),
            )

        raise ClarificationEngineError(
            f"unsupported_concept_status:{detection.status}"
        )

    def build_boundary_question(
        self,
        *,
        source_term: str,
    ) -> ClarificationQuestion:
        term = str(source_term or "").strip()
        if not term:
            raise ClarificationEngineError("source_term_required")
        normalized = self._normalize(term)
        return ClarificationQuestion(
            question_id=self._question_id(
                normalized,
                ClarificationKind.DEFINE_BOUNDARIES,
            ),
            source_term=term,
            normalized_term=normalized,
            kind=ClarificationKind.DEFINE_BOUNDARIES,
            answer_type=AnswerType.SINGLE_CHOICE,
            prompt=f'Что определяет границы "{term}"?',
            choices=self.BOUNDARY_CHOICES,
        )

    def answer(
        self,
        question: ClarificationQuestion,
        value: Any,
        *,
        structured_definition: dict[str, Any] | None = None,
    ) -> ClarificationAnswer:
        if not isinstance(question, ClarificationQuestion):
            raise ClarificationEngineError("invalid_clarification_question")

        if question.answer_type == AnswerType.YES_NO:
            normalized_answer = str(value or "").strip().upper()
            yes = {"YES", "Y", "ДА", "ТАК"}
            no = {"NO", "N", "НЕТ", "НІ"}
            if normalized_answer in yes:
                if not question.suggestions:
                    raise ClarificationEngineError(
                        "clarification_suggestions_required"
                    )
                return ClarificationAnswer(
                    question_id=question.question_id,
                    source_term=question.source_term,
                    kind=question.kind,
                    value="YES",
                    resolved_concept=question.suggestions[0],
                )
            if normalized_answer in no:
                return ClarificationAnswer(
                    question_id=question.question_id,
                    source_term=question.source_term,
                    kind=question.kind,
                    value="NO",
                )
            raise ClarificationEngineError("yes_no_answer_required")

        if question.answer_type == AnswerType.SINGLE_CHOICE:
            normalized_answer = self._normalize(str(value or ""))
            if normalized_answer not in question.choices:
                raise ClarificationEngineError(
                    f"unsupported_clarification_choice:{value}"
                )
            return ClarificationAnswer(
                question_id=question.question_id,
                source_term=question.source_term,
                kind=question.kind,
                value=normalized_answer,
                structured_definition={
                    "boundary_type": normalized_answer,
                    **dict(structured_definition or {}),
                },
            )

        text = str(value or "").strip()
        if not text:
            raise ClarificationEngineError(
                "clarification_text_required"
            )

        definition = dict(structured_definition or {})
        definition.setdefault("description", text)

        return ClarificationAnswer(
            question_id=question.question_id,
            source_term=question.source_term,
            kind=question.kind,
            value=text,
            structured_definition=definition,
        )

    def unresolved(
        self,
        questions: list[ClarificationQuestion],
        answers: list[ClarificationAnswer],
    ) -> list[ClarificationQuestion]:
        answered_ids = {x.question_id for x in answers}
        return [
            q for q in questions
            if q.question_id not in answered_ids
        ]

    @staticmethod
    def _normalize(value: str) -> str:
        return "_".join(
            str(value or "").strip().upper().replace("-", " ").split()
        )

    @staticmethod
    def _question_id(
        normalized_term: str,
        kind: ClarificationKind,
    ) -> str:
        raw = f"{normalized_term}|{kind.value}".encode("utf-8")
        return "CQ_" + sha256(raw).hexdigest()[:16].upper()
