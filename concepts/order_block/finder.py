from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .models import (
    OrderBlock,
    OrderBlockType,
)


@dataclass(slots=True)
class OrderBlockFinderConfig:
    search_bars_before_bos: int = 12
    require_sweep_before_bos: bool = True
    require_direction_alignment: bool = True
    minimum_candle_body_ratio: float = 0.0


class OrderBlockFinder:
    """
    Ищет базовую свечу Order Block перед подтверждённым BOS.

    Bullish OB:
    последняя bearish-свеча перед bullish BOS.

    Bearish OB:
    последняя bullish-свеча перед bearish BOS.

    Дополнительно:
    - может требовать Liquidity Sweep до BOS;
    - может требовать совпадение направления Sweep и BOS;
    - ограничивает глубину поиска перед BOS.
    """

    def __init__(
        self,
        config: OrderBlockFinderConfig | None = None,
    ) -> None:
        self.config = (
            config
            if config is not None
            else OrderBlockFinderConfig()
        )

        self._validate_config()

    def find(
        self,
        *,
        rates: Any,
        bos: Mapping[str, Any] | None,
        sweep: Mapping[str, Any] | None,
    ) -> OrderBlock | None:
        candles = self._as_list(rates)

        if not candles or bos is None:
            return None

        direction = str(
            bos.get(
                "direction",
                "",
            )
        ).upper()

        if direction not in {
            "BULLISH",
            "BEARISH",
        }:
            return None

        bos_time = self._as_int(
            bos.get("time")
        )

        bos_index = self._find_index_by_time(
            candles,
            bos_time,
        )

        if bos_index is None:
            bos_index = self._as_optional_int(
                bos.get("index")
            )

        if (
            bos_index is None
            or bos_index <= 0
            or bos_index >= len(candles)
        ):
            return None

        if not self._sweep_is_valid(
            bos=bos,
            sweep=sweep,
            direction=direction,
        ):
            return None

        search_start = max(
            0,
            bos_index
            - self.config.search_bars_before_bos,
        )

        sweep_index = self._sweep_index(
            candles=candles,
            sweep=sweep,
        )

        if (
            self.config.require_sweep_before_bos
            and sweep_index is not None
        ):
            search_start = max(
                search_start,
                sweep_index,
            )

        for index in range(
            bos_index - 1,
            search_start - 1,
            -1,
        ):
            candle = candles[index]

            open_price = self._get_float(
                candle,
                "open",
            )
            close_price = self._get_float(
                candle,
                "close",
            )
            high = self._get_float(
                candle,
                "high",
            )
            low = self._get_float(
                candle,
                "low",
            )

            candle_range = high - low

            if candle_range <= 0:
                continue

            body_ratio = (
                abs(close_price - open_price)
                / candle_range
            )

            if (
                body_ratio
                < self.config.minimum_candle_body_ratio
            ):
                continue

            if direction == "BULLISH":
                is_opposite = (
                    close_price < open_price
                )
                block_type = (
                    OrderBlockType.BULLISH
                )
            else:
                is_opposite = (
                    close_price > open_price
                )
                block_type = (
                    OrderBlockType.BEARISH
                )

            if not is_opposite:
                continue

            candle_time = self._get_int(
                candle,
                "time",
            )

            block_id = (
                f"{block_type.value}:"
                f"{candle_time}:"
                f"{bos_time}"
            )

            return OrderBlock(
                block_id=block_id,
                block_type=block_type,
                high=float(high),
                low=float(low),
                open_price=float(
                    open_price
                ),
                close_price=float(
                    close_price
                ),
                index=int(index),
                time=int(candle_time),
                impulse_index=int(
                    bos_index
                ),
                impulse_time=int(
                    bos_time
                ),
                metadata={
                    "bos_direction": direction,
                    "bos_time": int(
                        bos_time
                    ),
                    "bos_index": int(
                        bos_index
                    ),
                    "body_ratio": float(
                        body_ratio
                    ),
                    "bars_to_bos": int(
                        bos_index - index
                    ),
                    "sweep_time": (
                        self._as_int(
                            sweep.get("time")
                        )
                        if sweep is not None
                        else None
                    ),
                    "sweep_direction": (
                        str(
                            sweep.get(
                                "direction",
                                "",
                            )
                        ).upper()
                        if sweep is not None
                        else None
                    ),
                },
            )

        return None

    def _sweep_is_valid(
        self,
        *,
        bos: Mapping[str, Any],
        sweep: Mapping[str, Any] | None,
        direction: str,
    ) -> bool:
        if sweep is None:
            return not (
                self.config
                .require_sweep_before_bos
            )

        sweep_direction = str(
            sweep.get(
                "direction",
                "",
            )
        ).upper()

        if (
            self.config.require_direction_alignment
            and sweep_direction != direction
        ):
            return False

        bos_time = self._as_int(
            bos.get("time")
        )

        sweep_time = self._as_int(
            sweep.get("time")
        )

        if (
            self.config.require_sweep_before_bos
            and sweep_time > bos_time
        ):
            return False

        return True

    def _sweep_index(
        self,
        *,
        candles: list[Any],
        sweep: Mapping[str, Any] | None,
    ) -> int | None:
        if sweep is None:
            return None

        sweep_time = self._as_int(
            sweep.get("time")
        )

        index = self._find_index_by_time(
            candles,
            sweep_time,
        )

        if index is not None:
            return index

        return self._as_optional_int(
            sweep.get("index")
        )

    @staticmethod
    def _find_index_by_time(
        candles: list[Any],
        candle_time: int,
    ) -> int | None:
        for index, candle in enumerate(
            candles
        ):
            try:
                if int(
                    candle["time"]
                ) == int(candle_time):
                    return index
            except (
                KeyError,
                IndexError,
                TypeError,
                ValueError,
            ):
                continue

        return None

    def _validate_config(
        self,
    ) -> None:
        if (
            self.config.search_bars_before_bos
            < 1
        ):
            raise ValueError(
                "search_bars_before_bos "
                "must be at least 1"
            )

        if not (
            0.0
            <= self.config
            .minimum_candle_body_ratio
            <= 1.0
        ):
            raise ValueError(
                "minimum_candle_body_ratio "
                "must be between 0 and 1"
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

    @staticmethod
    def _as_int(
        value: Any,
    ) -> int:
        try:
            return int(value)
        except (
            TypeError,
            ValueError,
        ):
            return 0

    @staticmethod
    def _as_optional_int(
        value: Any,
    ) -> int | None:
        try:
            return int(value)
        except (
            TypeError,
            ValueError,
        ):
            return None