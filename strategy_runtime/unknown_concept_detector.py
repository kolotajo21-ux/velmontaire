from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import Enum
import re
from typing import Iterable


class ConceptStatus(str, Enum):
    KNOWN = "KNOWN"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    UNKNOWN_CONCEPT = "UNKNOWN_CONCEPT"


@dataclass(frozen=True, slots=True)
class ConceptDetection:
    source: str
    normalized: str
    status: ConceptStatus
    matched_concept: str | None = None
    confidence: float = 0.0
    suggestions: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "normalized": self.normalized,
            "status": self.status.value,
            "matched_concept": self.matched_concept,
            "confidence": self.confidence,
            "suggestions": list(self.suggestions),
        }


class UnknownConceptDetector:
    """
    Fail-closed detector for user-defined / unknown trading concepts.

    Exact canonical names and aliases are KNOWN.
    Close-but-not-exact terms are NEEDS_CLARIFICATION.
    Everything else is UNKNOWN_CONCEPT.

    It never silently converts an unknown phrase into a known concept.
    """

    DEFAULT_ALIASES = {
        "OB": "ORDER_BLOCK",
        "ORDERBLOCK": "ORDER_BLOCK",
        "ORDER BLOCK": "ORDER_BLOCK",
        "FVG": "FVG",
        "FAIR VALUE GAP": "FVG",
        "IFVG": "IFVG",
        "INVERSE FVG": "IFVG",
        "BOS": "BOS",
        "BREAK OF STRUCTURE": "BOS",
        "CHOCH": "CHOCH",
        "CHANGE OF CHARACTER": "CHOCH",
        "MSS": "MSS",
        "MARKET STRUCTURE SHIFT": "MSS",
        "LIQUIDITY SWEEP": "LIQUIDITY_SWEEP",
        "SWEEP": "LIQUIDITY_SWEEP",
        "LIQUIDITY GRAB": "LIQUIDITY_GRAB",
        "BSL": "BSL",
        "BUY SIDE LIQUIDITY": "BSL",
        "SSL": "SSL",
        "SELL SIDE LIQUIDITY": "SSL",
        "EQH": "EQH",
        "EQUAL HIGHS": "EQH",
        "EQL": "EQL",
        "EQUAL LOWS": "EQL",
        "BREAKER": "BREAKER_BLOCK",
        "BREAKER BLOCK": "BREAKER_BLOCK",
        "MITIGATION BLOCK": "MITIGATION_BLOCK",
        "DISPLACEMENT": "DISPLACEMENT",
        "IMBALANCE": "IMBALANCE",
        "PREMIUM": "PREMIUM",
        "DISCOUNT": "DISCOUNT",
        "EQUILIBRIUM": "EQUILIBRIUM",
        "OTE": "OTE",
        "PREVIOUS DAY HIGH": "PREVIOUS_DAY_HIGH",
        "PDH": "PREVIOUS_DAY_HIGH",
        "PREVIOUS DAY LOW": "PREVIOUS_DAY_LOW",
        "PDL": "PREVIOUS_DAY_LOW",
        "PREVIOUS WEEK HIGH": "PREVIOUS_WEEK_HIGH",
        "PWH": "PREVIOUS_WEEK_HIGH",
        "PREVIOUS WEEK LOW": "PREVIOUS_WEEK_LOW",
        "PWL": "PREVIOUS_WEEK_LOW",
    }

    def __init__(
        self,
        known_concepts: Iterable[str],
        aliases: dict[str, str] | None = None,
        clarification_threshold: float = 0.72,
    ) -> None:
        concepts = {
            self.normalize(x)
            for x in known_concepts
            if str(x).strip()
        }
        if not concepts:
            raise ValueError("known_concepts_required")

        self.known_concepts = concepts
        self.aliases = {
            self.normalize(k): self.normalize(v)
            for k, v in self.DEFAULT_ALIASES.items()
        }
        if aliases:
            self.aliases.update({
                self.normalize(k): self.normalize(v)
                for k, v in aliases.items()
            })

        self.clarification_threshold = float(clarification_threshold)
        if not 0.0 < self.clarification_threshold < 1.0:
            raise ValueError("invalid_clarification_threshold")

    @staticmethod
    def normalize(value: str) -> str:
        text = str(value or "").strip().upper()
        text = text.replace("-", " ").replace("/", " ")
        text = re.sub(r"[^A-Z0-9А-ЯЁІЇЄҐ_ ]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text.replace(" ", "_")

    def detect(self, phrase: str) -> ConceptDetection:
        source = str(phrase or "").strip()
        if not source:
            raise ValueError("concept_phrase_required")

        normalized = self.normalize(source)

        if normalized in self.known_concepts:
            return ConceptDetection(
                source=source,
                normalized=normalized,
                status=ConceptStatus.KNOWN,
                matched_concept=normalized,
                confidence=1.0,
            )

        alias_target = self.aliases.get(normalized)
        if alias_target and alias_target in self.known_concepts:
            return ConceptDetection(
                source=source,
                normalized=normalized,
                status=ConceptStatus.KNOWN,
                matched_concept=alias_target,
                confidence=1.0,
            )

        candidates = set(self.known_concepts)
        candidates.update(
            key for key, target in self.aliases.items()
            if target in self.known_concepts
        )

        scored = sorted(
            (
                (SequenceMatcher(None, normalized, candidate).ratio(), candidate)
                for candidate in candidates
            ),
            reverse=True,
        )

        best_score, best_candidate = scored[0] if scored else (0.0, "")
        suggestions = []
        for score, candidate in scored[:5]:
            if score >= self.clarification_threshold:
                canonical = self.aliases.get(candidate, candidate)
                if canonical not in suggestions:
                    suggestions.append(canonical)

        if best_score >= self.clarification_threshold:
            canonical = self.aliases.get(best_candidate, best_candidate)
            return ConceptDetection(
                source=source,
                normalized=normalized,
                status=ConceptStatus.NEEDS_CLARIFICATION,
                matched_concept=None,
                confidence=round(best_score, 4),
                suggestions=tuple(suggestions[:3] or [canonical]),
            )

        return ConceptDetection(
            source=source,
            normalized=normalized,
            status=ConceptStatus.UNKNOWN_CONCEPT,
            matched_concept=None,
            confidence=round(best_score, 4),
            suggestions=(),
        )

    def detect_many(self, phrases: Iterable[str]) -> list[ConceptDetection]:
        return [self.detect(x) for x in phrases]
