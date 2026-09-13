from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from enum import Enum
from typing import Any, Iterable


class PriceReferenceError(ValueError):
    """Fail-closed price-reference resolution error."""


class PriceReferenceType(str, Enum):
    CURRENT_OPEN = "CURRENT_OPEN"
    CURRENT_HIGH = "CURRENT_HIGH"
    CURRENT_LOW = "CURRENT_LOW"
    CURRENT_CLOSE = "CURRENT_CLOSE"

    PREVIOUS_OPEN = "PREVIOUS_OPEN"
    PREVIOUS_HIGH = "PREVIOUS_HIGH"
    PREVIOUS_LOW = "PREVIOUS_LOW"
    PREVIOUS_CLOSE = "PREVIOUS_CLOSE"

    HIGHEST_N = "HIGHEST_N"
    LOWEST_N = "LOWEST_N"

    DAY_OPEN = "DAY_OPEN"
    DAY_HIGH = "DAY_HIGH"
    DAY_LOW = "DAY_LOW"
    DAY_CLOSE = "DAY_CLOSE"

    PREVIOUS_DAY_OPEN = "PREVIOUS_DAY_OPEN"
    PREVIOUS_DAY_HIGH = "PREVIOUS_DAY_HIGH"
    PREVIOUS_DAY_LOW = "PREVIOUS_DAY_LOW"
    PREVIOUS_DAY_CLOSE = "PREVIOUS_DAY_CLOSE"

    WEEK_OPEN = "WEEK_OPEN"
    WEEK_HIGH = "WEEK_HIGH"
    WEEK_LOW = "WEEK_LOW"
    WEEK_CLOSE = "WEEK_CLOSE"

    PREVIOUS_WEEK_OPEN = "PREVIOUS_WEEK_OPEN"
    PREVIOUS_WEEK_HIGH = "PREVIOUS_WEEK_HIGH"
    PREVIOUS_WEEK_LOW = "PREVIOUS_WEEK_LOW"
    PREVIOUS_WEEK_CLOSE = "PREVIOUS_WEEK_CLOSE"

    SESSION_OPEN = "SESSION_OPEN"
    SESSION_HIGH = "SESSION_HIGH"
    SESSION_LOW = "SESSION_LOW"
    SESSION_CLOSE = "SESSION_CLOSE"


@dataclass(frozen=True, slots=True)
class PriceReferenceRequest:
    reference: PriceReferenceType | str
    timeframe: str | None = None
    bars: int | None = None
    field: str | None = None
    session: str | None = None
    offset: int = 1
    parameters: dict[str, Any] = dc_field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PriceReferenceResult:
    reference: PriceReferenceType
    value: float
    timeframe: str | None
    metadata: dict[str, Any] = dc_field(default_factory=dict)


