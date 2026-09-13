from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .capability_dependency_graph import (
    CapabilityDependencyError,
    CapabilityDependencyGraph,
)
from .capability_registry import (
    CapabilityRegistryError,
    CapabilityVersion,
    CustomCapabilityRegistry,
)


class CapabilityValidationError(ValueError):
    """Fail-closed validation error."""


@dataclass(frozen=True, slots=True)
class CapabilityValidationReport:
    capability_id: str
    version: int
    valid: bool
    checks: tuple[str, ...]
    execution_order: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "version": self.version,
            "valid": self.valid,
            "checks": list(self.checks),
            "execution_order": list(self.execution_order),
        }


class CapabilityValidationGate:
    """Final gate before a capability may be used for execution."""

    SUPPORTED_SPEC_KINDS = {
        "SEQUENCE",
        "LOGICAL_GROUP",
        "PRIMITIVE",
    }
    SUPPORTED_LOGICAL_OPERATORS = {"AND", "OR"}

    def __init__(
        self,
        registry: CustomCapabilityRegistry,
        primitive_names: Iterable[str],
    ) -> None:
        if not isinstance(registry, CustomCapabilityRegistry):
            raise CapabilityValidationError(
                "custom_capability_registry_required"
            )
        self.registry = registry
        self.primitives = {
            self._norm(x)
            for x in primitive_names
            if str(x).strip()
        }
        if not self.primitives:
            raise CapabilityValidationError(
                "primitive_names_required"
            )
        self.graph = CapabilityDependencyGraph(
            registry,
            self.primitives,
        )

    def validate(
        self,
        reference: str,
        *,
        version: int | None = None,
    ) -> CapabilityValidationReport:
        checks: list[str] = []

        try:
            item = self.registry.resolve(
                reference,
                version=version,
                require_enabled=True,
            )
        except CapabilityRegistryError as exc:
            raise CapabilityValidationError(
                f"registry_validation_failed:{exc}"
            ) from exc
        checks.append("REGISTRY_RESOLUTION")

        self._validate_identity(item)
        checks.append("IDENTITY")

        self._validate_executable_spec(item.executable_spec)
        checks.append("EXECUTABLE_SPEC")

        try:
            plan = self.graph.build_plan(
                item.capability_id,
                version=item.version,
            )
        except CapabilityDependencyError as exc:
            raise CapabilityValidationError(
                f"dependency_validation_failed:{exc}"
            ) from exc
        checks.append("DEPENDENCIES")

        for node in plan.execution_order:
            try:
                node_item = self.registry.resolve(
                    node.capability_id,
                    version=node.version,
                    require_enabled=True,
                )
            except CapabilityRegistryError as exc:
                raise CapabilityValidationError(
                    f"dependency_registry_validation_failed:{exc}"
                ) from exc
            self._validate_identity(node_item)
            self._validate_executable_spec(node_item.executable_spec)

        checks.append("DEPENDENCY_SPECS")
        checks.append("ENABLED_STATE")
        checks.append("VERSION_COMPATIBILITY")

        return CapabilityValidationReport(
            capability_id=item.capability_id,
            version=item.version,
            valid=True,
            checks=tuple(checks),
            execution_order=tuple(
                f"{node.capability_id}@v{node.version}"
                for node in plan.execution_order
            ),
        )

    def require_valid(
        self,
        reference: str,
        *,
        version: int | None = None,
    ) -> CapabilityValidationReport:
        report = self.validate(reference, version=version)
        if not report.valid:
            raise CapabilityValidationError(
                "capability_validation_failed"
            )
        return report

    def _validate_identity(
        self,
        item: CapabilityVersion,
    ) -> None:
        if not item.capability_id.startswith("CAP_"):
            raise CapabilityValidationError(
                "invalid_capability_id"
            )
        if not item.rule_id.startswith("CR_"):
            raise CapabilityValidationError(
                "invalid_rule_id"
            )
        if item.version <= 0:
            raise CapabilityValidationError(
                "invalid_capability_version"
            )
        if not item.name.strip():
            raise CapabilityValidationError(
                "capability_name_required"
            )

    def _validate_executable_spec(
        self,
        spec: dict[str, Any],
    ) -> None:
        if not isinstance(spec, dict) or not spec:
            raise CapabilityValidationError(
                "executable_spec_required"
            )

        kind = str(spec.get("kind") or "").strip().upper()
        if kind not in self.SUPPORTED_SPEC_KINDS:
            raise CapabilityValidationError(
                f"unsupported_executable_spec_kind:{kind}"
            )

        if kind == "SEQUENCE":
            steps = spec.get("steps")
            if not isinstance(steps, list) or not steps:
                raise CapabilityValidationError(
                    "sequence_steps_required"
                )
            for step in steps:
                self._validate_primitive_container(
                    step,
                    "sequence_step",
                )

            max_bars = spec.get("max_bars_between_steps")
            if max_bars is not None and int(max_bars) <= 0:
                raise CapabilityValidationError(
                    "invalid_max_bars_between_steps"
                )

        elif kind == "LOGICAL_GROUP":
            op = str(
                spec.get("logical_operator") or ""
            ).strip().upper()
            if op not in self.SUPPORTED_LOGICAL_OPERATORS:
                raise CapabilityValidationError(
                    f"unsupported_logical_operator:{op}"
                )
            children = spec.get("children")
            if not isinstance(children, list) or not children:
                raise CapabilityValidationError(
                    "logical_children_required"
                )
            for child in children:
                self._validate_primitive_container(
                    child,
                    "logical_child",
                )

        elif kind == "PRIMITIVE":
            primitive = self._norm(spec.get("primitive"))
            if not primitive:
                raise CapabilityValidationError(
                    "primitive_required"
                )
            self._require_known_reference(primitive)

        dependencies = spec.get("dependencies")
        if dependencies is not None:
            if not isinstance(dependencies, list):
                raise CapabilityValidationError(
                    "dependencies_must_be_list"
                )
            for dependency in dependencies:
                if isinstance(dependency, str):
                    if not dependency.strip():
                        raise CapabilityValidationError(
                            "dependency_reference_required"
                        )
                elif isinstance(dependency, dict):
                    ref = str(
                        dependency.get("reference")
                        or dependency.get("capability")
                        or ""
                    ).strip()
                    if not ref:
                        raise CapabilityValidationError(
                            "dependency_reference_required"
                        )
                    dep_version = dependency.get("version")
                    if dep_version is not None and int(dep_version) <= 0:
                        raise CapabilityValidationError(
                            "dependency_version_must_be_positive"
                        )
                else:
                    raise CapabilityValidationError(
                        "invalid_dependency_definition"
                    )

    def _validate_primitive_container(
        self,
        value: Any,
        label: str,
    ) -> None:
        if not isinstance(value, dict):
            raise CapabilityValidationError(
                f"{label}_must_be_object"
            )
        primitive = self._norm(value.get("primitive"))
        if not primitive:
            raise CapabilityValidationError(
                f"{label}_primitive_required"
            )
        self._require_known_reference(primitive)

    def _require_known_reference(self, reference: str) -> None:
        if reference in self.primitives:
            return

        try:
            self.registry.resolve(
                reference,
                require_enabled=True,
            )
        except CapabilityRegistryError as exc:
            raise CapabilityValidationError(
                f"unsupported_or_missing_reference:{reference}:{exc}"
            ) from exc

    @staticmethod
    def _norm(value: Any) -> str:
        return "_".join(
            str(value or "")
            .strip()
            .upper()
            .replace("-", " ")
            .split()
        )
