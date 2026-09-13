from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .capability_dependency_graph import (
    CapabilityDependencyError,
    CapabilityDependencyGraph,
    DependencyPlan,
)
from .capability_registry import (
    CapabilityRegistryError,
    CapabilityVersion,
    CustomCapabilityRegistry,
)
from .custom_rule_builder import (
    CompiledCustomRule,
    CustomRuleBuilder,
    CustomRuleBuilderError,
)


class CustomCapabilityCompilerError(ValueError):
    """Fail-closed end-to-end custom capability compilation error."""


@dataclass(frozen=True, slots=True)
class CapabilityCompilationResult:
    capability: CapabilityVersion
    compiled_rule: CompiledCustomRule
    dependency_plan: DependencyPlan
    execution_plan: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability.to_dict(),
            "compiled_rule": self.compiled_rule.to_dict(),
            "dependency_plan": self.dependency_plan.to_dict(),
            "execution_plan": dict(self.execution_plan),
        }


class CustomCapabilityCompiler:
    """
    End-to-end compiler:
        clarified structured definition
        -> compiled custom rule
        -> versioned registry capability
        -> dependency graph
        -> immutable execution plan

    Existing capabilities are reused idempotently.
    Changed definitions require explicit version creation.
    Any unresolved primitive/dependency blocks compilation.
    """

    def __init__(
        self,
        *,
        supported_primitives: Iterable[str],
        registry: CustomCapabilityRegistry | None = None,
    ) -> None:
        self.primitives = {
            self._norm(x)
            for x in supported_primitives
            if str(x).strip()
        }
        if not self.primitives:
            raise CustomCapabilityCompilerError(
                "supported_primitives_required"
            )

        self.registry = registry or CustomCapabilityRegistry()
        self.builder = CustomRuleBuilder(self.primitives)
        self.graph = CapabilityDependencyGraph(
            self.registry,
            self.primitives,
        )

    def compile_new(
        self,
        *,
        name: str,
        structured_definition: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> CapabilityCompilationResult:
        try:
            rule = self.builder.from_structured_definition(
                name=name,
                structured_definition=structured_definition,
            )
            capability = self.registry.register(
                rule,
                metadata=metadata,
            )
            return self._finalize(capability, rule)
        except (
            CustomRuleBuilderError,
            CapabilityRegistryError,
            CapabilityDependencyError,
        ) as exc:
            raise CustomCapabilityCompilerError(
                f"capability_compile_failed:{exc}"
            ) from exc

    def compile_version(
        self,
        *,
        capability_id: str,
        name: str,
        structured_definition: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> CapabilityCompilationResult:
        try:
            rule = self.builder.from_structured_definition(
                name=name,
                structured_definition=structured_definition,
            )
            capability = self.registry.create_version(
                capability_id,
                rule,
                metadata=metadata,
            )
            return self._finalize(capability, rule)
        except (
            CustomRuleBuilderError,
            CapabilityRegistryError,
            CapabilityDependencyError,
        ) as exc:
            raise CustomCapabilityCompilerError(
                f"capability_compile_failed:{exc}"
            ) from exc

    def compile_registered(
        self,
        reference: str,
        *,
        version: int | None = None,
    ) -> dict[str, Any]:
        try:
            capability = self.registry.resolve(
                reference,
                version=version,
                require_enabled=True,
            )
            plan = self.graph.build_plan(
                capability.capability_id,
                version=capability.version,
            )
            return self._execution_plan(plan)
        except (
            CapabilityRegistryError,
            CapabilityDependencyError,
        ) as exc:
            raise CustomCapabilityCompilerError(
                f"capability_compile_failed:{exc}"
            ) from exc

    def _finalize(
        self,
        capability: CapabilityVersion,
        rule: CompiledCustomRule,
    ) -> CapabilityCompilationResult:
        plan = self.graph.build_plan(
            capability.capability_id,
            version=capability.version,
        )
        execution = self._execution_plan(plan)
        return CapabilityCompilationResult(
            capability=capability,
            compiled_rule=rule,
            dependency_plan=plan,
            execution_plan=execution,
        )

    @staticmethod
    def _execution_plan(plan: DependencyPlan) -> dict[str, Any]:
        nodes = []
        for node in plan.execution_order:
            nodes.append({
                "capability_id": node.capability_id,
                "name": node.name,
                "version": node.version,
                "rule_id": node.rule_id,
            })

        return {
            "root_capability_id": plan.root_capability_id,
            "root_version": plan.root_version,
            "execution_order": nodes,
            "immutable": True,
        }

    @staticmethod
    def _norm(value: str) -> str:
        return "_".join(
            str(value or "")
            .strip()
            .upper()
            .replace("-", " ")
            .split()
        )
