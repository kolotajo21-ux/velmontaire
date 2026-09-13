from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from strategy_schema import StrategySchema

from .complex_conditions import ComplexConditionParseResult, ComplexConditionParser
from .dependencies import DependencyParseResult, StrategyDependencyResolver
from .models import ParseSessionStatus
from .references import ReferenceParseResult, StrategyReferenceParser
from .schema_builder import StrategyBuildResult, StrategySchemaBuilder
from .semantic_validator import SemanticValidationResult, StrategySemanticValidator


@dataclass(slots=True)
class StrategyAssemblyResult:
    build: StrategyBuildResult
    complex_condition: ComplexConditionParseResult | None = None
    references: ReferenceParseResult | None = None
    dependencies: DependencyParseResult | None = None
    semantics: SemanticValidationResult | None = None
    blockers: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return (
            self.build.schema is not None
            and self.complex_condition is not None
            and not self.complex_condition.ambiguous
            and self.references is not None
            and self.references.valid
            and self.dependencies is not None
            and self.dependencies.valid
            and self.semantics is not None
            and self.semantics.valid
            and not self.blockers
        )

    @property
    def schema(self) -> StrategySchema | None:
        return self.build.schema if self.ready else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "blockers": list(self.blockers),
            "build": self.build.to_dict(),
            "complex_condition": (
                self.complex_condition.to_dict()
                if self.complex_condition is not None else None
            ),
            "references": {
                "valid": self.references.valid,
                "references": [x.to_dict() for x in self.references.references],
                "unresolved": list(self.references.unresolved),
            } if self.references is not None else None,
            "dependencies": {
                "valid": self.dependencies.valid,
                "dependencies": [x.to_dict() for x in self.dependencies.dependencies],
                "unresolved": list(self.dependencies.unresolved),
            } if self.dependencies is not None else None,
            "semantics": (
                self.semantics.to_dict()
                if self.semantics is not None else None
            ),
        }


class StrategyParserAssembly:
    """Day 50 end-to-end conservative parser assembly."""

    def __init__(self) -> None:
        self.builder = StrategySchemaBuilder()
        self.complex_parser = ComplexConditionParser()
        self.reference_parser = StrategyReferenceParser()
        self.dependency_resolver = StrategyDependencyResolver()
        self.semantic_validator = StrategySemanticValidator()

    def start(
        self,
        text: str,
        *,
        strategy_id: str | None = None,
        name: str = "Parsed Strategy",
        version: str = "1.0",
    ) -> StrategyAssemblyResult:
        build = self.builder.start(
            text,
            strategy_id=strategy_id,
            name=name,
            version=version,
        )
        return self._assemble(build)

    def answer(
        self,
        result: StrategyAssemblyResult,
        answers: dict[str, Any],
        *,
        overwrite: bool = False,
        strategy_id: str | None = None,
        name: str = "Parsed Strategy",
        version: str = "1.0",
    ) -> StrategyAssemblyResult:
        self.builder.answer(
            result.build,
            answers,
            overwrite=overwrite,
            strategy_id=strategy_id,
            name=name,
            version=version,
        )
        return self._assemble(result.build)

    def _assemble(self, build: StrategyBuildResult) -> StrategyAssemblyResult:
        result = StrategyAssemblyResult(build=build)

        if build.session.status == ParseSessionStatus.INVALID:
            result.blockers.append("parse_session_invalid")
            return result

        condition_text = build.session.draft.value("entry.condition")
        if condition_text:
            result.complex_condition = self.complex_parser.parse(
                str(condition_text),
                condition_id="entry_condition_1",
            )
            if result.complex_condition.ambiguous:
                result.blockers.append(
                    result.complex_condition.reason or "complex_condition_ambiguous"
                )
        else:
            result.blockers.append("entry.condition")

        source = build.session.original_text
        result.references = self.reference_parser.parse(source)
        result.blockers.extend(result.references.unresolved)

        lines = [
            part.strip()
            for part in source.replace("\r", "\n").split("\n")
            if part.strip()
        ]
        if len(lines) <= 1:
            lines = [
                part.strip()
                for part in source.replace(";", ".").split(".")
                if part.strip()
            ]

        result.dependencies = self.dependency_resolver.resolve_lines(lines)
        result.blockers.extend(result.dependencies.unresolved)

        result.semantics = self.semantic_validator.validate(result.dependencies)
        if not result.semantics.valid:
            result.blockers.extend(
                issue.code for issue in result.semantics.issues
            )

        # Replace the old Day 42 single EVENT with the fully parsed condition tree.
        if (
            build.schema is not None
            and result.complex_condition is not None
            and not result.complex_condition.ambiguous
        ):
            build.schema.rules.entries[0].conditions = result.complex_condition.condition
            build.schema.metadata["parser_assembly"] = "day50"
            build.schema.metadata["dependency_graph"] = [
                x.to_dict() for x in result.dependencies.dependencies
            ]
            build.schema.metadata["reference_graph"] = [
                x.to_dict() for x in result.references.references
            ]

            validation = build.schema.validate()
            if not validation.valid:
                result.blockers.append("assembled_schema_validation_failed")

        result.blockers = list(dict.fromkeys(result.blockers))
        return result