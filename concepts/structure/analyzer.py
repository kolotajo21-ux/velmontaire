from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .models import SwingPoint, SwingType


@dataclass(slots=True)
class SwingAnalyzerConfig:
    left_bars: int = 2
    right_bars: int = 2
    allow_equal_highs: bool = False
    allow_equal_lows: bool = False
    minimum_price_distance: float = 0.0


class SwingAnalyzer:
    """
    Находит подтверждённые Swing High и Swing Low.

    Этот модуль:
    - не определяет HH/HL/LH/LL;
    - не ищет BOS/CHoCH;
    - не меняет тренд;
    - только выделяет локальные экстремумы.
    """

    def __init__(
        self,
        config: SwingAnalyzerConfig | None = None,
    ) -> None:
        self.config = (
            config
            if config is not None
            else SwingAnalyzerConfig()
        )

        self._validate_config()

    def analyze(
        self,
        rates: Any,
    ) -> list[SwingPoint]:
        candles = self._as_list(rates)

        minimum_bars = (
            self.config.left_bars
            + self.config.right_bars
            + 1
        )

        if len(candles) < minimum_bars:
            return []

        swings: list[SwingPoint] = []

        start_index = self.config.left_bars
        end_index = (
            len(candles)
            - self.config.right_bars
        )

        for index in range(
            start_index,
            end_index,
        ):
            candle = candles[index]

            high = self._get_float(
                candle,
                "high",
            )

            low = self._get_float(
                candle,
                "low",
            )

            candle_time = self._get_int(
                candle,
                "time",
            )

            if self._is_swing_high(
                candles=candles,
                index=index,
                price=high,
            ):
                swings.append(
                    SwingPoint(
                        index=index,
                        time=candle_time,
                        price=high,
                        swing_type=SwingType.HIGH,
                        strength=min(
                            self.config.left_bars,
                            self.config.right_bars,
                        ),
                        confirmed=True,
                        metadata={
                            "left_bars": (
                                self.config.left_bars
                            ),
                            "right_bars": (
                                self.config.right_bars
                            ),
                        },
                    )
                )

            if self._is_swing_low(
                candles=candles,
                index=index,
                price=low,
            ):
                swings.append(
                    SwingPoint(
                        index=index,
                        time=candle_time,
                        price=low,
                        swing_type=SwingType.LOW,
                        strength=min(
                            self.config.left_bars,
                            self.config.right_bars,
                        ),
                        confirmed=True,
                        metadata={
                            "left_bars": (
                                self.config.left_bars
                            ),
                            "right_bars": (
                                self.config.right_bars
                            ),
                        },
                    )
                )

        swings.sort(
            key=lambda swing: (
                swing.index,
                0
                if swing.swing_type
                == SwingType.HIGH
                else 1,
            )
        )

        return self._remove_near_duplicates(
            swings
        )

    def _is_swing_high(
        self,
        *,
        candles: list[Any],
        index: int,
        price: float,
    ) -> bool:
        if price <= 0:
            return False

        left = candles[
            index - self.config.left_bars:index
        ]

        right = candles[
            index + 1:
            index + 1 + self.config.right_bars
        ]

        left_highs = [
            self._get_float(
                candle,
                "high",
            )
            for candle in left
        ]

        right_highs = [
            self._get_float(
                candle,
                "high",
            )
            for candle in right
        ]

        if (
            len(left_highs)
            != self.config.left_bars
            or len(right_highs)
            != self.config.right_bars
        ):
            return False

        if self.config.allow_equal_highs:
            left_valid = all(
                price >= value
                for value in left_highs
            )

            right_valid = all(
                price >= value
                for value in right_highs
            )

            strict_break = (
                any(
                    price > value
                    for value in left_highs
                )
                or any(
                    price > value
                    for value in right_highs
                )
            )

            return (
                left_valid
                and right_valid
                and strict_break
            )

        return (
            all(
                price > value
                for value in left_highs
            )
            and all(
                price > value
                for value in right_highs
            )
        )

    def _is_swing_low(
        self,
        *,
        candles: list[Any],
        index: int,
        price: float,
    ) -> bool:
        if price <= 0:
            return False

        left = candles[
            index - self.config.left_bars:index
        ]

        right = candles[
            index + 1:
            index + 1 + self.config.right_bars
        ]

        left_lows = [
            self._get_float(
                candle,
                "low",
            )
            for candle in left
        ]

        right_lows = [
            self._get_float(
                candle,
                "low",
            )
            for candle in right
        ]

        if (
            len(left_lows)
            != self.config.left_bars
            or len(right_lows)
            != self.config.right_bars
        ):
            return False

        if self.config.allow_equal_lows:
            left_valid = all(
                price <= value
                for value in left_lows
            )

            right_valid = all(
                price <= value
                for value in right_lows
            )

            strict_break = (
                any(
                    price < value
                    for value in left_lows
                )
                or any(
                    price < value
                    for value in right_lows
                )
            )

            return (
                left_valid
                and right_valid
                and strict_break
            )

        return (
            all(
                price < value
                for value in left_lows
            )
            and all(
                price < value
                for value in right_lows
            )
        )

    def _remove_near_duplicates(
        self,
        swings: Iterable[SwingPoint],
    ) -> list[SwingPoint]:
        minimum_distance = max(
            0.0,
            float(
                self.config
                .minimum_price_distance
            ),
        )

        if minimum_distance <= 0:
            return list(swings)

        filtered: list[SwingPoint] = []

        for swing in swings:
            duplicate = False

            for existing in reversed(
                filtered
            ):
                if (
                    existing.swing_type
                    != swing.swing_type
                ):
                    continue

                if (
                    abs(
                        existing.price
                        - swing.price
                    )
                    < minimum_distance
                ):
                    duplicate = True
                    break

            if not duplicate:
                filtered.append(
                    swing
                )

        return filtered

    def _validate_config(
        self,
    ) -> None:
        if self.config.left_bars < 1:
            raise ValueError(
                "left_bars must be at least 1"
            )

        if self.config.right_bars < 1:
            raise ValueError(
                "right_bars must be at least 1"
            )

        if (
            self.config.minimum_price_distance
            < 0
        ):
            raise ValueError(
                "minimum_price_distance "
                "cannot be negative"
            )

    @staticmethod
    def _as_list(
        rates: Any,
    ) -> list[Any]:
        if rates is None:
            return []

        # pandas.DataFrame -> candle records.
        # list(DataFrame) returns column names, not rows.
        if hasattr(rates, "columns") and hasattr(rates, "to_dict"):
            try:
                return list(
                    rates.to_dict(
                        orient="records"
                    )
                )
            except Exception:
                return []

        try:
            return list(rates)
        except TypeError:
            return []

    @staticmethod
    def _get_float(
        candle: Any,
        field: str,
    ) -> float:
        try:
            return float(
                candle[field]
            )
        except (
            KeyError,
            IndexError,
            TypeError,
            ValueError,
        ):
            return 0.0

    @staticmethod
    def _get_int(
        candle: Any,
        field: str,
    ) -> int:
        try:
            return int(
                candle[field]
            )
        except (
            KeyError,
            IndexError,
            TypeError,
            ValueError,
        ):
            return 0