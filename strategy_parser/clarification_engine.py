from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .ai_builder import (
    AIStrategyBuilder,
    AIStrategyBuilderResult,
    AIStrategyBuilderStatus,
)


@dataclass(slots=True)
class ClarificationPrompt:
    question_id: str
    path: str
    question: str
    reason: str
    required: bool
    conflict_values: list[Any] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "path": self.path,
            "question": self.question,
            "reason": self.reason,
            "required": bool(self.required),
            "conflict_values": list(self.conflict_values),
        }


@dataclass(slots=True)
class ClarificationSubmissionResult:
    accepted: bool
    result: AIStrategyBuilderResult
    accepted_paths: list[str] = field(default_factory=list)
    rejected_keys: list[str] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": bool(self.accepted),
            "result": self.result.to_dict(),
            "accepted_paths": list(self.accepted_paths),
            "rejected_keys": list(self.rejected_keys),
            "reason": self.reason,
        }


class AIStrategyClarificationEngine:
    """
    Day 83 strict clarification layer.

    It converts parser questions into a user-facing contract and only accepts
    answers for fields that are currently unresolved/conflicting.

    Safety:
    - missing answers are never invented;
    - unknown keys are rejected;
    - empty answers are rejected;
    - conflicts are resolved explicitly;
    - already-resolved fields are never silently overwritten here.
    """

    def __init__(
        self,
        *,
        builder: AIStrategyBuilder,
    ) -> None:
        self.builder = builder

    def prompts(
        self,
        result: AIStrategyBuilderResult,
    ) -> list[ClarificationPrompt]:
        if result.status != AIStrategyBuilderStatus.NEEDS_CLARIFICATION:
            return []

        draft = result.build.session.draft

        return [
            ClarificationPrompt(
                question_id=question.question_id,
                path=question.path,
                question=question.question,
                reason=question.reason,
                required=question.required,
                conflict_values=list(
                    draft.conflicts.get(
                        question.path,
                        [],
                    )
                ),
            )
            for question in draft.questions
        ]

    def submit(
        self,
        result: AIStrategyBuilderResult,
        answers: dict[str, Any],
        *,
        semantic_dependencies: Any = None,
        strategy_id: str | None = None,
        name: str = "Parsed Strategy",
        version: str = "1.0",
    ) -> ClarificationSubmissionResult:
        prompts = self.prompts(result)

        if not prompts:
            return ClarificationSubmissionResult(
                accepted=False,
                result=result,
                reason="clarification_not_required",
            )

        by_question_id = {
            prompt.question_id: prompt
            for prompt in prompts
        }
        by_path = {
            prompt.path: prompt
            for prompt in prompts
        }

        mapped: dict[str, Any] = {}
        rejected: list[str] = []

        for raw_key, value in dict(answers or {}).items():
            key = str(raw_key)

            prompt = (
                by_question_id.get(key)
                or by_path.get(key)
            )

            if prompt is None:
                rejected.append(key)
                continue

            if value is None or value == "":
                rejected.append(key)
                continue

            mapped[prompt.path] = value

        if rejected:
            return ClarificationSubmissionResult(
                accepted=False,
                result=result,
                rejected_keys=rejected,
                reason="clarification_answers_invalid",
            )

        if not mapped:
            return ClarificationSubmissionResult(
                accepted=False,
                result=result,
                reason="clarification_answers_missing",
            )

        current = result
        accepted_paths: list[str] = []

        for path, value in mapped.items():
            conflicts = set(
                current.build.session.draft.conflicts
            )

            if path in conflicts:
                current = self.builder.resolve_conflict(
                    current,
                    path,
                    value,
                    semantic_dependencies=semantic_dependencies,
                    strategy_id=strategy_id,
                    name=name,
                    version=version,
                )
            else:
                current = self.builder.answer(
                    current,
                    {path: value},
                    semantic_dependencies=semantic_dependencies,
                    overwrite=False,
                    strategy_id=strategy_id,
                    name=name,
                    version=version,
                )

            accepted_paths.append(path)

        return ClarificationSubmissionResult(
            accepted=True,
            result=current,
            accepted_paths=accepted_paths,
            reason=(
                "clarification_completed"
                if current.ready
                else "clarification_partially_completed"
            ),
        )

    def require_no_pending_questions(
        self,
        result: AIStrategyBuilderResult,
    ) -> None:
        if self.prompts(result):
            raise ValueError(
                "strategy_clarification_required"
            )