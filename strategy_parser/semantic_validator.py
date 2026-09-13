from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .dependencies import DependencyParseResult, StrategyDependency


@dataclass(slots=True)
class SemanticValidationIssue:
    code: str
    message: str
    path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "path": self.path,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class SemanticValidationResult:
    valid: bool
    issues: list[SemanticValidationIssue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "issues": [issue.to_dict() for issue in self.issues],
        }


class StrategySemanticValidator:
    """
    Day 49 semantic validator.

    Fail-closed checks:
    - unresolved dependencies;
    - cycles in BEFORE relations;
    - direct ordering contradictions;
    - R-multiple TP without SL dependency;
    - entry/cancel semantic conflicts;
    - duplicate contradictory dependency relations.
    """

    def validate(
        self,
        dependencies: DependencyParseResult | list[StrategyDependency],
    ) -> SemanticValidationResult:
        if isinstance(dependencies, DependencyParseResult):
            deps = list(dependencies.dependencies)
            unresolved = list(dependencies.unresolved)
        else:
            deps = list(dependencies)
            unresolved = []

        issues: list[SemanticValidationIssue] = []

        for item in unresolved:
            issues.append(
                SemanticValidationIssue(
                    code="UNRESOLVED_DEPENDENCY",
                    path=item,
                    message="Dependency requires clarification before strategy can run.",
                )
            )

        self._check_before_contradictions(deps, issues)
        self._check_before_cycles(deps, issues)
        self._check_r_multiple_dependencies(deps, issues)
        self._check_entry_cancel_conflicts(deps, issues)
        self._check_relation_conflicts(deps, issues)

        return SemanticValidationResult(
            valid=not issues,
            issues=issues,
        )

    @staticmethod
    def _before_edges(
        deps: list[StrategyDependency],
    ) -> list[tuple[str, str]]:
        return [
            (dep.source, dep.target)
            for dep in deps
            if dep.relation == "BEFORE"
        ]

    def _check_before_contradictions(
        self,
        deps: list[StrategyDependency],
        issues: list[SemanticValidationIssue],
    ) -> None:
        edges = set(self._before_edges(deps))

        for source, target in sorted(edges):
            if source == target:
                issues.append(
                    SemanticValidationIssue(
                        code="SELF_ORDERING",
                        message=f"{source} cannot be BEFORE itself.",
                        metadata={"source": source, "target": target},
                    )
                )
                continue

            if (target, source) in edges and source < target:
                issues.append(
                    SemanticValidationIssue(
                        code="ORDER_CONTRADICTION",
                        message=(
                            f"Contradictory ordering: {source} BEFORE {target} "
                            f"and {target} BEFORE {source}."
                        ),
                        metadata={"a": source, "b": target},
                    )
                )

    def _check_before_cycles(
        self,
        deps: list[StrategyDependency],
        issues: list[SemanticValidationIssue],
    ) -> None:
        graph: dict[str, set[str]] = {}

        for source, target in self._before_edges(deps):
            graph.setdefault(source, set()).add(target)
            graph.setdefault(target, set())

        visited: set[str] = set()
        active: set[str] = set()

        def dfs(node: str, trail: list[str]) -> bool:
            if node in active:
                cycle = trail[trail.index(node):] + [node]
                issues.append(
                    SemanticValidationIssue(
                        code="ORDER_CYCLE",
                        message="Cyclic event order is not executable.",
                        metadata={"cycle": cycle},
                    )
                )
                return True

            if node in visited:
                return False

            active.add(node)
            trail.append(node)

            for nxt in graph.get(node, set()):
                if dfs(nxt, trail):
                    return True

            trail.pop()
            active.remove(node)
            visited.add(node)
            return False

        for node in list(graph):
            if node not in visited:
                if dfs(node, []):
                    break

    @staticmethod
    def _check_r_multiple_dependencies(
        deps: list[StrategyDependency],
        issues: list[SemanticValidationIssue],
    ) -> None:
        tp_r = [
            dep
            for dep in deps
            if dep.target == "TAKE_PROFIT"
            and dep.relation == "R_MULTIPLE"
        ]

        if not tp_r:
            return

        has_sl_basis = any(
            dep.target == "STOP_LOSS"
            and dep.relation in {"PRICE_REFERENCE", "FIXED_DISTANCE", "FIXED_PRICE"}
            for dep in deps
        )

        if not has_sl_basis:
            issues.append(
                SemanticValidationIssue(
                    code="TP_R_WITHOUT_SL_BASIS",
                    message=(
                        "Take Profit uses an R multiple, but Stop Loss has no "
                        "resolved price/distance basis."
                    ),
                    path="take_profit",
                )
            )

    @staticmethod
    def _check_entry_cancel_conflicts(
        deps: list[StrategyDependency],
        issues: list[SemanticValidationIssue],
    ) -> None:
        trigger_sources = {
            dep.source
            for dep in deps
            if dep.target == "ENTRY"
            and dep.relation in {"TRIGGERS", "BEFORE"}
        }
        cancel_sources = {
            dep.source
            for dep in deps
            if dep.target == "SETUP"
            and dep.relation == "CANCELS"
        }

        conflict = sorted(trigger_sources & cancel_sources)

        for source in conflict:
            issues.append(
                SemanticValidationIssue(
                    code="ENTRY_CANCEL_CONFLICT",
                    message=(
                        f"{source} is defined both as an entry dependency "
                        "and as a setup cancellation condition."
                    ),
                    metadata={"source": source},
                )
            )

    @staticmethod
    def _check_relation_conflicts(
        deps: list[StrategyDependency],
        issues: list[SemanticValidationIssue],
    ) -> None:
        by_pair: dict[tuple[str, str], set[str]] = {}

        for dep in deps:
            by_pair.setdefault(
                (dep.source, dep.target),
                set(),
            ).add(dep.relation)

        incompatible = {
            frozenset({"BEFORE", "CANCELS"}),
            frozenset({"TRIGGERS", "CANCELS"}),
        }

        for (source, target), relations in by_pair.items():
            for pair in incompatible:
                if pair.issubset(relations):
                    issues.append(
                        SemanticValidationIssue(
                            code="RELATION_CONFLICT",
                            message=(
                                f"{source} -> {target} has incompatible relations: "
                                + ", ".join(sorted(relations))
                            ),
                            metadata={
                                "source": source,
                                "target": target,
                                "relations": sorted(relations),
                            },
                        )
                    )
                    break