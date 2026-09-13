from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .models import (
    EqualLevel,
    LiquidityPool,
    LiquiditySide,
)


@dataclass(slots=True)
class LiquidityPoolConfig:
    minimum_strength: float = 0.0
    merge_price_tolerance: float = 0.00020
    merge_time_distance: int = 100


class LiquidityPoolBuilder:
    """
    Преобразует подтверждённые EQH/EQL в Liquidity Pool.

    BUY_SIDE:
    ликвидность над Equal Highs.

    SELL_SIDE:
    ликвидность под Equal Lows.
    """

    def __init__(
        self,
        config: LiquidityPoolConfig | None = None,
    ) -> None:
        self.config = (
            config
            if config is not None
            else LiquidityPoolConfig()
        )

        self._validate_config()

    def build(
        self,
        *,
        equal_highs: Iterable[EqualLevel],
        equal_lows: Iterable[EqualLevel],
    ) -> list[LiquidityPool]:
        pools: list[LiquidityPool] = []

        pools.extend(
            self._build_side(
                levels=list(equal_highs),
                expected_side=LiquiditySide.BUY_SIDE,
            )
        )

        pools.extend(
            self._build_side(
                levels=list(equal_lows),
                expected_side=LiquiditySide.SELL_SIDE,
            )
        )

        pools.sort(
            key=lambda pool: (
                pool.end_index,
                pool.end_time,
            )
        )

        return self._merge_nearby(
            pools
        )

    def _build_side(
        self,
        *,
        levels: list[EqualLevel],
        expected_side: LiquiditySide,
    ) -> list[LiquidityPool]:
        pools: list[LiquidityPool] = []

        for level in levels:
            if not level.confirmed:
                continue

            if level.invalidated:
                continue

            if level.side != expected_side:
                continue

            strength = self._calculate_strength(
                level
            )

            if (
                strength
                < self.config.minimum_strength
            ):
                continue

            pools.append(
                LiquidityPool(
                    side=level.side,
                    price=float(level.price),
                    start_index=int(
                        level.first_index
                    ),
                    start_time=int(
                        level.first_time
                    ),
                    end_index=int(
                        level.second_index
                    ),
                    end_time=int(
                        level.second_time
                    ),
                    source_type=(
                        level.level_type.value
                    ),
                    source_ids=[
                        level.level_id
                    ],
                    strength=float(
                        strength
                    ),
                    active=True,
                    swept=False,
                    invalidated=False,
                    metadata={
                        "touch_count": int(
                            level.touch_count
                        ),
                        "distance": float(
                            level.distance
                        ),
                        "tolerance": float(
                            level.tolerance
                        ),
                    },
                )
            )

        return pools

    @staticmethod
    def _calculate_strength(
        level: EqualLevel,
    ) -> float:
        touch_score = min(
            max(
                float(level.touch_count),
                2.0,
            ),
            5.0,
        ) / 5.0

        if level.tolerance > 0:
            precision_score = max(
                0.0,
                1.0
                - (
                    level.distance
                    / level.tolerance
                ),
            )
        else:
            precision_score = (
                1.0
                if level.distance == 0
                else 0.0
            )

        score = (
            touch_score * 60.0
            + precision_score * 40.0
        )

        return round(
            min(
                max(score, 0.0),
                100.0,
            ),
            2,
        )

    def _merge_nearby(
        self,
        pools: Iterable[LiquidityPool],
    ) -> list[LiquidityPool]:
        merged: list[LiquidityPool] = []

        for pool in pools:
            matching_pool: LiquidityPool | None = None

            for existing in reversed(
                merged
            ):
                if existing.side != pool.side:
                    continue

                price_distance = abs(
                    existing.price
                    - pool.price
                )

                index_distance = abs(
                    existing.end_index
                    - pool.start_index
                )

                if (
                    price_distance
                    <= self.config
                    .merge_price_tolerance
                    and index_distance
                    <= self.config
                    .merge_time_distance
                ):
                    matching_pool = existing
                    break

            if matching_pool is None:
                merged.append(pool)
                continue

            all_sources = [
                *matching_pool.source_ids,
                *pool.source_ids,
            ]

            matching_pool.source_ids = list(
                dict.fromkeys(
                    all_sources
                )
            )

            matching_pool.price = (
                matching_pool.price
                + pool.price
            ) / 2.0

            matching_pool.end_index = max(
                matching_pool.end_index,
                pool.end_index,
            )

            matching_pool.end_time = max(
                matching_pool.end_time,
                pool.end_time,
            )

            matching_pool.strength = round(
                min(
                    100.0,
                    max(
                        matching_pool.strength,
                        pool.strength,
                    )
                    + 5.0,
                ),
                2,
            )

            matching_pool.metadata[
                "merged_sources"
            ] = len(
                matching_pool.source_ids
            )

        return merged

    def _validate_config(
        self,
    ) -> None:
        if (
            self.config.minimum_strength
            < 0
        ):
            raise ValueError(
                "minimum_strength cannot "
                "be negative"
            )

        if (
            self.config.merge_price_tolerance
            < 0
        ):
            raise ValueError(
                "merge_price_tolerance cannot "
                "be negative"
            )

        if (
            self.config.merge_time_distance
            < 0
        ):
            raise ValueError(
                "merge_time_distance cannot "
                "be negative"
            )