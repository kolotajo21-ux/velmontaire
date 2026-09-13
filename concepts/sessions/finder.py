from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .models import (
    PreviousDayLevels,
    SessionType,
    SessionZone,
)


@dataclass(slots=True)
class SessionWindow:
    session_type: SessionType

    start_hour_utc: int
    end_hour_utc: int


@dataclass(slots=True)
class SessionFinderConfig:
    asia_start_utc: int = 0
    asia_end_utc: int = 7

    london_start_utc: int = 7
    london_end_utc: int = 12

    new_york_start_utc: int = 12
    new_york_end_utc: int = 21

    use_last_closed_candle: bool = True


class SessionFinder:
    """
    Находит диапазоны торговых сессий и PDH/PDL.

    Времена задаются в UTC.
    Это позволяет позже корректно отображать
    их в любом часовом поясе сайта пользователя.
    """

    def __init__(
        self,
        config: SessionFinderConfig | None = None,
    ) -> None:
        self.config = (
            config
            if config is not None
            else SessionFinderConfig()
        )

        self._validate_config()

        self.windows = (
            SessionWindow(
                session_type=SessionType.ASIA,
                start_hour_utc=self.config.asia_start_utc,
                end_hour_utc=self.config.asia_end_utc,
            ),
            SessionWindow(
                session_type=SessionType.LONDON,
                start_hour_utc=self.config.london_start_utc,
                end_hour_utc=self.config.london_end_utc,
            ),
            SessionWindow(
                session_type=SessionType.NEW_YORK,
                start_hour_utc=self.config.new_york_start_utc,
                end_hour_utc=self.config.new_york_end_utc,
            ),
        )

    def find_sessions(
        self,
        rates: Any,
    ) -> dict[SessionType, SessionZone]:
        candles = self._as_list(
            rates
        )

        if not candles:
            return {}

        last_index = (
            len(candles) - 2
            if self.config.use_last_closed_candle
            else len(candles) - 1
        )

        if last_index < 0:
            return {}

        usable = candles[
            : last_index + 1
        ]

        latest_time = self._get_int(
            usable[-1],
            "time",
        )

        latest_day = self._utc_day_key(
            latest_time
        )

        result: dict[
            SessionType,
            SessionZone
        ] = {}

        for window in self.windows:
            session_candles = [
                candle
                for candle in usable
                if (
                    self._utc_day_key(
                        self._get_int(
                            candle,
                            "time",
                        )
                    )
                    == latest_day
                    and self._in_window(
                        timestamp=self._get_int(
                            candle,
                            "time",
                        ),
                        start_hour=(
                            window.start_hour_utc
                        ),
                        end_hour=(
                            window.end_hour_utc
                        ),
                    )
                )
            ]

            if not session_candles:
                continue

            result[
                window.session_type
            ] = self._build_zone(
                session_type=(
                    window.session_type
                ),
                candles=session_candles,
                latest_time=latest_time,
                start_hour=(
                    window.start_hour_utc
                ),
                end_hour=(
                    window.end_hour_utc
                ),
            )

        return result

    def find_previous_day(
        self,
        rates: Any,
    ) -> PreviousDayLevels | None:
        candles = self._as_list(
            rates
        )

        if not candles:
            return None

        last_index = (
            len(candles) - 2
            if self.config.use_last_closed_candle
            else len(candles) - 1
        )

        if last_index < 0:
            return None

        usable = candles[
            : last_index + 1
        ]

        day_keys = sorted(
            {
                self._utc_day_key(
                    self._get_int(
                        candle,
                        "time",
                    )
                )
                for candle in usable
            }
        )

        if len(day_keys) < 2:
            return None

        previous_day_key = (
            day_keys[-2]
        )

        previous_day_candles = [
            candle
            for candle in usable
            if (
                self._utc_day_key(
                    self._get_int(
                        candle,
                        "time",
                    )
                )
                == previous_day_key
            )
        ]

        if not previous_day_candles:
            return None

        high = max(
            self._get_float(
                candle,
                "high",
            )
            for candle
            in previous_day_candles
        )

        low = min(
            self._get_float(
                candle,
                "low",
            )
            for candle
            in previous_day_candles
        )

        return PreviousDayLevels(
            high=float(high),
            low=float(low),
            date=int(
                previous_day_key
            ),
        )

    def _build_zone(
        self,
        *,
        session_type: SessionType,
        candles: list[Any],
        latest_time: int,
        start_hour: int,
        end_hour: int,
    ) -> SessionZone:
        first = candles[0]
        last = candles[-1]

        high = max(
            self._get_float(
                candle,
                "high",
            )
            for candle in candles
        )

        low = min(
            self._get_float(
                candle,
                "low",
            )
            for candle in candles
        )

        start_time = self._get_int(
            first,
            "time",
        )

        end_time = self._get_int(
            last,
            "time",
        )

        active = self._in_window(
            timestamp=latest_time,
            start_hour=start_hour,
            end_hour=end_hour,
        )

        return SessionZone(
            session_type=session_type,
            start_time=int(
                start_time
            ),
            end_time=int(
                end_time
            ),
            high=float(
                high
            ),
            low=float(
                low
            ),
            open_price=float(
                self._get_float(
                    first,
                    "open",
                )
            ),
            close_price=float(
                self._get_float(
                    last,
                    "close",
                )
            ),
            active=bool(
                active
            ),
            metadata={
                "start_hour_utc": int(
                    start_hour
                ),
                "end_hour_utc": int(
                    end_hour
                ),
                "candle_count": len(
                    candles
                ),
            },
        )

    @staticmethod
    def _in_window(
        *,
        timestamp: int,
        start_hour: int,
        end_hour: int,
    ) -> bool:
        dt = datetime.fromtimestamp(
            timestamp,
            tz=timezone.utc,
        )

        hour = dt.hour

        if start_hour < end_hour:
            return (
                start_hour
                <= hour
                < end_hour
            )

        return (
            hour >= start_hour
            or hour < end_hour
        )

    @staticmethod
    def _utc_day_key(
        timestamp: int,
    ) -> int:
        dt = datetime.fromtimestamp(
            timestamp,
            tz=timezone.utc,
        )

        day_start = datetime(
            dt.year,
            dt.month,
            dt.day,
            tzinfo=timezone.utc,
        )

        return int(
            day_start.timestamp()
        )

    def _validate_config(
        self,
    ) -> None:
        hours = [
            self.config.asia_start_utc,
            self.config.asia_end_utc,
            self.config.london_start_utc,
            self.config.london_end_utc,
            self.config.new_york_start_utc,
            self.config.new_york_end_utc,
        ]

        if any(
            hour < 0
            or hour > 23
            for hour in hours
        ):
            raise ValueError(
                "Session hours must be "
                "between 0 and 23"
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