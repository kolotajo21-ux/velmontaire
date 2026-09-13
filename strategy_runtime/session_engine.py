from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class SessionEngineError(ValueError):
    """Fail-closed session/timezone evaluation error."""


@dataclass(frozen=True, slots=True)
class SessionDefinition:
    name: str
    start: str
    end: str
    timezone_name: str = "UTC"

    def __post_init__(self) -> None:
        name = str(self.name or "").strip()
        if not name:
            raise ValueError("session_name_required")
        object.__setattr__(self, "name", name)
        _parse_clock(self.start)
        _parse_clock(self.end)
        _zone(self.timezone_name)


@dataclass(frozen=True, slots=True)
class SessionWindow:
    name: str
    start: datetime
    end: datetime
    timezone_name: str

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment < self.end


@dataclass(frozen=True, slots=True)
class SessionOHLC:
    name: str
    open: float
    high: float
    low: float
    close: float
    bar_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "bar_count": self.bar_count,
        }


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(str(name or "").strip())
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise SessionEngineError(f"unsupported_timezone:{name}") from exc


def _parse_clock(value: str) -> time:
    raw = str(value or "").strip()
    try:
        parts = raw.split(":")
        if len(parts) != 2:
            raise ValueError
        hour, minute = int(parts[0]), int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
        return time(hour, minute)
    except (TypeError, ValueError) as exc:
        raise SessionEngineError(f"invalid_session_time:{value}") from exc


class UniversalSessionEngine:
    """
    Timezone-aware trading session engine.

    Supports:
    - named/default and custom sessions;
    - timezone conversion with DST handled by zoneinfo;
    - windows crossing midnight;
    - inside/outside checks;
    - session OHLC from timestamped bars;
    - kill zones as ordinary named sub-sessions;
    - fail-closed behavior for missing/invalid time data.
    """

    DEFAULTS = {
        "ASIA": SessionDefinition("ASIA", "00:00", "09:00", "UTC"),
        "LONDON": SessionDefinition("LONDON", "07:00", "16:00", "Europe/London"),
        "NEW_YORK": SessionDefinition("NEW_YORK", "08:00", "17:00", "America/New_York"),
    }

    def __init__(self, sessions: Iterable[SessionDefinition] | None = None) -> None:
        self._sessions: dict[str, SessionDefinition] = dict(self.DEFAULTS)
        if sessions:
            for session in sessions:
                self.register(session)

    def register(self, session: SessionDefinition) -> None:
        if not isinstance(session, SessionDefinition):
            raise SessionEngineError("invalid_session_definition")
        self._sessions[self._key(session.name)] = session

    def get(self, name: str) -> SessionDefinition:
        key = self._key(name)
        session = self._sessions.get(key)
        if session is None:
            raise SessionEngineError(f"unknown_session:{name}")
        return session

    def window_for(self, name: str, moment: datetime | int | float | str) -> SessionWindow:
        session = self.get(name)
        zone = _zone(session.timezone_name)
        local = self._moment(moment).astimezone(zone)
        start_clock = _parse_clock(session.start)
        end_clock = _parse_clock(session.end)

        # Candidate window beginning on the local calendar day.
        start = datetime.combine(local.date(), start_clock, tzinfo=zone)
        end = datetime.combine(local.date(), end_clock, tzinfo=zone)

        if end_clock <= start_clock:
            end += timedelta(days=1)
            if local < start:
                start -= timedelta(days=1)
                end -= timedelta(days=1)

        return SessionWindow(session.name, start, end, session.timezone_name)

    def is_inside(self, name: str, moment: datetime | int | float | str) -> bool:
        local_moment = self._moment(moment).astimezone(_zone(self.get(name).timezone_name))
        return self.window_for(name, moment).contains(local_moment)

    def is_outside(self, name: str, moment: datetime | int | float | str) -> bool:
        return not self.is_inside(name, moment)

    def active_sessions(self, moment: datetime | int | float | str) -> list[str]:
        active = []
        for session in self._sessions.values():
            if self.is_inside(session.name, moment):
                active.append(session.name)
        return active

    def session_ohlc(
        self,
        name: str,
        moment: datetime | int | float | str,
        rates: Any,
    ) -> SessionOHLC:
        window = self.window_for(name, moment)
        rows = self._rows(rates)
        selected: list[dict[str, Any]] = []

        for row in rows:
            row_time = self._row_moment(row).astimezone(_zone(window.timezone_name))
            if window.start <= row_time < window.end:
                selected.append(row)

        if not selected:
            raise SessionEngineError(f"session_bars_missing:{name}")

        try:
            open_ = float(selected[0]["open"])
            high = max(float(row["high"]) for row in selected)
            low = min(float(row["low"]) for row in selected)
            close = float(selected[-1]["close"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SessionEngineError("session_ohlc_fields_missing") from exc

        return SessionOHLC(
            name=self.get(name).name,
            open=open_,
            high=high,
            low=low,
            close=close,
            bar_count=len(selected),
        )

    @staticmethod
    def _key(value: str) -> str:
        return str(value or "").strip().upper().replace("-", "_").replace(" ", "_")

    @staticmethod
    def _moment(value: datetime | int | float | str) -> datetime:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                raise SessionEngineError("naive_datetime_not_allowed")
            return value

        if isinstance(value, bool):
            raise SessionEngineError("invalid_session_timestamp:bool")

        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)

        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                raise SessionEngineError("invalid_session_timestamp:empty")
            try:
                parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError as exc:
                raise SessionEngineError(f"invalid_session_timestamp:{value}") from exc
            if parsed.tzinfo is None:
                raise SessionEngineError("naive_datetime_not_allowed")
            return parsed

        raise SessionEngineError(f"invalid_session_timestamp:{type(value).__name__}")

    @classmethod
    def _row_moment(cls, row: dict[str, Any]) -> datetime:
        for key in ("time", "timestamp", "datetime"):
            if key in row:
                return cls._moment(row[key])
        raise SessionEngineError("session_bar_time_missing")

    @staticmethod
    def _rows(rates: Any) -> list[dict[str, Any]]:
        if hasattr(rates, "to_dict"):
            try:
                rows = rates.to_dict("records")
                if isinstance(rows, list) and rows:
                    return [dict(x) for x in rows]
            except Exception:
                pass
        if isinstance(rates, (list, tuple)) and rates:
            return [dict(x) for x in rates]
        raise SessionEngineError("session_rates_required")
