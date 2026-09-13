from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class LanguageProfile:
    primary: str
    detected: tuple[str, ...]
    mixed: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "primary": self.primary,
            "detected": list(self.detected),
            "mixed": self.mixed,
        }


# Conservative phrase vocabulary.  It normalizes wording, not trading logic.
# Unknown strategy concepts are deliberately left untouched for later
# clarification/capability resolution.
LANGUAGE_MARKERS: dict[str, tuple[str, ...]] = {
    "RU": (
        "если", "когда", "после", "перед", "покуп", "продав", "риск",
        "свеч", "цена", "рын", "стоп", "тейк", "ликвидност",
    ),
    "UA": (
        "якщо", "коли", "після", "перед", "куп", "прод", "ризик",
        "свіч", "ціна", "рин", "збит", "прибут", "ліквідност",
    ),
    "EN": (
        "when", "if", "after", "before", "buy", "sell", "risk",
        "candle", "price", "market", "stop", "take", "liquidity",
    ),
}


GENERAL_ALIASES: dict[str, tuple[str, ...]] = {
    "WHEN": (
        "when", "когда", "коли",
    ),
    "IF": (
        "if", "если", "якщо",
    ),
    "AFTER": (
        "after", "после", "після",
    ),
    "BEFORE": (
        "before", "до", "перед", "перед тим як",
    ),
    "THEN": (
        "then", "затем", "потом", "после этого",
        "потім", "далі", "після цього",
    ),
    "AND": (
        "and", "и", "та", "і",
    ),
    "OR": (
        "or", "или", "або",
    ),
    "NOT": (
        "not", "не",
    ),
    "ENTRY": (
        "entry", "enter", "вход", "входить", "войти",
        "вхід", "входити", "увійти",
    ),
    "RISK": (
        "risk", "риск", "ризик",
    ),
    "STOP LOSS": (
        "stop loss", "stoploss", "sl",
        "стоп лосс", "стоп-лосс", "стоп",
        "стоп лос", "стоп-лос",
    ),
    "TAKE PROFIT": (
        "take profit", "takeprofit", "tp",
        "тейк профит", "тейк-профит", "тейк",
        "тейк профіт", "тейк-профіт",
    ),
    "RISK REWARD": (
        "risk reward", "risk/reward", "r:r", "rr",
        "риск прибыль", "риск/прибыль",
        "ризик прибуток", "ризик/прибуток",
    ),
    "PIPS": (
        "pips", "pip",
        "пипсов", "пипса", "пипс", "піпсів", "піпса", "піпс",
    ),
    "POINTS": (
        "points", "point",
        "пунктов", "пункта", "пунктів", "пункти", "пункт",
    ),
    "PERCENT": (
        "percent", "процентов", "процента", "процент",
        "відсотків", "відсотка", "відсоток",
    ),
    "PRICE": (
        "price", "цена", "ціна",
    ),
    "CLOSE": (
        "close", "closing price", "закрытие", "закрывается", "закрылся",
        "закриття", "закривається", "закрився",
    ),
    "ABOVE": (
        "above", "higher than", "выше", "над", "вище",
    ),
    "BELOW": (
        "below", "lower than", "ниже", "под", "нижче",
    ),
    "CROSSES": (
        "crosses", "cross", "crosses over",
        "пересекает", "пересечение", "пересекает вверх", "перетинає",
        "перетин", "перетинає вгору",
    ),
    "FIXED": (
        "fixed", "фиксированный", "фиксировано", "фіксований", "фіксовано",
    ),
}


def detect_languages(text: str) -> LanguageProfile:
    source = str(text or "").lower()
    scores: dict[str, int] = {"RU": 0, "UA": 0, "EN": 0}

    for language, markers in LANGUAGE_MARKERS.items():
        for marker in markers:
            if re.search(rf"(?<!\w){re.escape(marker)}\w*", source, re.I):
                scores[language] += 1

    detected = tuple(
        language
        for language, score in sorted(scores.items())
        if score > 0
    )

    if not detected:
        # Trading text often consists mostly of universal symbols/abbreviations.
        primary = "UNKNOWN"
    else:
        primary = max(scores, key=scores.get)

    return LanguageProfile(
        primary=primary,
        detected=detected,
        mixed=len(detected) > 1,
    )


def iter_aliases(
    aliases: dict[str, tuple[str, ...]],
) -> Iterable[tuple[str, str]]:
    for canonical, variants in aliases.items():
        for alias in sorted(variants, key=len, reverse=True):
            yield canonical, alias
