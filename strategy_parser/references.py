from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .trading_ontology import ConceptCategory, DEFAULT_TRADING_ONTOLOGY


@dataclass(slots=True)
class StrategyReference:
    reference_id: str
    target_type: str
    target_name: str
    source_text: str
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference_id": self.reference_id,
            "target_type": self.target_type,
            "target_name": self.target_name,
            "source_text": self.source_text,
            "attributes": dict(self.attributes),
        }


@dataclass(slots=True)
class ReferenceParseResult:
    references: list[StrategyReference] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.unresolved


class StrategyReferenceParser:
    """Conservative Day 47 parser for cross-rule references."""

    _PRONOUNS = re.compile(
        r"\b(?:этого|этот|этой|тот\s+же|того\s+же|цього|цей|ця|те\s+саме|same|this|that)\b",
        re.I,
    )

    def parse(self, text: str) -> ReferenceParseResult:
        source = re.sub(r"\s+", " ", str(text or "")).strip()
        result = ReferenceParseResult()
        upper = source.upper()

        seen: set[tuple[str, str]] = set()

        type_by_category = {
            ConceptCategory.EVENT: "EVENT",
            ConceptCategory.STRUCTURE: "EVENT",
            ConceptCategory.LIQUIDITY: "EVENT",
            ConceptCategory.ZONE: "ZONE",
            ConceptCategory.PRICE_REFERENCE: "PRICE_REFERENCE",
            ConceptCategory.RANGE_LOCATION: "RANGE_LOCATION",
            ConceptCategory.MANAGEMENT: "MANAGEMENT",
        }

        for match in DEFAULT_TRADING_ONTOLOGY.find_matches(source):
            target_type = type_by_category.get(match.concept.category)
            if target_type is None:
                continue

            key = (target_type, match.concept.canonical)
            if key in seen:
                continue

            seen.add(key)
            result.references.append(
                StrategyReference(
                    reference_id=f"ref_{len(result.references) + 1}",
                    target_type=target_type,
                    target_name=match.concept.canonical,
                    source_text=match.alias,
                    attributes={
                        "ontology_category": match.concept.category.value,
                        **dict(match.concept.metadata),
                    },
                )
            )

        if self._PRONOUNS.search(source):
            if not result.references:
                result.unresolved.append("reference.target")
            elif len(result.references) > 1:
                result.unresolved.append("reference.ambiguous_target")

        # Relative SL/TP references are preserved, never converted to a price here.
        if re.search(r"\b(?:SL|STOP\s*LOSS)\b.*\b(?:LOW|HIGH)\b", upper):
            result.references.append(
                StrategyReference(
                    reference_id=f"ref_{len(result.references) + 1}",
                    target_type="PRICE_REFERENCE",
                    target_name="STOP_LOSS_STRUCTURE_REFERENCE",
                    source_text=source,
                )
            )

        if re.search(r"\b(?:TP|TAKE\s*PROFIT)\b\s*(?:=|:)?\s*\d+(?:[.,]\d+)?\s*R\b", upper):
            result.references.append(
                StrategyReference(
                    reference_id=f"ref_{len(result.references) + 1}",
                    target_type="RISK_REFERENCE",
                    target_name="R_MULTIPLE",
                    source_text=source,
                )
            )

        return result