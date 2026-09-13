from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from concepts.structure.models import (
    SwingPoint,
    SwingType,
)

from .models import (
    EqualLevel,
    EqualLevelType,
    LiquiditySide,
)


@dataclass(slots=True)
class EqualLevelsConfig:
    absolute_tolerance: float = 0.00020
    relative_tolerance: float = 0.0
    minimum_bars_between: int = 3
    maximum_bars_between: int = 200
    minimum_touches: int = 2


class EqualLevelsAnalyzer:
    """
    Находит Equal Highs и Equal Lows по подтверждённым свингам.

    EQH:
    два Swing High находятся достаточно близко по цене.

    EQL:
    два Swing Low находятся достаточно близко по цене.
    """

    def __init__(
        self,
        config: EqualLevelsConfig | None = None,
    ) -> None:
        self.config = (
            config
            if config is not None
            else EqualLevelsConfig()
        )

        self._validate_config()

    def analyze(
        self,
        swings: Iterable[SwingPoint],
    ) -> tuple[
        list[EqualLevel],
        list[EqualLevel],
    ]:
        ordered = sorted(
            list(swings),
            key=lambda swing: (
                swing.index,
                swing.time,
            ),
        )

        highs = [
            swing
            for swing in ordered
            if swing.swing_type
            == SwingType.HIGH
        ]

        lows = [
            swing
            for swing in ordered
            if swing.swing_type
            == SwingType.LOW
        ]

        equal_highs = self._find_equal_levels(
            swings=highs,
            level_type=EqualLevelType.EQH,
            side=LiquiditySide.BUY_SIDE,
        )

        equal_lows = self._find_equal_levels(
            swings=lows,
            level_type=EqualLevelType.EQL,
            side=LiquiditySide.SELL_SIDE,
        )

        return equal_highs, equal_lows

    def _find_equal_levels(
        self,
        *,
        swings: list[SwingPoint],
        level_type: EqualLevelType,
        side: LiquiditySide,
    ) -> list[EqualLevel]:
        levels: list[EqualLevel] = []

        for current_index in range(
            1,
            len(swings),
        ):
            current = swings[current_index]

            for previous_index in range(
                current_index - 1,
                -1,
                -1,
            ):
                previous = swings[previous_index]

                bars_between = (
                    current.index
                    - previous.index
                )

                if (
                    bars_between
                    < self.config.minimum_bars_between
                ):
                    continue

                if (
                    bars_between
                    > self.config.maximum_bars_between
                ):
                    break

                tolerance = self._tolerance(
                    previous.price,
                    current.price,
                )

                distance = abs(
                    current.price
                    - previous.price
                )

                if distance > tolerance:
                    continue

                average_price = (
                    previous.price
                    + current.price
                ) / 2.0

                levels.append(
                    EqualLevel(
                        level_type=level_type,
                        side=side,
                        price=float(
                            average_price
                        ),
                        first_index=int(
                            previous.index
                        ),
                        first_time=int(
                            previous.time
                        ),
                        second_index=int(
                            current.index
                        ),
                        second_time=int(
                            current.time
                        ),
                        distance=float(
                            distance
                        ),
                        tolerance=float(
                            tolerance
                        ),
                        confirmed=True,
                        tested=False,
                        invalidated=False,
                        touch_count=2,
                        metadata={
                            "first_price": float(
                                previous.price
                            ),
                            "second_price": float(
                                current.price
                            ),
                            "bars_between": int(
                                bars_between
                            ),
                        },
                    )
                )

                break

        return self._remove_duplicates(
            levels
        )

    def _tolerance(
        self,
        first_price: float,
        second_price: float,
    ) -> float:
        absolute = max(
            0.0,
            float(
                self.config
                .absolute_tolerance
            ),
        )

        reference_price = max(
            abs(first_price),
            abs(second_price),
        )

        relative = (
            reference_price
            * max(
                0.0,
                float(
                    self.config
                    .relative_tolerance
                ),
            )
        )

        return max(
            absolute,
            relative,
        )

    @staticmethod
    def _remove_duplicates(
        levels: Iterable[EqualLevel],
    ) -> list[EqualLevel]:
        filtered: list[EqualLevel] = []

        seen: set[
            tuple[str, int, int]
        ] = set()

        for level in levels:
            level_key = (
                level.level_type.value,
                int(level.first_index),
                int(level.second_index),
            )

            if level_key in seen:
                continue

            seen.add(level_key)
            filtered.append(level)

        return filtered

    def _validate_config(
        self,
    ) -> None:
        if (
            self.config.absolute_tolerance
            < 0
        ):
            raise ValueError(
                "absolute_tolerance "
                "cannot be negative"
            )

        if (
            self.config.relative_tolerance
            < 0
        ):
            raise ValueError(
                "relative_tolerance "
                "cannot be negative"
            )

        if (
            self.config.minimum_bars_between
            < 1
        ):
            raise ValueError(
                "minimum_bars_between "
                "must be at least 1"
            )

        if (
            self.config.maximum_bars_between
            < self.config.minimum_bars_between
        ):
            raise ValueError(
                "maximum_bars_between "
                "cannot be smaller than "
                "minimum_bars_between"
            )

        if self.config.minimum_touches < 2:
            raise ValueError(
                "minimum_touches must "
                "be at least 2"
            )