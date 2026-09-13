from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class DataQualityReport:
    valid: bool
    candle_count: int
    issues: tuple[str, ...]
    warnings: tuple[str, ...]
    first_time: str | None
    last_time: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BacktestDataQualityService:
    """
    Fail-closed validation for historical OHLCV data before backtesting.

    Hard failures:
    - insufficient history;
    - duplicate/non-increasing timestamps;
    - malformed or impossible OHLC;
    - negative volume;
    - timezone-naive timestamps;
    - gaps above configured hard threshold.

    Smaller gaps may be surfaced as warnings.
    """

    def validate(
        self,
        *,
        candles: Iterable[dict[str, Any]],
        timeframe_minutes: int,
        minimum_candles: int,
        warning_gap_multiple: int = 2,
        hard_gap_multiple: int = 12,
    ) -> DataQualityReport:
        if timeframe_minutes <= 0:
            raise ValueError("timeframe_minutes_must_be_positive")
        if minimum_candles <= 0:
            raise ValueError("minimum_candles_must_be_positive")
        if warning_gap_multiple < 2:
            raise ValueError("warning_gap_multiple_invalid")
        if hard_gap_multiple <= warning_gap_multiple:
            raise ValueError("hard_gap_multiple_must_exceed_warning_gap_multiple")

        rows = list(candles)
        issues: list[str] = []
        warnings: list[str] = []

        if len(rows) < minimum_candles:
            issues.append(
                f"insufficient_history:{len(rows)}<{minimum_candles}"
            )

        previous_dt: datetime | None = None
        first_dt: datetime | None = None
        last_dt: datetime | None = None

        expected_seconds = timeframe_minutes * 60

        for index, candle in enumerate(rows):
            if not isinstance(candle, dict):
                issues.append(f"candle_{index}:not_mapping")
                continue

            missing = [
                key for key in ("time", "open", "high", "low", "close")
                if key not in candle
            ]
            if missing:
                issues.append(
                    f"candle_{index}:missing:{','.join(missing)}"
                )
                continue

            try:
                dt = self._dt(str(candle["time"]))
            except ValueError as exc:
                issues.append(f"candle_{index}:{exc}")
                continue

            try:
                o = float(candle["open"])
                h = float(candle["high"])
                l = float(candle["low"])
                c = float(candle["close"])
                v = float(candle.get("volume", 0.0))
            except (TypeError, ValueError):
                issues.append(f"candle_{index}:non_numeric_ohlcv")
                continue

            if h < l:
                issues.append(f"candle_{index}:high_below_low")
            if h < max(o, c):
                issues.append(f"candle_{index}:high_below_open_or_close")
            if l > min(o, c):
                issues.append(f"candle_{index}:low_above_open_or_close")
            if min(o, h, l, c) <= 0:
                issues.append(f"candle_{index}:non_positive_price")
            if v < 0:
                issues.append(f"candle_{index}:negative_volume")

            if previous_dt is not None:
                delta = (dt - previous_dt).total_seconds()
                if delta <= 0:
                    issues.append(f"candle_{index}:timestamp_not_increasing")
                else:
                    multiple = delta / expected_seconds
                    if multiple >= hard_gap_multiple:
                        issues.append(
                            f"candle_{index}:hard_gap:{int(delta)}s"
                        )
                    elif multiple >= warning_gap_multiple:
                        warnings.append(
                            f"candle_{index}:data_gap:{int(delta)}s"
                        )

            if first_dt is None:
                first_dt = dt
            last_dt = dt
            previous_dt = dt

        return DataQualityReport(
            valid=not issues,
            candle_count=len(rows),
            issues=tuple(issues),
            warnings=tuple(warnings),
            first_time=first_dt.isoformat() if first_dt else None,
            last_time=last_dt.isoformat() if last_dt else None,
        )

    def require_valid(self, **kwargs: Any) -> DataQualityReport:
        report = self.validate(**kwargs)
        if not report.valid:
            raise RuntimeError(
                "backtest_market_data_rejected:" + "|".join(report.issues)
            )
        return report

    @staticmethod
    def _dt(value: str) -> datetime:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("invalid_timestamp") from exc
        if dt.tzinfo is None:
            raise ValueError("timezone_aware_timestamp_required")
        return dt.astimezone(timezone.utc)
