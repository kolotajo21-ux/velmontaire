from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from .ai_builder import (
    AIStrategyBuilder,
    AIStrategyBuilderResult,
)
from .guarded_compiler import (
    GuardedCompilationResult,
    GuardedStrategyCompiler,
)
from .module_binding import (
    AIStrategyModuleBinder,
    StrategyModuleBindingResult,
)
from .module_resolver import (
    StrategyCapabilityRequirement,
    StrategyCapabilityResolutionReport,
    StrategyCapabilityResolver,
)


class AICompilationPipelineStatus(str, Enum):
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    BLOCKED_CAPABILITY = "BLOCKED_CAPABILITY"
    BLOCKED_BINDING = "BLOCKED_BINDING"
    BLOCKED_COMPILATION = "BLOCKED_COMPILATION"
    READY = "READY"


@dataclass(slots=True)
class AICompilationPipelineResult:
    status: AICompilationPipelineStatus
    builder_result: AIStrategyBuilderResult
    requirements: list[StrategyCapabilityRequirement] = field(default_factory=list)
    capability_report: StrategyCapabilityResolutionReport | None = None
    binding_result: StrategyModuleBindingResult | None = None
    compilation_result: GuardedCompilationResult | None = None
    blockers: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return (
            self.status == AICompilationPipelineStatus.READY
            and self.compilation_result is not None
            and self.compilation_result.success
        )

    @property
    def compiled(self) -> Any | None:
        if not self.ready or self.compilation_result is None:
            return None

        inner = self.compilation_result.compilation_result
        return getattr(inner, "compiled", None)

    @property
    def questions(self) -> list[str]:
        return list(self.builder_result.questions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "status": self.status.value,
            "builder_result": self.builder_result.to_dict(),
            "requirements": [
                item.to_dict()
                for item in self.requirements
            ],
            "capability_report": (
                self.capability_report.to_dict()
                if self.capability_report is not None
                else None
            ),
            "binding_result": (
                self.binding_result.to_dict()
                if self.binding_result is not None
                else None
            ),
            "compilation_result": (
                self.compilation_result.to_dict()
                if self.compilation_result is not None
                else None
            ),
            "blockers": list(self.blockers),
            "questions": self.questions,
        }


class AIStrategyCompilationPipeline:
    """
    Day 87 production integration pipeline.

    AI text
      -> Day 82/83 builder + clarification
      -> capability requirements
      -> Day 84 resolver
      -> Day 85 explicit module binding
      -> Day 86 guarded compiler
      -> compiled strategy

    No downstream stage runs before the previous stage is READY.
    """

    def __init__(
        self,
        *,
        registry: Any,
        builder: AIStrategyBuilder | None = None,
        requirement_factory: Callable[
            [Any],
            list[StrategyCapabilityRequirement],
        ],
        resolver: StrategyCapabilityResolver | None = None,
        binder: AIStrategyModuleBinder | None = None,
        compiler: GuardedStrategyCompiler | None = None,
    ) -> None:
        self.registry = registry
        self.builder = builder or AIStrategyBuilder()
        self.requirement_factory = requirement_factory
        self.resolver = resolver or StrategyCapabilityResolver(
            registry=registry
        )
        self.binder = binder or AIStrategyModuleBinder()
        self.compiler = compiler or GuardedStrategyCompiler(
            registry=registry
        )

    def start(
        self,
        text: str,
        **builder_kwargs: Any,
    ) -> AICompilationPipelineResult:
        builder_result = self.builder.start(
            text,
            **builder_kwargs,
        )

        return self._continue(
            builder_result
        )

    def answer(
        self,
        result: AICompilationPipelineResult,
        answers: dict[str, Any],
        *,
        overwrite: bool = False,
        **builder_kwargs: Any,
    ) -> AICompilationPipelineResult:
        builder_result = self.builder.answer(
            result.builder_result,
            answers,
            overwrite=overwrite,
            **builder_kwargs,
        )

        return self._continue(
            builder_result
        )

    def resolve_conflict(
        self,
        result: AICompilationPipelineResult,
        path: str,
        value: Any,
        **builder_kwargs: Any,
    ) -> AICompilationPipelineResult:
        builder_result = self.builder.resolve_conflict(
            result.builder_result,
            path,
            value,
            **builder_kwargs,
        )

        return self._continue(
            builder_result
        )

    def require_compiled(
        self,
        result: AICompilationPipelineResult,
    ) -> Any:
        if not result.ready:
            raise ValueError(
                "ai_strategy_compilation_pipeline_not_ready"
            )

        compiled = result.compiled

        if compiled is None:
            raise ValueError(
                "compiled_strategy_missing"
            )

        return compiled

    def _continue(
        self,
        builder_result: AIStrategyBuilderResult,
    ) -> AICompilationPipelineResult:
        if not builder_result.ready:
            return AICompilationPipelineResult(
                status=(
                    AICompilationPipelineStatus
                    .NEEDS_CLARIFICATION
                ),
                builder_result=builder_result,
                blockers=list(
                    builder_result.blockers
                ),
            )

        schema = self.builder.require_ready_schema(
            builder_result
        )

        try:
            requirements = list(
                self.requirement_factory(
                    schema
                )
            )
        except Exception as exc:
            return AICompilationPipelineResult(
                status=(
                    AICompilationPipelineStatus
                    .BLOCKED_CAPABILITY
                ),
                builder_result=builder_result,
                blockers=[
                    "capability_requirement_factory_exception:"
                    f"{type(exc).__name__}:{exc}"
                ],
            )

        capability_report = self.resolver.resolve(
            requirements
        )

        if not capability_report.ready:
            return AICompilationPipelineResult(
                status=(
                    AICompilationPipelineStatus
                    .BLOCKED_CAPABILITY
                ),
                builder_result=builder_result,
                requirements=requirements,
                capability_report=capability_report,
                blockers=[
                    (
                        "capability:"
                        f"{item.status.value}:"
                        f"{item.requirement.normalized_capability()}"
                    )
                    for item in capability_report.blockers
                ],
            )

        binding_result = self.binder.bind(
            schema=schema,
            resolution_report=capability_report,
        )

        if not binding_result.ready:
            return AICompilationPipelineResult(
                status=(
                    AICompilationPipelineStatus
                    .BLOCKED_BINDING
                ),
                builder_result=builder_result,
                requirements=requirements,
                capability_report=capability_report,
                binding_result=binding_result,
                blockers=list(
                    binding_result.blockers
                ),
            )

        compilation_result = self.compiler.compile(
            schema=schema,
            binding=binding_result,
        )

        if not compilation_result.success:
            return AICompilationPipelineResult(
                status=(
                    AICompilationPipelineStatus
                    .BLOCKED_COMPILATION
                ),
                builder_result=builder_result,
                requirements=requirements,
                capability_report=capability_report,
                binding_result=binding_result,
                compilation_result=compilation_result,
                blockers=[
                    compilation_result.reason
                ],
            )

        return AICompilationPipelineResult(
            status=AICompilationPipelineStatus.READY,
            builder_result=builder_result,
            requirements=requirements,
            capability_report=capability_report,
            binding_result=binding_result,
            compilation_result=compilation_result,
        )