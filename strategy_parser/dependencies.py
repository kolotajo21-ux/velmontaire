from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .trading_ontology import DEFAULT_TRADING_ONTOLOGY


@dataclass(slots=True)
class StrategyDependency:
    dependency_id: str
    source: str
    target: str
    relation: str
    source_text: str
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dependency_id": self.dependency_id,
            "source": self.source,
            "target": self.target,
            "relation": self.relation,
            "source_text": self.source_text,
            "attributes": dict(self.attributes),
        }


@dataclass(slots=True)
class DependencyParseResult:
    dependencies: list[StrategyDependency] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.unresolved


class StrategyDependencyResolver:
    """
    Day 48 conservative dependency resolver.

    It preserves explicit ordering/dependencies only.
    It never invents an omitted predecessor or reference target.
    """

    @property
    def _concept_pattern(self) -> str:
        return DEFAULT_TRADING_ONTOLOGY.dependency_pattern()

    def resolve(self, text: str) -> DependencyParseResult:
        source = re.sub(r"\s+", " ", str(text or "")).strip()
        upper = source.upper()
        result = DependencyParseResult()

        # Explicit arrow chain: A -> B -> C.
        arrow_parts = [
            self._canonical(x)
            for x in re.split(r"\s*(?:->|→)\s*", upper)
            if self._is_concept(x.strip())
        ]
        if len(arrow_parts) >= 2:
            for left, right in zip(arrow_parts, arrow_parts[1:]):
                self._add(result, left, right, "BEFORE", source)
            return result

        # Explicit "after X ... Y" relation.
        for match in re.finditer(
            rf"\bAFTER\s+{self._concept_pattern}\b.*?\b{self._concept_pattern}\b",
            upper,
            re.I,
        ):
            first = self._canonical(match.group(1))
            second = self._canonical(match.group(2))
            if first != second:
                self._add(result, first, second, "BEFORE", source)

        # Russian equivalent: "после X ... Y".
        for match in re.finditer(
            rf"\bПОСЛЕ\s+{self._concept_pattern}\b.*?\b{self._concept_pattern}\b",
            upper,
            re.I,
        ):
            first = self._canonical(match.group(1))
            second = self._canonical(match.group(2))
            if first != second:
                self._add(result, first, second, "BEFORE", source)

        # Ukrainian equivalent: "після X ... Y".
        for match in re.finditer(
            rf"\bПІСЛЯ\s+{self._concept_pattern}\b.*?\b{self._concept_pattern}\b",
            upper,
            re.I,
        ):
            first = self._canonical(match.group(1))
            second = self._canonical(match.group(2))
            if first != second:
                self._add(result, first, second, "BEFORE", source)

        # Entry on return to a named zone.
        match = re.search(
            rf"\b(?:ENTRY|ВХОД)\b.*?\b(?:RETURN|ВОЗВРАТ\w*)\b.*?\b{self._concept_pattern}\b",
            upper,
            re.I,
        )
        if match:
            zone = self._canonical(match.group(1))
            self._add(result, zone, "ENTRY", "TRIGGERS", source)

        # SL structural dependency.
        sl = re.search(
            rf"\b(?:SL|STOP\s*LOSS)\b.*?\b(?:LOW|HIGH|ЛОУ|ХАЙ)\b.*?\b{self._concept_pattern}\b",
            upper,
            re.I,
        )
        if sl:
            target = self._canonical(sl.group(1))
            self._add(result, target, "STOP_LOSS", "PRICE_REFERENCE", source)

        # TP depends on R / SL.
        rr = re.search(
            r"\b(?:TP|TAKE\s*PROFIT)\b\s*(?:=|:)?\s*(\d+(?:[.,]\d+)?)\s*R\b",
            upper,
            re.I,
        )
        if rr:
            self._add(
                result,
                "STOP_LOSS",
                "TAKE_PROFIT",
                "R_MULTIPLE",
                source,
                {"multiple": float(rr.group(1).replace(",", "."))},
            )

        # Explicit cancellation/invalidation.
        cancel = re.search(
            rf"\b(?:IF|ЕСЛИ)\b.*?\b{self._concept_pattern}\b.*?\b(?:CANCEL|CANCELLED|ОТМЕН\w*)\b",
            upper,
            re.I,
        )
        if cancel:
            event = self._canonical(cancel.group(1))
            self._add(result, event, "SETUP", "CANCELS", source)

        # Fail closed for dependency words with no explicit resolvable target.
        if re.search(r"\b(?:AFTER|BEFORE|ПОСЛЕ|ПІСЛЯ|ДО|ПЕРЕД)\b", upper) and not result.dependencies:
            result.unresolved.append("dependency.explicit_relation")

        return result

    def resolve_lines(self, lines: list[str]) -> DependencyParseResult:
        merged = DependencyParseResult()
        for line in lines:
            parsed = self.resolve(line)
            for dep in parsed.dependencies:
                if not any(
                    x.source == dep.source
                    and x.target == dep.target
                    and x.relation == dep.relation
                    for x in merged.dependencies
                ):
                    dep.dependency_id = f"dep_{len(merged.dependencies) + 1}"
                    merged.dependencies.append(dep)
            for item in parsed.unresolved:
                if item not in merged.unresolved:
                    merged.unresolved.append(item)
        return merged

    def _add(
        self,
        result: DependencyParseResult,
        source: str,
        target: str,
        relation: str,
        source_text: str,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        if any(
            x.source == source and x.target == target and x.relation == relation
            for x in result.dependencies
        ):
            return
        result.dependencies.append(
            StrategyDependency(
                dependency_id=f"dep_{len(result.dependencies) + 1}",
                source=source,
                target=target,
                relation=relation,
                source_text=source_text,
                attributes=dict(attributes or {}),
            )
        )

    @staticmethod
    def _canonical(value: str) -> str:
        canonical = DEFAULT_TRADING_ONTOLOGY.canonicalize(value)
        if canonical is not None:
            return canonical
        return re.sub(r"\s+", " ", str(value or "").strip().upper())

    @staticmethod
    def _is_concept(value: str) -> bool:
        return DEFAULT_TRADING_ONTOLOGY.canonicalize(value) is not None