class UniversalPriceReferenceEngine:
    """
    Deterministic gateway for candle, rolling, daily, weekly and session levels.

    Input:
      rates_by_timeframe = {"M15": list[dict] or pandas DataFrame, ...}
      market = optional precomputed levels:
        day, previous_day, week, previous_week, sessions

    Missing data is never guessed.
    """

    _ALIASES = {
        "OPEN": PriceReferenceType.CURRENT_OPEN,
        "HIGH": PriceReferenceType.CURRENT_HIGH,
        "LOW": PriceReferenceType.CURRENT_LOW,
        "CLOSE": PriceReferenceType.CURRENT_CLOSE,

        "CURRENT_OPEN": PriceReferenceType.CURRENT_OPEN,
        "CURRENT_HIGH": PriceReferenceType.CURRENT_HIGH,
        "CURRENT_LOW": PriceReferenceType.CURRENT_LOW,
        "CURRENT_CLOSE": PriceReferenceType.CURRENT_CLOSE,

        "PREVIOUS_OPEN": PriceReferenceType.PREVIOUS_OPEN,
        "PREV_OPEN": PriceReferenceType.PREVIOUS_OPEN,
        "PREVIOUS_HIGH": PriceReferenceType.PREVIOUS_HIGH,
        "PREV_HIGH": PriceReferenceType.PREVIOUS_HIGH,
        "PREVIOUS_LOW": PriceReferenceType.PREVIOUS_LOW,
        "PREV_LOW": PriceReferenceType.PREVIOUS_LOW,
        "PREVIOUS_CLOSE": PriceReferenceType.PREVIOUS_CLOSE,
        "PREV_CLOSE": PriceReferenceType.PREVIOUS_CLOSE,

        "HIGHEST_N": PriceReferenceType.HIGHEST_N,
        "HIGHEST": PriceReferenceType.HIGHEST_N,
        "LOWEST_N": PriceReferenceType.LOWEST_N,
        "LOWEST": PriceReferenceType.LOWEST_N,

        "DAY_OPEN": PriceReferenceType.DAY_OPEN,
        "DAY_HIGH": PriceReferenceType.DAY_HIGH,
        "DAY_LOW": PriceReferenceType.DAY_LOW,
        "DAY_CLOSE": PriceReferenceType.DAY_CLOSE,

        "PREVIOUS_DAY_OPEN": PriceReferenceType.PREVIOUS_DAY_OPEN,
        "PREVIOUS_DAY_HIGH": PriceReferenceType.PREVIOUS_DAY_HIGH,
        "PDH": PriceReferenceType.PREVIOUS_DAY_HIGH,
        "PREVIOUS_DAY_LOW": PriceReferenceType.PREVIOUS_DAY_LOW,
        "PDL": PriceReferenceType.PREVIOUS_DAY_LOW,
        "PREVIOUS_DAY_CLOSE": PriceReferenceType.PREVIOUS_DAY_CLOSE,

        "WEEK_OPEN": PriceReferenceType.WEEK_OPEN,
        "WEEK_HIGH": PriceReferenceType.WEEK_HIGH,
        "WEEK_LOW": PriceReferenceType.WEEK_LOW,
        "WEEK_CLOSE": PriceReferenceType.WEEK_CLOSE,

        "PREVIOUS_WEEK_OPEN": PriceReferenceType.PREVIOUS_WEEK_OPEN,
        "PREVIOUS_WEEK_HIGH": PriceReferenceType.PREVIOUS_WEEK_HIGH,
        "PWH": PriceReferenceType.PREVIOUS_WEEK_HIGH,
        "PREVIOUS_WEEK_LOW": PriceReferenceType.PREVIOUS_WEEK_LOW,
        "PWL": PriceReferenceType.PREVIOUS_WEEK_LOW,
        "PREVIOUS_WEEK_CLOSE": PriceReferenceType.PREVIOUS_WEEK_CLOSE,

        "SESSION_OPEN": PriceReferenceType.SESSION_OPEN,
        "SESSION_HIGH": PriceReferenceType.SESSION_HIGH,
        "SESSION_LOW": PriceReferenceType.SESSION_LOW,
        "SESSION_CLOSE": PriceReferenceType.SESSION_CLOSE,
    }

    def normalize(self, reference: PriceReferenceType | str) -> PriceReferenceType:
        if isinstance(reference, PriceReferenceType):
            return reference
        raw = str(reference or "").strip().upper().replace("-", "_").replace(" ", "_")
        result = self._ALIASES.get(raw)
        if result is None:
            raise PriceReferenceError(f"unsupported_price_reference:{reference}")
        return result

    def resolve(
        self,
        request: PriceReferenceRequest,
        *,
        rates_by_timeframe: dict[str, Any],
        market: dict[str, Any] | None = None,
    ) -> PriceReferenceResult:
        ref = self.normalize(request.reference)
        market = market or {}

        if ref.value.startswith("CURRENT_"):
            field = ref.value.split("_", 1)[1].lower()
            value = self._candle_value(
                rates_by_timeframe, request.timeframe, field, offset=0
            )
        elif ref.value.startswith("PREVIOUS_") and not ref.value.startswith(
            ("PREVIOUS_DAY_", "PREVIOUS_WEEK_")
        ):
            field = ref.value.split("_", 1)[1].lower()
            value = self._candle_value(
                rates_by_timeframe, request.timeframe, field, offset=request.offset
            )
        elif ref in {PriceReferenceType.HIGHEST_N, PriceReferenceType.LOWEST_N}:
            bars = self._positive_int(request.bars, "bars")
            field = str(
                request.field
                or ("high" if ref == PriceReferenceType.HIGHEST_N else "low")
            ).strip().lower()
            values = self._rolling_values(
                rates_by_timeframe, request.timeframe, field, bars
            )
            value = max(values) if ref == PriceReferenceType.HIGHEST_N else min(values)
        elif ref.value.startswith("PREVIOUS_DAY_"):
            field = ref.value.removeprefix("PREVIOUS_DAY_").lower()
            value = self._market_level(market, "previous_day", field)
        elif ref.value.startswith("DAY_"):
            field = ref.value.removeprefix("DAY_").lower()
            value = self._market_level(market, "day", field)
        elif ref.value.startswith("PREVIOUS_WEEK_"):
            field = ref.value.removeprefix("PREVIOUS_WEEK_").lower()
            value = self._market_level(market, "previous_week", field)
        elif ref.value.startswith("WEEK_"):
            field = ref.value.removeprefix("WEEK_").lower()
            value = self._market_level(market, "week", field)
        elif ref.value.startswith("SESSION_"):
            field = ref.value.removeprefix("SESSION_").lower()
            session = str(request.session or "").strip()
            if not session:
                raise PriceReferenceError("session_name_required")
            sessions = self._case_get(market, "sessions")
            if not isinstance(sessions, dict):
                raise PriceReferenceError("sessions_data_missing")
            session_data = self._case_get(sessions, session)
            if not isinstance(session_data, dict):
                raise PriceReferenceError(f"session_data_missing:{session}")
            value = self._case_get(session_data, field)
            if value is None:
                raise PriceReferenceError(f"session_field_missing:{session}:{field}")
        else:
            raise PriceReferenceError(f"unsupported_price_reference:{ref.value}")

        try:
            numeric = float(value)
        except (TypeError, ValueError) as exc:
            raise PriceReferenceError(f"price_reference_not_numeric:{ref.value}") from exc

        return PriceReferenceResult(
            reference=ref,
            value=numeric,
            timeframe=(str(request.timeframe).upper() if request.timeframe else None),
            metadata={
                "bars": request.bars,
                "field": request.field,
                "session": request.session,
                "offset": request.offset,
            },
        )

    def _candle_value(
        self,
        rates_by_timeframe: dict[str, Any],
        timeframe: str | None,
        field: str,
        *,
        offset: int,
    ) -> Any:
        rows = self._rows_for_timeframe(rates_by_timeframe, timeframe)
        if offset < 0:
            raise PriceReferenceError("candle_offset_must_be_non_negative")
        if len(rows) <= offset:
            raise PriceReferenceError(
                f"insufficient_history:{str(timeframe).upper()}:{offset + 1}:{len(rows)}"
            )
        row = rows[-1 - offset]
        value = self._case_get(row, field)
        if value is None:
            raise PriceReferenceError(f"candle_field_missing:{field}")
        return value

    def _rolling_values(
        self,
        rates_by_timeframe: dict[str, Any],
        timeframe: str | None,
        field: str,
        bars: int,
    ) -> list[float]:
        rows = self._rows_for_timeframe(rates_by_timeframe, timeframe)
        if len(rows) < bars:
            raise PriceReferenceError(
                f"insufficient_history:{str(timeframe).upper()}:{bars}:{len(rows)}"
            )
        out = []
        for row in rows[-bars:]:
            value = self._case_get(row, field)
            if value is None:
                raise PriceReferenceError(f"candle_field_missing:{field}")
            out.append(float(value))
        return out

    def _rows_for_timeframe(
        self,
        rates_by_timeframe: dict[str, Any],
        timeframe: str | None,
    ) -> list[dict[str, Any]]:
        tf = str(timeframe or "").strip().upper()
        if not tf:
            raise PriceReferenceError("price_reference_timeframe_required")

        frame = None
        for key, value in rates_by_timeframe.items():
            if str(key).upper() == tf:
                frame = value
                break
        if frame is None:
            raise PriceReferenceError(f"timeframe_data_missing:{tf}")

        if hasattr(frame, "to_dict"):
            try:
                rows = frame.to_dict("records")
                if isinstance(rows, list) and rows:
                    return [dict(row) for row in rows]
            except Exception:
                pass
        if isinstance(frame, (list, tuple)) and frame:
            return [dict(row) for row in frame]
        raise PriceReferenceError(f"timeframe_data_empty:{tf}")

    def _market_level(self, market: dict[str, Any], group: str, field: str) -> Any:
        data = self._case_get(market, group)
        if not isinstance(data, dict):
            raise PriceReferenceError(f"market_group_missing:{group}")
        value = self._case_get(data, field)
        if value is None:
            raise PriceReferenceError(f"market_level_missing:{group}:{field}")
        return value

    @staticmethod
    def _positive_int(value: Any, name: str) -> int:
        try:
            result = int(value)
        except (TypeError, ValueError) as exc:
            raise PriceReferenceError(f"invalid_price_reference_parameter:{name}") from exc
        if result <= 0:
            raise PriceReferenceError(f"invalid_price_reference_parameter:{name}")
        return result

    @staticmethod
    def _case_get(mapping: dict[str, Any], key: str) -> Any:
        target = str(key).casefold()
        for candidate, value in mapping.items():
            if str(candidate).casefold() == target:
                return value
        return None
