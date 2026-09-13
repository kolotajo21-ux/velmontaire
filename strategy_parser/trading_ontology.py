from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable


class ConceptCategory(str, Enum):
    EVENT = "EVENT"
    ZONE = "ZONE"
    STRUCTURE = "STRUCTURE"
    LIQUIDITY = "LIQUIDITY"
    PRICE_REFERENCE = "PRICE_REFERENCE"
    RANGE_LOCATION = "RANGE_LOCATION"
    EXECUTION = "EXECUTION"
    MANAGEMENT = "MANAGEMENT"


@dataclass(frozen=True, slots=True)
class TradingConcept:
    canonical: str
    category: ConceptCategory
    aliases: dict[str, tuple[str, ...]]
    abbreviations: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def all_aliases(self) -> tuple[str, ...]:
        values: list[str] = [self.canonical, self.canonical.replace("_", " ")]
        values.extend(self.abbreviations)
        for items in self.aliases.values():
            values.extend(items)

        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            clean = re.sub(r"\s+", " ", str(value or "").strip())
            key = clean.casefold()
            if clean and key not in seen:
                seen.add(key)
                result.append(clean)
        return tuple(result)

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical": self.canonical,
            "category": self.category.value,
            "aliases": {k: list(v) for k, v in self.aliases.items()},
            "abbreviations": list(self.abbreviations),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class ConceptMatch:
    concept: TradingConcept
    alias: str
    start: int
    end: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical": self.concept.canonical,
            "category": self.concept.category.value,
            "alias": self.alias,
            "start": self.start,
            "end": self.end,
            "metadata": dict(self.concept.metadata),
        }


class TradingOntology:
    """
    Central canonical trading vocabulary.

    Parser components must consume concepts from this registry instead of
    maintaining independent BOS/CHOCH/FVG/OB/liquidity alias lists.

    The registry normalizes terminology only. It does not invent trading logic.
    """

    def __init__(self, concepts: Iterable[TradingConcept] | None = None) -> None:
        selected = tuple(concepts) if concepts is not None else DEFAULT_CONCEPTS

        by_name: dict[str, TradingConcept] = {}
        alias_index: dict[str, TradingConcept] = {}

        for concept in selected:
            key = self._key(concept.canonical)
            if key in by_name:
                raise ValueError(f"duplicate_concept:{concept.canonical}")
            by_name[key] = concept

            for alias in concept.all_aliases():
                alias_key = self._key(alias)
                existing = alias_index.get(alias_key)
                if existing is not None and existing.canonical != concept.canonical:
                    raise ValueError(
                        f"ambiguous_ontology_alias:{alias}:{existing.canonical}:{concept.canonical}"
                    )
                alias_index[alias_key] = concept

        self._by_name = by_name
        self._alias_index = alias_index

    def get(self, canonical: str) -> TradingConcept | None:
        return self._by_name.get(self._key(canonical))

    def require(self, canonical: str) -> TradingConcept:
        concept = self.get(canonical)
        if concept is None:
            raise KeyError(f"unknown_trading_concept:{canonical}")
        return concept

    def canonicalize(self, value: str) -> str | None:
        concept = self._alias_index.get(self._key(value))
        return concept.canonical if concept is not None else None

    def category_of(self, value: str) -> ConceptCategory | None:
        canonical = self.canonicalize(value) or self._key(value).upper()
        concept = self.get(canonical)
        return concept.category if concept is not None else None

    def aliases_for(self, canonical: str) -> tuple[str, ...]:
        return self.require(canonical).all_aliases()

    def concepts(
        self,
        *,
        categories: set[ConceptCategory] | None = None,
    ) -> tuple[TradingConcept, ...]:
        values = tuple(self._by_name.values())
        if categories is None:
            return values
        return tuple(x for x in values if x.category in categories)

    def find_matches(
        self,
        text: str,
        *,
        categories: set[ConceptCategory] | None = None,
    ) -> list[ConceptMatch]:
        source = str(text or "")
        matches: list[ConceptMatch] = []

        concepts = self.concepts(categories=categories)
        candidates: list[tuple[str, TradingConcept]] = []
        for concept in concepts:
            for alias in concept.all_aliases():
                candidates.append((alias, concept))

        candidates.sort(key=lambda item: len(item[0]), reverse=True)

        occupied: list[tuple[int, int]] = []
        for alias, concept in candidates:
            pattern = re.compile(rf"(?<!\w){re.escape(alias)}(?!\w)", re.I)
            for match in pattern.finditer(source):
                if any(match.start() < end and match.end() > start for start, end in occupied):
                    continue
                occupied.append((match.start(), match.end()))
                matches.append(
                    ConceptMatch(
                        concept=concept,
                        alias=match.group(0),
                        start=match.start(),
                        end=match.end(),
                    )
                )

        return sorted(matches, key=lambda x: x.start)

    def dependency_pattern(self) -> str:
        aliases: list[str] = []
        for concept in self.concepts():
            aliases.extend(concept.all_aliases())

        unique = sorted(
            {x.upper() for x in aliases if x},
            key=len,
            reverse=True,
        )
        return "(" + "|".join(re.escape(x) for x in unique) + ")"

    @staticmethod
    def _key(value: str) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


