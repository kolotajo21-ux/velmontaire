from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .dependencies import (
    DependencyParseResult,
    StrategyDependency,
)
from .models import ParseSessionStatus
from .schema_builder import (
    StrategyBuildResult,
    StrategySchemaBuilder,
)
from .semantic_validator import (
    SemanticValidationResult,
    StrategySemanticValidator,
)


class AIStrategyBuilderStatus(str, Enum):
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    READY = "READY"
    BLOCKED_SEMANTIC = "BLOCKED_SEMANTIC"
    INVALID = "INVALID"


@dataclass(slots=True)
class AIStrategyBuilderResult:
    build: StrategyBuildResult
    status: AIStrategyBuilderStatus

    semantic_validation: SemanticValidationResult | None = None

    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return (
            self.status == AIStrategyBuilderStatus.READY
            and self.build.schema is not None
            and not self.blockers
        )

    @property
    def questions(self) -> list[str]:
        return list(self.build.questions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "status": self.status.value,
            "build": self.build.to_dict(),
            "semantic_validation": (
                self.semantic_validation.to_dict()
                if self.semantic_validation is not None
                else None
            ),
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "questions": self.questions,
        }


class AIStrategyBuilder:
    """
    Day 82 production-facing AI Strategy Builder foundation.

    Existing parser stack remains authoritative:

        raw text
          -> StrategySchemaBuilder
          -> clarification session
          -> StrategySchema
          -> semantic validation
          -> READY / blocked result

    Safety rules:
    - missing parser information is never invented;
    - clarification questions are surfaced as-is;
    - INVALID parse sessions never proceed;
    - semantic issues block readiness;
    - semantic dependency input is explicit rather than guessed.
    """

    def __init__(
        self,
        *,
        schema_builder: StrategySchemaBuilder | None = None,
        semantic_validator: StrategySemanticValidator | None = None,
    ) -> None:
        self.schema_builder = (
            schema_builder
            if schema_builder is not None
            else StrategySchemaBuilder()
        )

        self.semantic_validator = (
            semantic_validator
            if semantic_validator is not None
            else StrategySemanticValidator()
        )

    def start(
        self,
        text: str,
        *,
        semantic_dependencies: (
            DependencyParseResult
            | list[StrategyDependency]
            | None
        ) = None,
        session_id: str | None = None,
        strategy_id: str | None = None,
        name: str = "Parsed Strategy",
        version: str = "1.0",
    ) -> AIStrategyBuilderResult:
        build = self.schema_builder.start(
            text,
            session_id=session_id,
            strategy_id=strategy_id,
            name=name,
            version=version,
        )

        return self._finalize(
            build,
            semantic_dependencies=semantic_dependencies,
        )

    def answer(
        self,
        result: AIStrategyBuilderResult,
        answers: dict[str, Any],
        *,
        semantic_dependencies: (
            DependencyParseResult
            | list[StrategyDependency]
            | None
        ) = None,
        overwrite: bool = False,
        strategy_id: str | None = None,
        name: str = "Parsed Strategy",
        version: str = "1.0",
    ) -> AIStrategyBuilderResult:
        build = self.schema_builder.answer(
            result.build,
            answers,
            overwrite=overwrite,
            strategy_id=strategy_id,
            name=name,
            version=version,
        )

        return self._finalize(
            build,
            semantic_dependencies=semantic_dependencies,
        )

    def resolve_conflict(
        self,
        result: AIStrategyBuilderResult,
        path: str,
        value: Any,
        *,
        semantic_dependencies: (
            DependencyParseResult
            | list[StrategyDependency]
            | None
        ) = None,
        strategy_id: str | None = None,
        name: str = "Parsed Strategy",
        version: str = "1.0",
    ) -> AIStrategyBuilderResult:
        build = self.schema_builder.resolve_conflict(
            result.build,
            path,
            value,
            strategy_id=strategy_id,
            name=name,
            version=version,
        )

        return self._finalize(
            build,
            semantic_dependencies=semantic_dependencies,
        )

    def require_ready_schema(
        self,
        result: AIStrategyBuilderResult,
    ):
        if not result.ready:
            raise ValueError(
                "ai_strategy_builder_not_ready"
            )

        return self.schema_builder.require_schema(
            result.build
        )

    def _finalize(
        self,
        build: StrategyBuildResult,
        *,
        semantic_dependencies: (
            DependencyParseResult
            | list[StrategyDependency]
            | None
        ),
    ) -> AIStrategyBuilderResult:
        session = build.session

        if session.status == ParseSessionStatus.INVALID:
            return AIStrategyBuilderResult(
                build=build,
                status=AIStrategyBuilderStatus.INVALID,
                blockers=[
                    session.invalid_reason
                    or "strategy_parse_session_invalid"
                ],
            )

        if build.schema is None:
            blockers = []

            if session.draft.conflicts:
                blockers.extend(
                    f"conflict:{path}"
                    for path in sorted(
                        session.draft.conflicts
                    )
                )

            blockers.extend(
                f"unresolved:{path}"
                for path in session.draft.unresolved_fields
            )

            return AIStrategyBuilderResult(
                build=build,
                status=(
                    AIStrategyBuilderStatus
                    .NEEDS_CLARIFICATION
                ),
                blockers=blockers,
            )

        semantic = self._semantic_validation(
            semantic_dependencies
        )

        if not semantic.valid:
            return AIStrategyBuilderResult(
                build=build,
                status=(
                    AIStrategyBuilderStatus
                    .BLOCKED_SEMANTIC
                ),
                semantic_validation=semantic,
                blockers=[
                    self._issue_blocker(issue)
                    for issue in semantic.issues
                ],
            )

        return AIStrategyBuilderResult(
            build=build,
            status=AIStrategyBuilderStatus.READY,
            semantic_validation=semantic,
        )

    def _semantic_validation(
        self,
        dependencies: (
            DependencyParseResult
            | list[StrategyDependency]
            | None
        ),
    ) -> SemanticValidationResult:
        # No dependencies means there is nothing semantic to validate
        # at this layer. We do not invent dependency relations.
        if dependencies is None:
            return SemanticValidationResult(
                valid=True,
                issues=[],
            )

        return self.semantic_validator.validate(
            dependencies
        )

    @staticmethod
    def _issue_blocker(issue: Any) -> str:
        path = getattr(
            issue,
            "path",
            None,
        )

        code = str(
            getattr(
                issue,
                "code",
                "SEMANTIC_ISSUE",
            )
        )

        if path:
            return f"semantic:{path}:{code}"

        return f"semantic:{code}"