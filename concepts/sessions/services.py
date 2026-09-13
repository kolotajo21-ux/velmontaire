from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .finder import (
    SessionFinder,
    SessionFinderConfig,
)
from .models import (
    PremiumDiscountZone,
    SessionState,
    SessionType,
)


@dataclass(slots=True)
class SessionServiceConfig:
    asia_start_utc: int = 0
    asia_end_utc: int = 7

    london_start_utc: int = 7
    london_end_utc: int = 12

    new_york_start_utc: int = 12
    new_york_end_utc: int = 21

    use_last_closed_candle: bool = True

    premium_discount_source: str = (
        "PREVIOUS_DAY"
    )


class SessionService:
    """
    Высокоуровневый сервис сессий.

    Собирает:
    - Asia / London / New York;
    - Session High / Low;
    - PDH / PDL;
    - Premium / Discount.
    """

    def __init__(
        self,
        config: SessionServiceConfig | None = None,
    ) -> None:
        self.config = (
            config
            if config is not None
            else SessionServiceConfig()
        )

        self._validate_config()

        self.finder = SessionFinder(
            SessionFinderConfig(
                asia_start_utc=(
                    self.config.asia_start_utc
                ),
                asia_end_utc=(
                    self.config.asia_end_utc
                ),
                london_start_utc=(
                    self.config.london_start_utc
                ),
                london_end_utc=(
                    self.config.london_end_utc
                ),
                new_york_start_utc=(
                    self.config.new_york_start_utc
                ),
                new_york_end_utc=(
                    self.config.new_york_end_utc
                ),
                use_last_closed_candle=(
                    self.config.use_last_closed_candle
                ),
            )
        )

    def analyze(
        self,
        *,
        rates: Any,
    ) -> SessionState:
        candles = self._as_list(
            rates
        )

        if not candles:
            return SessionState(
                diagnostics={
                    "candles": 0,
                    "reason": "rates_missing",
                }
            )

        sessions = self.finder.find_sessions(
            candles
        )

        previous_day = (
            self.finder.find_previous_day(
                candles
            )
        )

        premium_discount = (
            self._build_premium_discount(
                sessions=sessions,
                previous_day=previous_day,
            )
        )

        asia = sessions.get(
            SessionType.ASIA
        )

        london = sessions.get(
            SessionType.LONDON
        )

        new_york = sessions.get(
            SessionType.NEW_YORK
        )

        diagnostics = {
            "candles": len(candles),
            "asia_found": (
                asia is not None
            ),
            "london_found": (
                london is not None
            ),
            "new_york_found": (
                new_york is not None
            ),
            "previous_day_found": (
                previous_day is not None
            ),
            "premium_discount_found": (
                premium_discount
                is not None
            ),
            "premium_discount_source": (
                self.config
                .premium_discount_source
            ),
        }

        return SessionState(
            asia=asia,
            london=london,
            new_york=new_york,
            previous_day=previous_day,
            premium_discount=(
                premium_discount
            ),
            diagnostics=diagnostics,
        )

    def _build_premium_discount(
        self,
        *,
        sessions: dict[
            SessionType,
            Any,
        ],
        previous_day: Any,
    ) -> PremiumDiscountZone | None:
        source = str(
            self.config
            .premium_discount_source
        ).upper()

        high: float | None = None
        low: float | None = None

        if (
            source == "PREVIOUS_DAY"
            and previous_day is not None
        ):
            high = float(
                previous_day.high
            )
            low = float(
                previous_day.low
            )

        elif source == "ASIA":
            zone = sessions.get(
                SessionType.ASIA
            )
            if zone is not None:
                high = float(
                    zone.high
                )
                low = float(
                    zone.low
                )

        elif source == "LONDON":
            zone = sessions.get(
                SessionType.LONDON
            )
            if zone is not None:
                high = float(
                    zone.high
                )
                low = float(
                    zone.low
                )

        elif source == "NEW_YORK":
            zone = sessions.get(
                SessionType.NEW_YORK
            )
            if zone is not None:
                high = float(
                    zone.high
                )
                low = float(
                    zone.low
                )

        if (
            high is None
            or low is None
            or high <= low
        ):
            return None

        equilibrium = (
            high + low
        ) / 2.0

        return PremiumDiscountZone(
            equilibrium=float(
                equilibrium
            ),
            premium_high=float(
                high
            ),
            premium_low=float(
                equilibrium
            ),
            discount_high=float(
                equilibrium
            ),
            discount_low=float(
                low
            ),
        )

    def best_session_range(
        self,
        state: SessionState,
    ) -> tuple[
        str,
        float,
        float,
    ] | None:
        candidates = []

        for name, zone in (
            ("ASIA", state.asia),
            ("LONDON", state.london),
            ("NEW_YORK", state.new_york),
        ):
            if zone is None:
                continue

            candidates.append(
                (
                    name,
                    float(zone.high),
                    float(zone.low),
                    float(zone.range),
                )
            )

        if not candidates:
            return None

        best = max(
            candidates,
            key=lambda item: (
                item[3]
            ),
        )

        return (
            best[0],
            best[1],
            best[2],
        )

    def _validate_config(
        self,
    ) -> None:
        source = str(
            self.config
            .premium_discount_source
        ).upper()

        if source not in {
            "PREVIOUS_DAY",
            "ASIA",
            "LONDON",
            "NEW_YORK",
        }:
            raise ValueError(
                "premium_discount_source "
                "must be PREVIOUS_DAY, ASIA, "
                "LONDON or NEW_YORK"
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
