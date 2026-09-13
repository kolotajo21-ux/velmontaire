from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class MultiTimeframeError(ValueError):
    """Fail-closed multi-timeframe synchronization error."""


class TimeframeAlignmentMode(str, Enum):
    AS_OF = "AS_OF"
    EXACT = "EXACT"


@dataclass(frozen=True, slots=True)
class TimeframeRequirement:
    timeframe: str
    min_bars: int = 1

    def __post_init__(self) -> None:
        tf = normalize_timeframe(self.timeframe)
        object.__setattr__(self, "timeframe", tf)
        bars = int(self.min_bars)
        if bars < 1:
            raise ValueError("min_bars_must_be_positive")
        object.__setattr__(self, "min_bars", bars)


@dataclass(frozen=True, slots=True)
class TimeframeSnapshot:
    timeframe: str
    rows: tuple[dict[str, Any], ...]
    current_row: dict[str, Any]
    current_time: int | float
    source_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "timeframe": self.timeframe,
            "rows": [dict(x) for x in self.rows],
            "current_row": dict(self.current_row),
            "current_time": self.current_time,
            "source_count": self.source_count,
        }


@dataclass(frozen=True, slots=True)
class MultiTimeframeSnapshot:
    execution_timeframe: str
    current_time: int | float
    frames: dict[str, TimeframeSnapshot] = field(default_factory=dict)

    def frame(self, timeframe: str) -> TimeframeSnapshot:
        tf = normalize_timeframe(timeframe)
        result = self.frames.get(tf)
        if result is None:
            raise MultiTimeframeError(f"timeframe_snapshot_missing:{tf}")
        return result

    def current(self, timeframe: str) -> dict[str, Any]:
        return dict(self.frame(timeframe).current_row)

    def history(self, timeframe: str) -> list[dict[str, Any]]:
        return [dict(x) for x in self.frame(timeframe).rows]


_TIMEFRAME_ALIASES = {
    "1M": "M1",
    "M1": "M1",
    "5M": "M5",
    "M5": "M5",
    "15M": "M15",
    "M15": "M15",
    "30M": "M30",
    "M30": "M30",
    "1H": "H1",
    "H1": "H1",
    "4H": "H4",
    "H4": "H4",
    "1D": "D1",
    "D1": "D1",
    "1W": "W1",
    "W1": "W1",
}


def normalize_timeframe(value: str) -> str:
    raw = str(value or "").strip().upper().replace(" ", "")
    result = _TIMEFRAME_ALIASES.get(raw)
    if result is None:
        raise MultiTimeframeError(f"unsupported_timeframe:{value}")
    return result


