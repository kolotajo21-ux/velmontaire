from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .models import (
    MitigationStatus,
    OrderBlock,
    OrderBlockType,
)


@dataclass(slots=True)
class MitigationConfig:
    partial_fill_threshold: float = 0.25
    mitigated_fill_threshold: float = 0.75
    invalidate_on_close_through: bool = True
    use_last_closed_candle: bool = True


class MitigationAnalyzer:
    """
    Отслеживает жизненный цикл Order Block.

    ВАЖНО:
    mitigation начинается только ПОСЛЕ impulse/BOS candle.
    Свечи формирования OB и самого импульса не считаются ретестом.
    """

    def __init__(
        self,
        config: MitigationConfig | None = None,
    ) -> None:
        self.config = (
            config
            if config is not None
            else MitigationConfig()
        )

        self._validate_config()

    def update(
        self,
        *,
        rates: Any,
        block: OrderBlock,
    ) -> OrderBlock:
        candles = self._as_list(rates)

        if not candles:
            return block

        last_index = (
            len(candles) - 2
            if self.config.use_last_closed_candle
            else len(candles) - 1
        )

        # Ретест OB может существовать только ПОСЛЕ BOS/impulse candle.
        start_index = max(
            int(block.impulse_index) + 1,
            int(block.index) + 1,
        )

        if last_index < start_index:
            return block

        first_touch_time: int | None = (
            block.mitigation.first_touch_time
        )

        last_touch_time: int | None = (
            block.mitigation.last_touch_time
        )

        touch_count = int(
            block.mitigation.touch_count
        )

        maximum_fill = float(
            block.mitigation.filled_percent
        )

        status = block.mitigation.status

        for index in range(
            start_index,
            last_index + 1,
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
            close = self._get_float(
                candle,
                "close",
            )
            candle_time = self._get_int(
                candle,
                "time",
            )

            if self._is_invalidated(
                block=block,
                close=close,
            ):
                status = (
                    MitigationStatus.INVALIDATED
                )

                block.active = False

                block.mitigation.metadata[
                    "invalidation_time"
                ] = int(
                    candle_time
                )

                block.mitigation.metadata[
                    "invalidation_close"
                ] = float(
                    close
                )

                break

            if not self._is_touched(
                block=block,
                high=high,
                low=low,
            ):
                continue

            touch_count += 1

            if first_touch_time is None:
                first_touch_time = int(
                    candle_time
                )

            last_touch_time = int(
                candle_time
            )

            fill_percent = (
                self._fill_percent(
                    block=block,
                    high=high,
                    low=low,
                )
            )

            maximum_fill = max(
                maximum_fill,
                fill_percent,
            )

            status = self._status_from_fill(
                maximum_fill
            )

            if (
                status
                == MitigationStatus.MITIGATED
            ):
                block.active = False
                break

        block.mitigation.first_touch_time = (
            first_touch_time
        )

        block.mitigation.last_touch_time = (
            last_touch_time
        )

        block.mitigation.touch_count = int(
            touch_count
        )

        block.mitigation.filled_percent = round(
            min(
                max(
                    maximum_fill,
                    0.0,
                ),
                100.0,
            ),
            2,
        )

        block.mitigation.status = status

        block.mitigation.metadata.update(
            {
                "partial_fill_threshold": float(
                    self.config
                    .partial_fill_threshold
                ),
                "mitigated_fill_threshold": float(
                    self.config
                    .mitigated_fill_threshold
                ),
                "mitigation_start_index": int(
                    start_index
                ),
                "impulse_index": int(
                    block.impulse_index
                ),
            }
        )

        return block

    def update_many(
        self,
        *,
        rates: Any,
        blocks: Iterable[OrderBlock],
    ) -> list[OrderBlock]:
        return [
            self.update(
                rates=rates,
                block=block,
            )
            for block in blocks
        ]

    @staticmethod
    def _is_touched(
        *,
        block: OrderBlock,
        high: float,
        low: float,
    ) -> bool:
        return (
            low <= block.high
            and high >= block.low
        )

    def _is_invalidated(
        self,
        *,
        block: OrderBlock,
        close: float,
    ) -> bool:
        if not (
            self.config
            .invalidate_on_close_through
        ):
            return False

        if (
            block.block_type
            == OrderBlockType.BULLISH
        ):
            return close < block.low

        return close > block.high

    @staticmethod
    def _fill_percent(
        *,
        block: OrderBlock,
        high: float,
        low: float,
    ) -> float:
        block_range = (
            block.high
            - block.low
        )

        if block_range <= 0:
            return 0.0

        if (
            block.block_type
            == OrderBlockType.BULLISH
        ):
            deepest_price = max(
                min(
                    low,
                    block.high,
                ),
                block.low,
            )

            filled = (
                block.high
                - deepest_price
            )

        else:
            deepest_price = min(
                max(
                    high,
                    block.low,
                ),
                block.high,
            )

            filled = (
                deepest_price
                - block.low
            )

        return (
            filled
            / block_range
            * 100.0
        )

    def _status_from_fill(
        self,
        fill_percent: float,
    ) -> MitigationStatus:
        partial_threshold = (
            self.config
            .partial_fill_threshold
            * 100.0
        )

        mitigated_threshold = (
            self.config
            .mitigated_fill_threshold
            * 100.0
        )

        if (
            fill_percent
            >= mitigated_threshold
        ):
            return (
                MitigationStatus.MITIGATED
            )

        if (
            fill_percent
            >= partial_threshold
        ):
            return (
                MitigationStatus.PARTIAL
            )

        if fill_percent > 0:
            return (
                MitigationStatus.TOUCHED
            )

        return (
            MitigationStatus.FRESH
        )

    def _validate_config(
        self,
    ) -> None:
        if not (
            0.0
            <= self.config
            .partial_fill_threshold
            <= 1.0
        ):
            raise ValueError(
                "partial_fill_threshold "
                "must be between 0 and 1"
            )

        if not (
            0.0
            <= self.config
            .mitigated_fill_threshold
            <= 1.0
        ):
            raise ValueError(
                "mitigated_fill_threshold "
                "must be between 0 and 1"
            )

        if (
            self.config
            .mitigated_fill_threshold
            < self.config
            .partial_fill_threshold
        ):
            raise ValueError(
                "mitigated_fill_threshold "
                "cannot be smaller than "
                "partial_fill_threshold"
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