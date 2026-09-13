from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Iterable


class LogicalEvaluationError(ValueError):
    """Fail-closed logical evaluation error."""


class LogicalMode(str, Enum):
    AND = "AND"
    OR = "OR"
    NOT = "NOT"
    ALL_OF = "ALL_OF"
    ANY_OF = "ANY_OF"


@dataclass(frozen=True, slots=True)
class LogicalEvaluation:
    mode: LogicalMode
    passed: bool
    results: tuple[bool, ...]
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "passed": bool(self.passed),
            "results": list(self.results),
            "diagnostics": dict(self.diagnostics),
        }


class UniversalLogicalEngine:
    """
    Deterministic logical composition gateway.

    Supports booleans, zero-argument callables and nested condition trees.
    It never invents missing child results and fails closed on malformed input.
    """

    _ALIASES = {
        "AND": LogicalMode.AND,
        "&&": LogicalMode.AND,
        "ALL": LogicalMode.ALL_OF,
        "ALL_OF": LogicalMode.ALL_OF,
        "OR": LogicalMode.OR,
        "||": LogicalMode.OR,
        "ANY": LogicalMode.ANY_OF,
        "ANY_OF": LogicalMode.ANY_OF,
        "NOT": LogicalMode.NOT,
        "!": LogicalMode.NOT,
    }

    def normalize(self, mode: LogicalMode | str) -> LogicalMode:
        if isinstance(mode, LogicalMode):
            return mode
        raw = str(mode or "").strip().upper().replace("-", "_").replace(" ", "_")
        result = self._ALIASES.get(raw)
        if result is None:
            raise LogicalEvaluationError(f"unsupported_logical_operator:{mode}")
        return result

    def evaluate(
        self,
        mode: LogicalMode | str,
        children: Iterable[Any],
    ) -> LogicalEvaluation:
        op = self.normalize(mode)
        items = list(children)

        if op == LogicalMode.NOT:
            if len(items) != 1:
                raise LogicalEvaluationError("NOT_requires_exactly_one_child")
        elif not items:
            raise LogicalEvaluationError(f"{op.value}_requires_children")

        results = tuple(self._resolve_child(child) for child in items)

        if op in (LogicalMode.AND, LogicalMode.ALL_OF):
            passed = all(results)
        elif op in (LogicalMode.OR, LogicalMode.ANY_OF):
            passed = any(results)
        elif op == LogicalMode.NOT:
            passed = not results[0]
        else:
            raise LogicalEvaluationError(f"unsupported_logical_operator:{op.value}")

        return LogicalEvaluation(
            mode=op,
            passed=passed,
            results=results,
            diagnostics={"child_count": len(results)},
        )

    def evaluate_tree(
        self,
        node: Any,
        *,
        leaf_resolver: Callable[[Any], bool] | None = None,
    ) -> bool:
        """
        Tree form:
          {"operator": "AND", "children": [True, {...}]}
          {"operator": "NOT", "children": [False]}

        Non-group leaves are delegated to leaf_resolver when supplied.
        """
        if isinstance(node, bool):
            return node

        if callable(node):
            return self._strict_bool(node())

        if isinstance(node, dict) and ("operator" in node or "logical_operator" in node):
            mode = node.get("operator", node.get("logical_operator"))
            children = node.get("children")
            if not isinstance(children, (list, tuple)):
                raise LogicalEvaluationError("logical_children_required")
            resolved = [
                self.evaluate_tree(child, leaf_resolver=leaf_resolver)
                for child in children
            ]
            return self.evaluate(mode, resolved).passed

        if leaf_resolver is not None:
            return self._strict_bool(leaf_resolver(node))

        raise LogicalEvaluationError(
            f"unresolved_logical_leaf:{type(node).__name__}"
        )

    @staticmethod
    def _strict_bool(value: Any) -> bool:
        if type(value) is not bool:
            raise LogicalEvaluationError(
                f"logical_child_must_be_bool:{type(value).__name__}"
            )
        return value

    def _resolve_child(self, child: Any) -> bool:
        if callable(child):
            child = child()
        return self._strict_bool(child)