class UniversalMultiTimeframeEngine:
    """
    Builds one synchronized market snapshot across multiple timeframes.

    Rules:
    - each requested timeframe is explicit;
    - higher/lower timeframe data are aligned to one execution timestamp;
    - future candles are never visible;
    - missing timeframe/history/time fields fail closed;
    - no timeframe is silently substituted for another.
    """

    def build_snapshot(
        self,
        *,
        rates_by_timeframe: dict[str, Any],
        execution_timeframe: str,
        requirements: list[TimeframeRequirement | str],
        current_time: int | float | datetime | None = None,
        mode: TimeframeAlignmentMode | str = TimeframeAlignmentMode.AS_OF,
    ) -> MultiTimeframeSnapshot:
        execution_tf = normalize_timeframe(execution_timeframe)
        alignment = self._normalize_mode(mode)

        reqs: list[TimeframeRequirement] = []
        for item in requirements:
            reqs.append(
                item if isinstance(item, TimeframeRequirement)
                else TimeframeRequirement(str(item))
            )

        # execution timeframe is always required.
        if execution_tf not in {x.timeframe for x in reqs}:
            reqs.insert(0, TimeframeRequirement(execution_tf))

        source = self._normalize_sources(rates_by_timeframe)

        if execution_tf not in source:
            raise MultiTimeframeError(f"timeframe_data_missing:{execution_tf}")

        exec_rows = self._rows(source[execution_tf], execution_tf)
        anchor_time = (
            self._timestamp_value(current_time)
            if current_time is not None
            else self._row_time(exec_rows[-1], execution_tf)
        )

        frames: dict[str, TimeframeSnapshot] = {}

        for req in reqs:
            if req.timeframe not in source:
                raise MultiTimeframeError(
                    f"timeframe_data_missing:{req.timeframe}"
                )

            rows = self._rows(source[req.timeframe], req.timeframe)
            visible = self._visible_rows(
                rows,
                req.timeframe,
                anchor_time,
                alignment,
            )

            if len(visible) < req.min_bars:
                raise MultiTimeframeError(
                    f"insufficient_timeframe_history:"
                    f"{req.timeframe}:{req.min_bars}:{len(visible)}"
                )

            current = visible[-1]
            current_bar_time = self._row_time(current, req.timeframe)

            if current_bar_time > anchor_time:
                raise MultiTimeframeError(
                    f"future_bar_exposed:{req.timeframe}"
                )

            frames[req.timeframe] = TimeframeSnapshot(
                timeframe=req.timeframe,
                rows=tuple(dict(x) for x in visible),
                current_row=dict(current),
                current_time=current_bar_time,
                source_count=len(rows),
            )

        return MultiTimeframeSnapshot(
            execution_timeframe=execution_tf,
            current_time=anchor_time,
            frames=frames,
        )

    def validate_condition_timeframes(
        self,
        condition_tree: Any,
        snapshot: MultiTimeframeSnapshot,
    ) -> set[str]:
        """
        Walks a generic condition tree and verifies every explicit timeframe.

        Supported containers:
          {"timeframe": "H4", ...}
          {"children": [...]}
          {"sequence": [...]}
          nested lists/tuples
        """
        required: set[str] = set()

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                tf = node.get("timeframe")
                if tf:
                    required.add(normalize_timeframe(str(tf)))
                for key in ("children", "sequence"):
                    value = node.get(key)
                    if isinstance(value, (list, tuple)):
                        for child in value:
                            walk(child)
                for key in ("left", "right", "entry_price", "reference"):
                    value = node.get(key)
                    if value is not None:
                        walk(value)
            elif isinstance(node, (list, tuple)):
                for child in node:
                    walk(child)

        walk(condition_tree)

        for tf in sorted(required):
            if tf not in snapshot.frames:
                raise MultiTimeframeError(
                    f"condition_timeframe_missing:{tf}"
                )

        return required

    @staticmethod
    def _normalize_mode(
        mode: TimeframeAlignmentMode | str,
    ) -> TimeframeAlignmentMode:
        if isinstance(mode, TimeframeAlignmentMode):
            return mode
        raw = str(mode or "").strip().upper()
        try:
            return TimeframeAlignmentMode(raw)
        except ValueError as exc:
            raise MultiTimeframeError(
                f"unsupported_alignment_mode:{mode}"
            ) from exc

    @staticmethod
    def _normalize_sources(
        rates_by_timeframe: dict[str, Any],
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in rates_by_timeframe.items():
            tf = normalize_timeframe(str(key))
            if tf in result:
                raise MultiTimeframeError(
                    f"duplicate_timeframe_source:{tf}"
                )
            result[tf] = value
        return result

    def _visible_rows(
        self,
        rows: list[dict[str, Any]],
        timeframe: str,
        anchor_time: int | float,
        mode: TimeframeAlignmentMode,
    ) -> list[dict[str, Any]]:
        if mode == TimeframeAlignmentMode.AS_OF:
            visible = [
                row for row in rows
                if self._row_time(row, timeframe) <= anchor_time
            ]
        else:
            visible = [
                row for row in rows
                if self._row_time(row, timeframe) == anchor_time
            ]

        if not visible:
            raise MultiTimeframeError(
                f"no_aligned_bar:{timeframe}:{anchor_time}"
            )
        return visible

    @staticmethod
    def _rows(frame: Any, timeframe: str) -> list[dict[str, Any]]:
        if hasattr(frame, "to_dict"):
            try:
                rows = frame.to_dict("records")
                if isinstance(rows, list) and rows:
                    return [dict(x) for x in rows]
            except Exception:
                pass

        if isinstance(frame, (list, tuple)) and frame:
            return [dict(x) for x in frame]

        raise MultiTimeframeError(
            f"timeframe_data_empty:{timeframe}"
        )

    @classmethod
    def _row_time(
        cls,
        row: dict[str, Any],
        timeframe: str,
    ) -> int | float:
        for key in ("time", "timestamp", "datetime"):
            if key in row:
                return cls._timestamp_value(row[key])
        raise MultiTimeframeError(
            f"time_field_missing:{timeframe}"
        )

    @staticmethod
    def _timestamp_value(value: Any) -> int | float:
        if isinstance(value, datetime):
            return value.timestamp()

        if isinstance(value, bool):
            raise MultiTimeframeError("invalid_timestamp:bool")

        if isinstance(value, (int, float)):
            return value

        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                raise MultiTimeframeError("invalid_timestamp:empty")
            try:
                return float(raw)
            except ValueError:
                try:
                    return datetime.fromisoformat(raw).timestamp()
                except ValueError as exc:
                    raise MultiTimeframeError(
                        f"invalid_timestamp:{value}"
                    ) from exc

        raise MultiTimeframeError(
            f"invalid_timestamp:{type(value).__name__}"
        )
