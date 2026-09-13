from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .capability_registry import (
    CapabilityRegistryError,
    CapabilityVersion,
    CustomCapabilityRegistry,
)


class CapabilityDependencyError(ValueError):
    """Fail-closed dependency graph error."""


@dataclass(frozen=True, slots=True)
class CapabilityDependency:
    reference: str
    version: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference": self.reference,
            "version": self.version,
        }


@dataclass(frozen=True, slots=True)
class DependencyNode:
    capability_id: str
    name: str
    version: int
    rule_id: str
    dependencies: tuple[CapabilityDependency, ...] = field(
        default_factory=tuple
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "name": self.name,
            "version": self.version,
            "rule_id": self.rule_id,
            "dependencies": [
                x.to_dict() for x in self.dependencies
            ],
        }


@dataclass(frozen=True, slots=True)
class DependencyPlan:
    root_capability_id: str
    root_version: int
    execution_order: tuple[DependencyNode, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "root_capability_id": self.root_capability_id,
            "root_version": self.root_version,
            "execution_order": [
                x.to_dict() for x in self.execution_order
            ],
        }


class CapabilityDependencyGraph:
    """
    Resolves nested custom capabilities into a deterministic execution order.

    Supports:
    - nested capability dependencies;
    - explicit dependency version pinning;
    - missing dependency detection;
    - cycle detection;
    - disabled dependency blocking;
    - topological dependency-first execution order.
    """

    def __init__(
        self,
        registry: CustomCapabilityRegistry,
        primitive_names: Iterable[str],
    ) -> None:
        if not isinstance(registry, CustomCapabilityRegistry):
            raise CapabilityDependencyError(
                "custom_capability_registry_required"
            )
        self.registry = registry
        self.primitives = {
            self._norm(x)
            for x in primitive_names
            if str(x).strip()
        }
        if not self.primitives:
            raise CapabilityDependencyError(
                "primitive_names_required"
            )

    def build_plan(
        self,
        root_reference: str,
        *,
        version: int | None = None,
    ) -> DependencyPlan:
        root = self._resolve_capability(
            root_reference,
            version=version,
        )

        visiting: list[str] = []
        visited: set[tuple[str, int]] = set()
        ordered: list[DependencyNode] = []

        def visit(item: CapabilityVersion) -> None:
            key = (item.capability_id, item.version)
            if key in visited:
                return

            if item.capability_id in visiting:
                start = visiting.index(item.capability_id)
                cycle = visiting[start:] + [item.capability_id]
                raise CapabilityDependencyError(
                    "capability_dependency_cycle:"
                    + "->".join(cycle)
                )

            visiting.append(item.capability_id)

            dependencies = self._extract_dependencies(item)
            for dependency in dependencies:
                ref_norm = self._norm(dependency.reference)
                if ref_norm in self.primitives:
                    continue

                child = self._resolve_capability(
                    dependency.reference,
                    version=dependency.version,
                )
                visit(child)

            visiting.pop()
            visited.add(key)
            ordered.append(
                DependencyNode(
                    capability_id=item.capability_id,
                    name=item.name,
                    version=item.version,
                    rule_id=item.rule_id,
                    dependencies=dependencies,
                )
            )

        visit(root)

        return DependencyPlan(
            root_capability_id=root.capability_id,
            root_version=root.version,
            execution_order=tuple(ordered),
        )

    def _extract_dependencies(
        self,
        item: CapabilityVersion,
    ) -> tuple[CapabilityDependency, ...]:
        spec = item.executable_spec
        raw_dependencies = spec.get("dependencies")

        if raw_dependencies is not None:
            if not isinstance(raw_dependencies, list):
                raise CapabilityDependencyError(
                    f"dependencies_must_be_list:{item.capability_id}"
                )
            result: list[CapabilityDependency] = []
            for raw in raw_dependencies:
                if isinstance(raw, str):
                    result.append(
                        CapabilityDependency(reference=raw)
                    )
                    continue
                if not isinstance(raw, dict):
                    raise CapabilityDependencyError(
                        "invalid_dependency_definition"
                    )
                reference = str(
                    raw.get("reference")
                    or raw.get("capability")
                    or ""
                ).strip()
                if not reference:
                    raise CapabilityDependencyError(
                        "dependency_reference_required"
                    )
                version = raw.get("version")
                if version is not None:
                    version = int(version)
                    if version <= 0:
                        raise CapabilityDependencyError(
                            "dependency_version_must_be_positive"
                        )
                result.append(
                    CapabilityDependency(
                        reference=reference,
                        version=version,
                    )
                )
            return tuple(result)

        # Backward-compatible extraction from Point 21 executable specs.
        refs: list[str] = []
        kind = str(spec.get("kind", "")).upper()

        if kind == "SEQUENCE":
            for step in spec.get("steps", []):
                if isinstance(step, dict) and step.get("primitive"):
                    refs.append(str(step["primitive"]))

        elif kind == "LOGICAL_GROUP":
            for child in spec.get("children", []):
                if isinstance(child, dict) and child.get("primitive"):
                    refs.append(str(child["primitive"]))

        elif kind == "PRIMITIVE":
            if spec.get("primitive"):
                refs.append(str(spec["primitive"]))

        return tuple(
            CapabilityDependency(reference=x)
            for x in refs
        )

    def _resolve_capability(
        self,
        reference: str,
        *,
        version: int | None,
    ) -> CapabilityVersion:
        try:
            return self.registry.resolve(
                reference,
                version=version,
                require_enabled=True,
            )
        except CapabilityRegistryError as exc:
            raise CapabilityDependencyError(
                f"dependency_resolution_failed:{reference}:{exc}"
            ) from exc

    @staticmethod
    def _norm(value: str) -> str:
        return "_".join(
            str(value or "")
            .strip()
            .upper()
            .replace("-", " ")
            .split()
        )
