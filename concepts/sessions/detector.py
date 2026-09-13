from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from core.detector import (
    BaseDetector,
    DetectorContext,
    DetectorResult,
)

from .models import (
    SessionState,
)
from .services import (
    SessionService,
    SessionServiceConfig,
)


@dataclass(slots=True)
class SessionDetectorConfig:
    timeframe: str = "M15"

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


class SessionDetector(BaseDetector):
    """
    Thin session detector.

    Heavy logic lives in SessionService:
    sessions -> PDH/PDL -> Premium/Discount -> SessionState.
    """

    name = "sessions"
    version = "1.0.0"

    dependencies: tuple[str, ...] = ()

    def __init__(
        self,
        config: SessionDetectorConfig | None = None,
    ) -> None:
        self.config = (
            config
            if config is not None
            else SessionDetectorConfig()
        )

        self._validate_config()

        self.service = SessionService(
            SessionServiceConfig(
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
                premium_discount_source=(
                    self.config.premium_discount_source
                ),
            )
        )

    def analyze(
        self,
        context: DetectorContext,
        snapshot: Mapping[str, Any],
    ) -> DetectorResult:
        timeframe = str(
            self.config.timeframe
        ).upper()

        rates = context.get_rates(
            timeframe
        )

        candles = self._as_list(
            rates
        )

        diagnostics: dict[str, Any] = {
            "symbol": context.symbol,
            "timeframe": timeframe,
            "candles": len(candles),
        }

        if not candles:
            diagnostics[
                "rejection_reason"
            ] = "rates_missing"

            empty_state = SessionState(
                diagnostics=diagnostics
            )

            return self.success(
                data=empty_state.to_dict(),
                events=[],
                diagnostics=diagnostics,
            )

        state = self.service.analyze(
            rates=candles
        )

        diagnostics.update(
            state.diagnostics
        )

        diagnostics[
            "rejection_reason"
        ] = None

        data = state.to_dict()

        data[
            "symbol"
        ] = context.symbol

        data[
            "timeframe"
        ] = timeframe

        best_range = (
            self.service.best_session_range(
                state
            )
        )

        data[
            "best_session_range"
        ] = (
            {
                "session": best_range[0],
                "high": best_range[1],
                "low": best_range[2],
            }
            if best_range is not None
            else None
        )

        events: list[
            dict[str, Any]
        ] = []

        for zone in (
            state.asia,
            state.london,
            state.new_york,
        ):
            if zone is None:
                continue

            event = zone.to_dict()

            event[
                "event_type"
            ] = "SESSION"

            event[
                "type"
            ] = zone.session_type.value

            event[
                "direction"
            ] = "NEUTRAL"

            event[
                "time"
            ] = int(
                zone.end_time
            )

            events.append(
                event
            )

        if state.previous_day is not None:
            previous_day = (
                state.previous_day.to_dict()
            )

            events.append(
                {
                    "event_type": "PREVIOUS_DAY_LEVELS",
                    "type": "PDH_PDL",
                    "direction": "NEUTRAL",
                    "time": int(
                        state.previous_day.date
                    ),
                    "high": float(
                        state.previous_day.high
                    ),
                    "low": float(
                        state.previous_day.low
                    ),
                    **previous_day,
                }
            )

        if (
            state.premium_discount
            is not None
        ):
            premium_discount = (
                state.premium_discount
                .to_dict()
            )

            events.append(
                {
                    "event_type": (
                        "PREMIUM_DISCOUNT"
                    ),
                    "type": (
                        "PREMIUM_DISCOUNT"
                    ),
                    "direction": "NEUTRAL",
                    "time": int(
                        candles[-1]["time"]
                    ),
                    **premium_discount,
                }
            )

        return self.success(
            data=data,
            events=events,
            diagnostics=diagnostics,
        )

    def _validate_config(
        self,
    ) -> None:
        if not str(
            self.config.timeframe
        ).strip():
            raise ValueError(
                "Session timeframe cannot "
                "be empty"
            )

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
