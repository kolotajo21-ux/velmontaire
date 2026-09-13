from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
from typing import Any, Iterable


class CustomRuleBuilderError(ValueError):
    """Fail-closed custom-rule build error."""


class CustomRuleKind(str, Enum):
    SEQUENCE = "SEQUENCE"
    ALL_OF = "ALL_OF"
    ANY_OF = "ANY_OF"
    SINGLE = "SINGLE"


@dataclass(frozen=True, slots=True)
class CustomRuleDefinition:
    name: str
    kind: CustomRuleKind | str
    requires: tuple[str, ...]
    description: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        name = str(self.name or "").strip()
        if not name:
            raise CustomRuleBuilderError("custom_rule_name_required")
        object.__setattr__(self, "name", name)

        req = tuple(
            str(x or "").strip().upper()
            for x in self.requires
            if str(x or "").strip()
        )
        if not req:
            raise CustomRuleBuilderError("custom_rule_requires_required")
        object.__setattr__(self, "requires", req)


@dataclass(frozen=True, slots=True)
class CompiledCustomRule:
    rule_id: str
    name: str
    kind: CustomRuleKind
    requires: tuple[str, ...]
    description: str
    parameters: dict[str, Any]
    executable_spec: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "kind": self.kind.value,
            "requires": list(self.requires),
            "description": self.description,
            "parameters": dict(self.parameters),
            "executable_spec": dict(self.executable_spec),
        }


class CustomRuleBuilder:
    """
    Compiles clarified user concepts into reusable rules composed only from
    already-supported primitives.

    No Python source code is generated.
    Unknown primitives block compilation instead of being guessed.
    """

    def __init__(self, supported_primitives: Iterable[str]) -> None:
        self.supported = {
            self._norm(x)
            for x in supported_primitives
            if str(x).strip()
        }
        if not self.supported:
            raise CustomRuleBuilderError("supported_primitives_required")

    def from_structured_definition(
        self,
        *,
        name: str,
        structured_definition: dict[str, Any],
        default_kind: CustomRuleKind | str = CustomRuleKind.SEQUENCE,
    ) -> CompiledCustomRule:
        if not isinstance(structured_definition, dict):
            raise CustomRuleBuilderError("structured_definition_required")

        base_concept = structured_definition.get("base_concept")
        requires = list(structured_definition.get("requires") or [])

        if base_concept:
            normalized_existing = {self._norm(x) for x in requires}
            if self._norm(base_concept) not in normalized_existing:
                requires.append(base_concept)

        if not requires:
            raise CustomRuleBuilderError("structured_definition_requires_missing")

        definition = CustomRuleDefinition(
            name=name,
            kind=structured_definition.get("kind", default_kind),
            requires=tuple(requires),
            description=str(
                structured_definition.get("description", "")
            ).strip(),
            parameters={
                k: v
                for k, v in structured_definition.items()
                if k
                not in {
                    "base_concept",
                    "requires",
                    "description",
                    "kind",
                }
            },
        )
        return self.compile(definition)

    def compile(
        self,
        definition: CustomRuleDefinition,
    ) -> CompiledCustomRule:
        if not isinstance(definition, CustomRuleDefinition):
            raise CustomRuleBuilderError("invalid_custom_rule_definition")

        kind = self._kind(definition.kind)
        requires = tuple(self._norm(x) for x in definition.requires)

        unknown = sorted({
            x for x in requires if x not in self.supported
        })
        if unknown:
            raise CustomRuleBuilderError(
                "unsupported_custom_rule_primitives:"
                + ",".join(unknown)
            )

        if kind == CustomRuleKind.SINGLE and len(requires) != 1:
            raise CustomRuleBuilderError(
                "single_rule_requires_exactly_one_primitive"
            )

        executable = self._build_spec(
            kind,
            requires,
            definition.parameters,
        )
        rid = self._rule_id(
            definition.name,
            kind,
            requires,
            definition.parameters,
        )

        return CompiledCustomRule(
            rule_id=rid,
            name=definition.name,
            kind=kind,
            requires=requires,
            description=definition.description,
            parameters=dict(definition.parameters),
            executable_spec=executable,
        )

    def _build_spec(
        self,
        kind: CustomRuleKind,
        requires: tuple[str, ...],
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        if kind == CustomRuleKind.SEQUENCE:
            spec: dict[str, Any] = {
                "kind": "SEQUENCE",
                "steps": [
                    {"primitive": x}
                    for x in requires
                ],
            }
            if "max_bars_between_steps" in parameters:
                value = int(parameters["max_bars_between_steps"])
                if value <= 0:
                    raise CustomRuleBuilderError(
                        "invalid_max_bars_between_steps"
                    )
                spec["max_bars_between_steps"] = value
            return spec

        if kind == CustomRuleKind.ALL_OF:
            return {
                "kind": "LOGICAL_GROUP",
                "logical_operator": "AND",
                "children": [
                    {"primitive": x}
                    for x in requires
                ],
            }

        if kind == CustomRuleKind.ANY_OF:
            return {
                "kind": "LOGICAL_GROUP",
                "logical_operator": "OR",
                "children": [
                    {"primitive": x}
                    for x in requires
                ],
            }

        if kind == CustomRuleKind.SINGLE:
            return {
                "kind": "PRIMITIVE",
                "primitive": requires[0],
            }

        raise CustomRuleBuilderError(
            f"unsupported_custom_rule_kind:{kind}"
        )

    @staticmethod
    def _norm(value: str) -> str:
        return "_".join(
            str(value or "")
            .strip()
            .upper()
            .replace("-", " ")
            .split()
        )

    @staticmethod
    def _kind(
        value: CustomRuleKind | str,
    ) -> CustomRuleKind:
        if isinstance(value, CustomRuleKind):
            return value

        raw = (
            str(value or "")
            .strip()
            .upper()
            .replace("-", "_")
            .replace(" ", "_")
        )
        aliases = {
            "AND": CustomRuleKind.ALL_OF,
            "OR": CustomRuleKind.ANY_OF,
            "SEQ": CustomRuleKind.SEQUENCE,
        }
        if raw in aliases:
            return aliases[raw]

        try:
            return CustomRuleKind(raw)
        except ValueError as exc:
            raise CustomRuleBuilderError(
                f"unsupported_custom_rule_kind:{value}"
            ) from exc

    @staticmethod
    def _rule_id(
        name: str,
        kind: CustomRuleKind,
        requires: tuple[str, ...],
        parameters: dict[str, Any],
    ) -> str:
        payload = repr((
            str(name).strip().upper(),
            kind.value,
            requires,
            sorted(
                parameters.items(),
                key=lambda x: str(x[0]),
            ),
        )).encode("utf-8")

        return (
            "CR_"
            + sha256(payload).hexdigest()[:16].upper()
        )