DEFAULT_CONCEPTS: tuple[TradingConcept, ...] = (
    TradingConcept(
        canonical="BOS",
        category=ConceptCategory.STRUCTURE,
        aliases={
            "EN": ("break of structure", "structure break"),
            "RU": ("слом структуры", "слома структуры", "пробой структуры", "пробоя структуры"),
            "UA": ("злам структури", "зламу структури", "пробій структури", "пробою структури"),
        },
        abbreviations=("BOS",),
    ),
    TradingConcept(
        canonical="CHOCH",
        category=ConceptCategory.STRUCTURE,
        aliases={
            "EN": ("change of character",),
            "RU": ("смена характера", "смены характера", "чоч"),
            "UA": ("зміна характеру", "зміни характеру", "чоч"),
        },
        abbreviations=("CHOCH", "CHoCH"),
    ),
    TradingConcept(
        canonical="MSS",
        category=ConceptCategory.STRUCTURE,
        aliases={
            "EN": ("market structure shift",),
            "RU": ("смена структуры рынка",),
            "UA": ("зміна структури ринку",),
        },
        abbreviations=("MSS",),
    ),
    TradingConcept(
        canonical="FVG",
        category=ConceptCategory.ZONE,
        aliases={
            "EN": ("fair value gap",),
            "RU": ("фвг",),
            "UA": ("фвг",),
        },
        abbreviations=("FVG",),
        metadata={"family": "IMBALANCE"},
    ),
    TradingConcept(
        canonical="IFVG",
        category=ConceptCategory.ZONE,
        aliases={
            "EN": ("inverse fair value gap", "inverted fair value gap"),
            "RU": ("инверсный fvg", "инвертированный fvg"),
            "UA": ("інверсний fvg", "інвертований fvg"),
        },
        abbreviations=("IFVG",),
        metadata={"family": "IMBALANCE"},
    ),
    TradingConcept(
        canonical="ORDER_BLOCK",
        category=ConceptCategory.ZONE,
        aliases={
            "EN": ("order block", "orderblock"),
            "RU": (
                "ордер блок", "ордер блока", "ордер блоке", "ордер блоку",
                "ордерблок", "ордерблока", "ордерблоке", "ордер-блок",
            ),
            "UA": (
                "ордер блок", "ордер блока", "ордер блоці", "ордер блоку",
                "ордер-блок",
            ),
        },
        abbreviations=("OB",),
    ),
    TradingConcept(
        canonical="BREAKER_BLOCK",
        category=ConceptCategory.ZONE,
        aliases={
            "EN": ("breaker block", "breaker"),
            "RU": ("брейкер блок", "брейкер"),
            "UA": ("брейкер блок", "брейкер"),
        },
        abbreviations=("BB",),
    ),
    TradingConcept(
        canonical="MITIGATION_BLOCK",
        category=ConceptCategory.ZONE,
        aliases={
            "EN": ("mitigation block",),
            "RU": ("митигейшн блок", "блок митигации"),
            "UA": ("мітігейшн блок", "блок мітігації"),
        },
        abbreviations=("MB",),
    ),
    TradingConcept(
        canonical="LIQUIDITY_SWEEP",
        category=ConceptCategory.LIQUIDITY,
        aliases={
            "EN": ("liquidity sweep", "liquidity grab", "sweep liquidity"),
            "RU": (
                "снятие ликвидности", "снятия ликвидности", "снятии ликвидности",
                "снять ликвидность", "снимает ликвидность", "снял ликвидность",
                "свип ликвидности", "свипа ликвидности",
            ),
            "UA": (
                "зняття ліквідності", "знятті ліквідності",
                "зняти ліквідність", "знімає ліквідність", "зняв ліквідність",
                "свіп ліквідності", "свіпу ліквідності",
            ),
        },
        abbreviations=("SWEEP",),
    ),
    TradingConcept(
        canonical="BSL",
        category=ConceptCategory.LIQUIDITY,
        aliases={
            "EN": ("buy side liquidity", "buy-side liquidity"),
            "RU": ("ликвидность покупателей", "бай сайд ликвидность"),
            "UA": ("ліквідність покупців", "бай сайд ліквідність"),
        },
        abbreviations=("BSL",),
        metadata={"side": "BUY_SIDE"},
    ),
    TradingConcept(
        canonical="SSL",
        category=ConceptCategory.LIQUIDITY,
        aliases={
            "EN": ("sell side liquidity", "sell-side liquidity"),
            "RU": ("ликвидность продавцов", "селл сайд ликвидность"),
            "UA": ("ліквідність продавців", "селл сайд ліквідність"),
        },
        abbreviations=("SSL",),
        metadata={"side": "SELL_SIDE"},
    ),
    TradingConcept(
        canonical="EQH",
        category=ConceptCategory.LIQUIDITY,
        aliases={
            "EN": ("equal highs",),
            "RU": ("равные максимумы", "равных максимумов", "равные хаи", "равных хаев"),
            "UA": ("рівні максимуми", "рівних максимумів", "рівні хаї", "рівних хаїв"),
        },
        abbreviations=("EQH",),
    ),
    TradingConcept(
        canonical="EQL",
        category=ConceptCategory.LIQUIDITY,
        aliases={
            "EN": ("equal lows",),
            "RU": ("равные минимумы", "равных минимумов", "равные лои", "равных лоев"),
            "UA": ("рівні мінімуми", "рівних мінімумів", "рівні лої", "рівних лоїв"),
        },
        abbreviations=("EQL",),
    ),
    TradingConcept(
        canonical="PREVIOUS_DAY_HIGH",
        category=ConceptCategory.PRICE_REFERENCE,
        aliases={
            "EN": ("previous day high", "prior day high", "yesterday high"),
            "RU": ("максимум прошлого дня", "хай прошлого дня", "вчерашний максимум"),
            "UA": ("максимум минулого дня", "хай минулого дня", "вчорашній максимум"),
        },
        abbreviations=("PDH",),
    ),
    TradingConcept(
        canonical="PREVIOUS_DAY_LOW",
        category=ConceptCategory.PRICE_REFERENCE,
        aliases={
            "EN": ("previous day low", "prior day low", "yesterday low"),
            "RU": ("минимум прошлого дня", "лой прошлого дня", "вчерашний минимум"),
            "UA": ("мінімум минулого дня", "лой минулого дня", "вчорашній мінімум"),
        },
        abbreviations=("PDL",),
    ),
    TradingConcept(
        canonical="PREVIOUS_WEEK_HIGH",
        category=ConceptCategory.PRICE_REFERENCE,
        aliases={
            "EN": ("previous week high", "prior week high"),
            "RU": ("максимум прошлой недели", "хай прошлой недели"),
            "UA": ("максимум минулого тижня", "хай минулого тижня"),
        },
        abbreviations=("PWH",),
    ),
    TradingConcept(
        canonical="PREVIOUS_WEEK_LOW",
        category=ConceptCategory.PRICE_REFERENCE,
        aliases={
            "EN": ("previous week low", "prior week low"),
            "RU": ("минимум прошлой недели", "лой прошлой недели"),
            "UA": ("мінімум минулого тижня", "лой минулого тижня"),
        },
        abbreviations=("PWL",),
    ),
    TradingConcept(
        canonical="PREMIUM",
        category=ConceptCategory.RANGE_LOCATION,
        aliases={
            "EN": ("premium", "premium zone"),
            "RU": ("премиум", "премиум зона"),
            "UA": ("преміум", "преміум зона"),
        },
    ),
    TradingConcept(
        canonical="DISCOUNT",
        category=ConceptCategory.RANGE_LOCATION,
        aliases={
            "EN": ("discount", "discount zone"),
            "RU": ("дискаунт", "дисконт", "зона дискаунта"),
            "UA": ("дискаунт", "дисконт", "зона дискаунту"),
        },
    ),
    TradingConcept(
        canonical="EQUILIBRIUM",
        category=ConceptCategory.RANGE_LOCATION,
        aliases={
            "EN": ("equilibrium", "eq", "50 percent level"),
            "RU": ("эквилибриум", "равновесие", "уровень 50 процентов"),
            "UA": ("еквілібріум", "рівновага", "рівень 50 відсотків"),
        },
        abbreviations=("EQ",),
    ),
    TradingConcept(
        canonical="OTE",
        category=ConceptCategory.RANGE_LOCATION,
        aliases={
            "EN": ("optimal trade entry", "ote"),
            "RU": ("оптимальная точка входа",),
            "UA": ("оптимальна точка входу",),
        },
        abbreviations=("OTE",),
    ),
    TradingConcept(
        canonical="DISPLACEMENT",
        category=ConceptCategory.EVENT,
        aliases={
            "EN": ("displacement", "impulsive displacement"),
            "RU": ("дисплейсмент", "импульсное смещение"),
            "UA": ("дисплейсмент", "імпульсне зміщення"),
        },
    ),
    TradingConcept(
        canonical="IMBALANCE",
        category=ConceptCategory.ZONE,
        aliases={
            "EN": ("imbalance",),
            "RU": ("имбаланс", "дисбаланс"),
            "UA": ("імбаланс", "дисбаланс"),
        },
    ),
    TradingConcept(
        canonical="BREAK_EVEN",
        category=ConceptCategory.MANAGEMENT,
        aliases={
            "EN": ("break even", "breakeven"),
            "RU": ("безубыток", "без убытка"),
            "UA": ("беззбиток", "без збитку"),
        },
        abbreviations=("BE",),
    ),
)


DEFAULT_TRADING_ONTOLOGY = TradingOntology()