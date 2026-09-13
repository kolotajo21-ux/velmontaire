from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from strategy_schema import (
    ConditionKind,
    LogicalOperator,
    StrategyCondition,
)


@dataclass(slots=True)
class ComplexConditionParseResult:
    condition: StrategyCondition | None
    ambiguous: bool
    reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "condition": (
                self.condition.to_dict()
                if self.condition is not None
                else None
            ),
            "ambiguous": self.ambiguous,
            "reason": self.reason,
        }


class ComplexConditionParser:
    """
    Conservative parser for compound entry conditions.

    Supported:
    - A AND B
    - A OR B
    - NOT A
    - A -> B -> C
    - then / затем / потом / после этого
    - nested precedence: NOT > AND > OR

    It does not invent missing events or ordering.
    """

    _OR = re.compile(r"\s+(?:OR|ИЛИ|АБО)\s+", re.I)
    _AND = re.compile(r"\s+(?:AND|И|І|ТА)\s+", re.I)
    _NOT = re.compile(r"^\s*(?:NOT|НЕ)\s+", re.I)
    _SEQ = re.compile(
        r"\s*(?:->|→|\bTHEN\b|\bЗАТЕМ\b|\bПОТОМ\b|"
        r"\bПОСЛЕ\s+ЭТОГО\b|\bПОТІМ\b|\bДАЛІ\b|\bПІСЛЯ\s+ЦЬОГО\b)\s*",
        re.I,
    )

    def parse(
        self,
        expression: str,
        *,
        condition_id: str = "entry_condition_1",
    ) -> ComplexConditionParseResult:
        text = self._clean(expression)
        if not text:
            return ComplexConditionParseResult(
                condition=None,
                ambiguous=True,
                reason="empty_condition_expression",
            )

        # Sequence has the widest scope because order is semantically
        # different from boolean grouping.
        seq = self._split(self._SEQ, text)
        if len(seq) > 1:
            steps = []
            for i, part in enumerate(seq, start=1):
                parsed = self.parse(
                    part,
                    condition_id=f"{condition_id}_step_{i}",
                )
                if parsed.ambiguous or parsed.condition is None:
                    return parsed
                steps.append(parsed.condition)

            return ComplexConditionParseResult(
                condition=StrategyCondition(
                    condition_id=condition_id,
                    kind=ConditionKind.SEQUENCE,
                    sequence=steps,
                    description=text,
                    metadata={"parser": "ComplexConditionParser"},
                ),
                ambiguous=False,
            )

        or_parts = self._split(self._OR, text)
        if len(or_parts) > 1:
            return self._logical(
                LogicalOperator.OR,
                or_parts,
                condition_id,
                text,
            )

        and_parts = self._split(self._AND, text)
        if len(and_parts) > 1:
            return self._logical(
                LogicalOperator.AND,
                and_parts,
                condition_id,
                text,
            )

        not_match = self._NOT.match(text)
        if not_match:
            remainder = text[not_match.end():].strip()
            child = self.parse(
                remainder,
                condition_id=f"{condition_id}_not_1",
            )
            if child.ambiguous or child.condition is None:
                return child
            return ComplexConditionParseResult(
                condition=StrategyCondition(
                    condition_id=condition_id,
                    kind=ConditionKind.LOGICAL_GROUP,
                    logical_operator=LogicalOperator.NOT,
                    children=[child.condition],
                    description=text,
                    metadata={"parser": "ComplexConditionParser"},
                ),
                ambiguous=False,
            )

        # Reject dangling operators instead of silently turning them into events.
        if re.search(
            r"(?:->|→|\bAND\b|\bOR\b|\bNOT\b|\bИ\b|\bІ\b|\bТА\b|\bИЛИ\b|\bАБО\b|\bНЕ\b)\s*$",
            text,
            re.I,
        ):
            return ComplexConditionParseResult(
                condition=None,
                ambiguous=True,
                reason="dangling_logical_operator",
            )

        return ComplexConditionParseResult(
            condition=StrategyCondition(
                condition_id=condition_id,
                kind=ConditionKind.EVENT,
                event_name=text,
                description=text,
                metadata={"parser": "ComplexConditionParser"},
            ),
            ambiguous=False,
        )

    def _logical(
        self,
        operator: LogicalOperator,
        parts: Iterable[str],
        condition_id: str,
        source: str,
    ) -> ComplexConditionParseResult:
        children = []
        for i, part in enumerate(parts, start=1):
            parsed = self.parse(
                part,
                condition_id=f"{condition_id}_{operator.value.lower()}_{i}",
            )
            if parsed.ambiguous or parsed.condition is None:
                return parsed
            children.append(parsed.condition)

        if len(children) < 2:
            return ComplexConditionParseResult(
                condition=None,
                ambiguous=True,
                reason="logical_group_requires_multiple_children",
            )

        return ComplexConditionParseResult(
            condition=StrategyCondition(
                condition_id=condition_id,
                kind=ConditionKind.LOGICAL_GROUP,
                logical_operator=operator,
                children=children,
                description=source,
                metadata={"parser": "ComplexConditionParser"},
            ),
            ambiguous=False,
        )

    @staticmethod
    def _split(pattern: re.Pattern, text: str) -> list[str]:
        parts = [p.strip(" ,") for p in pattern.split(text)]
        if len(parts) <= 1:
            return [text]
        if any(not p for p in parts):
            return [text]
        return parts

    @staticmethod
    def _clean(text: str) -> str:
        return re.sub(r"\s+", " ", str(text or "")).strip(" .;,")