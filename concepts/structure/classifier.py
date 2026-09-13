from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .models import (
    StructureDirection,
    StructurePointType,
    SwingPoint,
    SwingType,
)


@dataclass(slots=True)
class SwingClassifierConfig:
    minimum_difference: float = 0.0
    equal_tolerance: float = 0.0


class SwingClassifier:
    """
    Классифицирует SwingPoint как HH, HL, LH или LL.

    Правила:
    - текущий HIGH выше предыдущего HIGH -> HH;
    - текущий HIGH ниже предыдущего HIGH -> LH;
    - текущий LOW выше предыдущего LOW -> HL;
    - текущий LOW ниже предыдущего LOW -> LL.

    Этот модуль не ищет BOS/CHoCH и не определяет
    окончательный тренд самостоятельно.
    """

    def __init__(
        self,
        config: SwingClassifierConfig | None = None,
    ) -> None:
        self.config = (
            config
            if config is not None
            else SwingClassifierConfig()
        )

        self._validate_config()

    def classify(
        self,
        swings: Iterable[SwingPoint],
    ) -> list[SwingPoint]:
        ordered = sorted(
            list(swings),
            key=lambda swing: (
                swing.index,
                0
                if swing.swing_type
                == SwingType.HIGH
                else 1,
            ),
        )

        previous_high: SwingPoint | None = None
        previous_low: SwingPoint | None = None

        classified: list[SwingPoint] = []

        for swing in ordered:
            if swing.swing_type == SwingType.HIGH:
                swing.point_type = self._classify_high(
                    current=swing,
                    previous=previous_high,
                )
                previous_high = swing

            elif swing.swing_type == SwingType.LOW:
                swing.point_type = self._classify_low(
                    current=swing,
                    previous=previous_low,
                )
                previous_low = swing

            classified.append(swing)

        return classified

    def infer_direction(
        self,
        swings: Iterable[SwingPoint],
    ) -> StructureDirection:
        classified = list(swings)

        if not classified:
            return StructureDirection.RANGE

        recent_types = [
            swing.point_type
            for swing in classified[-6:]
            if swing.point_type
            != StructurePointType.UNKNOWN
        ]

        bullish_score = sum(
            1
            for point_type in recent_types
            if point_type in {
                StructurePointType.HH,
                StructurePointType.HL,
            }
        )

        bearish_score = sum(
            1
            for point_type in recent_types
            if point_type in {
                StructurePointType.LH,
                StructurePointType.LL,
            }
        )

        if bullish_score >= 2 and bullish_score > bearish_score:
            return StructureDirection.BULLISH

        if bearish_score >= 2 and bearish_score > bullish_score:
            return StructureDirection.BEARISH

        return StructureDirection.RANGE

    def _classify_high(
        self,
        *,
        current: SwingPoint,
        previous: SwingPoint | None,
    ) -> StructurePointType:
        if previous is None:
            return StructurePointType.UNKNOWN

        difference = (
            current.price
            - previous.price
        )

        if self._is_effectively_equal(
            current.price,
            previous.price,
        ):
            return StructurePointType.UNKNOWN

        if (
            difference
            > self.config.minimum_difference
        ):
            return StructurePointType.HH

        if (
            difference
            < -self.config.minimum_difference
        ):
            return StructurePointType.LH

        return StructurePointType.UNKNOWN

    def _classify_low(
        self,
        *,
        current: SwingPoint,
        previous: SwingPoint | None,
    ) -> StructurePointType:
        if previous is None:
            return StructurePointType.UNKNOWN

        difference = (
            current.price
            - previous.price
        )

        if self._is_effectively_equal(
            current.price,
            previous.price,
        ):
            return StructurePointType.UNKNOWN

        if (
            difference
            > self.config.minimum_difference
        ):
            return StructurePointType.HL

        if (
            difference
            < -self.config.minimum_difference
        ):
            return StructurePointType.LL

        return StructurePointType.UNKNOWN

    def _is_effectively_equal(
        self,
        first: float,
        second: float,
    ) -> bool:
        return (
            abs(first - second)
            <= self.config.equal_tolerance
        )

    def _validate_config(
        self,
    ) -> None:
        if (
            self.config.minimum_difference
            < 0
        ):
            raise ValueError(
                "minimum_difference "
                "cannot be negative"
            )

        if (
            self.config.equal_tolerance
            < 0
        ):
            raise ValueError(
                "equal_tolerance "
                "cannot be negative"
            )