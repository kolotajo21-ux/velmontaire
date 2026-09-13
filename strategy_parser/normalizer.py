from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .language_semantics import GENERAL_ALIASES, detect_languages
from .trading_ontology import DEFAULT_TRADING_ONTOLOGY


@dataclass(slots=True)
class NormalizedToken:
    category: str
    canonical: str
    original: str
    start: int
    end: int
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "canonical": self.canonical,
            "original": self.original,
            "start": int(self.start),
            "end": int(self.end),
            "confidence": float(self.confidence),
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class NormalizationResult:
    source_text: str
    normalized_text: str
    tokens: list[NormalizedToken] = field(default_factory=list)
    unknown_terms: list[str] = field(default_factory=list)
    language: dict[str, Any] = field(default_factory=dict)

    def values(self, category: str) -> list[str]:
        return [x.canonical for x in self.tokens if x.category == category]

    def first(self, category: str, default: Any = None) -> Any:
        values = self.values(category)
        return values[0] if values else default

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_text": self.source_text,
            "normalized_text": self.normalized_text,
            "tokens": [x.to_dict() for x in self.tokens],
            "unknown_terms": list(self.unknown_terms),
            "language": dict(self.language),
        }


class StrategyTextNormalizer:
    """
    Multilingual conservative semantic normalizer.

    Supported input:
    - English
    - Russian
    - Ukrainian
    - mixed RU/UA/EN trading text

    It canonicalizes vocabulary only. It never invents missing strategy logic.
    """

    SYMBOL_ALIASES: dict[str, tuple[str, ...]] = {
        "XAUUSD": ("xauusd", "xau/usd", "gold", "золото", "золоте", "золота", "золотом"),
        "XAGUSD": ("xagusd", "xag/usd", "silver", "серебро", "срібло"),
        "EURUSD": ("eurusd", "eur/usd", "евродоллар", "евро доллар", "євродолар", "євро долар"),
        "GBPUSD": ("gbpusd", "gbp/usd", "фунт доллар", "фунт долар"),
        "USDJPY": ("usdjpy", "usd/jpy", "доллар иена", "долар єна"),
        "USDCHF": ("usdchf", "usd/chf"),
        "USDCAD": ("usdcad", "usd/cad"),
        "AUDUSD": ("audusd", "aud/usd"),
        "NZDUSD": ("nzdusd", "nzd/usd"),
        "NAS100": ("nas100", "nasdaq", "nasdaq100", "насдак"),
        "US30": ("us30", "dow", "dow jones", "доу"),
        "SPX500": ("spx500", "sp500", "s&p500", "s&p 500"),
    }

    TIMEFRAME_ALIASES: dict[str, tuple[str, ...]] = {
        "M1": ("m1", "1m", "1 min", "1 minute", "1 минута", "1 хвилина"),
        "M5": ("m5", "5m", "5 min", "5 minutes", "5 минут", "5 хвилин"),
        "M15": ("m15", "15m", "15 min", "15 minutes", "15 минут", "15 хвилин"),
        "M30": ("m30", "30m", "30 min", "30 minutes", "30 минут", "30 хвилин"),
        "H1": ("h1", "1h", "1 hour", "часовик", "1 час", "1 година"),
        "H4": ("h4", "4h", "4 hour", "4 hours", "4 часа", "4 часов", "4 години"),
        "D1": ("d1", "1d", "daily", "дневка", "дневной", "денний", "дневний"),
        "W1": ("w1", "1w", "weekly", "недельный", "тижневий"),
    }

    SIDE_ALIASES: dict[str, tuple[str, ...]] = {
        "LONG": (
            "long", "buy", "покупка", "покупать", "покупай", "купить", "лонг",
            "купівля", "купувати", "купуй", "купити",
        ),
        "SHORT": (
            "short", "sell", "продажа", "продавать", "продавай", "продать", "шорт",
            "продаж", "продавати", "продавай", "продати",
        ),
    }

    ORDER_TYPE_ALIASES: dict[str, tuple[str, ...]] = {
        "MARKET": (
            "market order", "market", "по рынку", "рыночный ордер", "рыночный вход",
            "по ринку", "ринковий ордер", "ринковий вхід",
        ),
        "LIMIT": (
            "limit order", "limit", "лимитка", "лимитный ордер", "лимитный вход",
            "лімітка", "лімітний ордер", "лімітний вхід",
        ),
        "STOP": (
            "stop order", "buy stop", "sell stop", "стоп ордер", "стоповый ордер",
            "стоповий ордер",
        ),
    }

    _PERCENT_RE = re.compile(r"(?<![\w.])(\d+(?:[.,]\d+)?)\s*%")
    _HALF_PERCENT_RE = re.compile(
        r"\b(?:half\s+(?:a\s+)?percent|пол\s*процента|полпроцента|"
        r"пів\s*відсотка|піввідсотка)\b",
        re.I,
    )

    def normalize(self, text: str) -> NormalizationResult:
        source = str(text or "").strip()
        if not source:
            raise ValueError("strategy text is required")

        tokens: list[NormalizedToken] = []
        self._collect_aliases(source, "symbol", self.SYMBOL_ALIASES, tokens)
        self._collect_aliases(source, "timeframe", self.TIMEFRAME_ALIASES, tokens)
        self._collect_aliases(source, "side", self.SIDE_ALIASES, tokens)
        self._collect_aliases(source, "order_type", self.ORDER_TYPE_ALIASES, tokens)
        self._collect_ontology_concepts(source, tokens)
        self._collect_aliases(source, "language_keyword", GENERAL_ALIASES, tokens)

        for match in self._PERCENT_RE.finditer(source):
            tokens.append(
                NormalizedToken(
                    category="percent",
                    canonical=str(float(match.group(1).replace(",", "."))),
                    original=match.group(0),
                    start=match.start(),
                    end=match.end(),
                    metadata={"numeric_value": float(match.group(1).replace(",", "."))},
                )
            )

        for match in self._HALF_PERCENT_RE.finditer(source):
            if not self._overlaps(match.start(), match.end(), tokens, category="percent"):
                tokens.append(
                    NormalizedToken(
                        category="percent",
                        canonical="0.5",
                        original=match.group(0),
                        start=match.start(),
                        end=match.end(),
                        metadata={"numeric_value": 0.5},
                    )
                )

        tokens = self._deduplicate(tokens)
        profile = detect_languages(source)

        return NormalizationResult(
            source_text=source,
            normalized_text=self._render_normalized(source, tokens),
            tokens=tokens,
            unknown_terms=[],
            language=profile.to_dict(),
        )

    def detect_unknown_terms(
        self,
        result: NormalizationResult,
        terms: list[str],
    ) -> NormalizationResult:
        known_originals = {x.original.lower().strip() for x in result.tokens}
        unknown: list[str] = []
        for term in terms:
            value = str(term).strip()
            if value and value.lower() not in known_originals and value not in unknown:
                unknown.append(value)
        result.unknown_terms = unknown
        return result

    def canonical_values(self, text: str) -> dict[str, list[str]]:
        result = self.normalize(text)
        categories = {x.category for x in result.tokens}
        return {c: result.values(c) for c in sorted(categories)}

    def _collect_ontology_concepts(
        self,
        source: str,
        tokens: list[NormalizedToken],
    ) -> None:
        for match in DEFAULT_TRADING_ONTOLOGY.find_matches(source):
            if any(
                match.start < token.end and match.end > token.start
                for token in tokens
            ):
                continue

            tokens.append(
                NormalizedToken(
                    category="concept",
                    canonical=match.concept.canonical,
                    original=match.alias,
                    start=match.start,
                    end=match.end,
                    metadata={
                        "ontology_category": match.concept.category.value,
                        **dict(match.concept.metadata),
                    },
                )
            )

    def _collect_aliases(
        self,
        source: str,
        category: str,
        aliases: dict[str, tuple[str, ...]],
        tokens: list[NormalizedToken],
    ) -> None:
        for canonical, variants in aliases.items():
            for alias in sorted(variants, key=len, reverse=True):
                pattern = re.compile(rf"(?<!\w){re.escape(alias)}(?!\w)", re.I)
                for match in pattern.finditer(source):
                    # Do not create overlapping replacements, even across categories.
                    if any(match.start() < x.end and match.end() > x.start for x in tokens):
                        continue
                    tokens.append(
                        NormalizedToken(
                            category=category,
                            canonical=canonical,
                            original=match.group(0),
                            start=match.start(),
                            end=match.end(),
                        )
                    )

    @staticmethod
    def _overlaps(
        start: int,
        end: int,
        tokens: list[NormalizedToken],
        *,
        category: str,
    ) -> bool:
        return any(
            x.category == category and start < x.end and end > x.start
            for x in tokens
        )

    @staticmethod
    def _deduplicate(tokens: list[NormalizedToken]) -> list[NormalizedToken]:
        ordered = sorted(tokens, key=lambda x: (x.start, -(x.end - x.start), x.category))
        result: list[NormalizedToken] = []
        occupied: list[tuple[int, int]] = []
        seen: set[tuple[str, str, int, int]] = set()

        for token in ordered:
            key = (token.category, token.canonical, token.start, token.end)
            if key in seen:
                continue
            if any(token.start < end and token.end > start for start, end in occupied):
                continue
            seen.add(key)
            occupied.append((token.start, token.end))
            result.append(token)
        return result

    @staticmethod
    def _render_normalized(source: str, tokens: list[NormalizedToken]) -> str:
        text = source
        for token in sorted(tokens, key=lambda x: x.start, reverse=True):
            replacement = f"{token.canonical}%" if token.category == "percent" else token.canonical
            text = text[:token.start] + replacement + text[token.end:]
        return text