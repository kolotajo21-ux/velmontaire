from __future__ import annotations

from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from core.context import ModuleExecutionResult, StrategyContext
from core.interfaces import EntryModule
from core.strategy import ModuleRole, StrategyModuleDefinition


class ICTNYAsiaSweepM5Module(EntryModule):
    """Closed-H1 bias -> Asia sweep -> M5 MSS/displacement/FVG limit entry."""

    provider = "ict_ny_asia_sweep_m5"
    role = ModuleRole.ENTRY
    version = "1.0.0"
    capabilities = (
        "ict_ny_asia_sweep_m5_setup",
        "h1_ema_bias",
        "asia_liquidity_sweep",
        "m5_fractal_mss",
        "m5_atr_displacement_fvg",
        "m5_fvg_midpoint_limit_entry",
    )
    dependencies = ()

    H1_SECONDS = 60 * 60
    M5_SECONDS = 5 * 60

    def __init__(
        self,
        definition: StrategyModuleDefinition | None = None,
    ) -> None:
        super().__init__(definition=definition)
        metadata = dict(
            (self.definition.parameters or {}).get("event_metadata") or {}
        )
        self.asia_timezone_name = str(
            metadata.get("asia_timezone") or "Europe/Kyiv"
        )
        self.entry_timezone_name = str(
            metadata.get("entry_timezone") or "America/New_York"
        )
        self.asia_timezone = ZoneInfo(self.asia_timezone_name)
        self.entry_timezone = ZoneInfo(self.entry_timezone_name)
        self.asia_start = self._parse_time(metadata.get("asia_start") or "03:00")
        self.asia_end = self._parse_time(metadata.get("asia_end") or "10:00")
        self.entry_start = self._parse_time(metadata.get("entry_start") or "09:30")
        self.entry_end = self._parse_time(metadata.get("entry_end") or "11:00")
        self.h1_fast_ema_period = int(metadata.get("h1_fast_ema_period") or 20)
        self.h1_slow_ema_period = int(metadata.get("h1_slow_ema_period") or 50)
        self.fractal_left_bars = int(metadata.get("fractal_left_bars") or 2)
        self.fractal_right_bars = int(metadata.get("fractal_right_bars") or 2)
        self.mss_swing_lookback = int(metadata.get("mss_swing_lookback") or 50)
        self.atr_period = int(metadata.get("atr_period") or 14)
        self.displacement_atr_multiple = float(
            metadata.get("displacement_atr_multiple") or 1.0
        )
        self.displacement_body_ratio = float(
            metadata.get("displacement_body_ratio") or 0.60
        )
        self.stop_buffer_ticks = int(metadata.get("stop_buffer_ticks") or 1)
        if not 1 <= self.h1_fast_ema_period < self.h1_slow_ema_period:
            raise ValueError("ict_ny_asia_h1_ema_periods_invalid")
        if self.fractal_left_bars < 1 or self.fractal_right_bars < 1:
            raise ValueError("ict_ny_asia_fractal_bars_invalid")
        if self.atr_period < 2 or self.displacement_atr_multiple <= 0:
            raise ValueError("ict_ny_asia_displacement_atr_invalid")
        if not 0 < self.displacement_body_ratio <= 1:
            raise ValueError("ict_ny_asia_displacement_body_ratio_invalid")

    def execute(self, context: StrategyContext) -> ModuleExecutionResult:
        m5 = self._rows(context.get_rates("M5"))
        h1 = self._rows(context.get_rates("H1"))
        if len(m5) < 30:
            return self._wait("m5_history_missing", candles=len(m5))
        if len(h1) < self.h1_slow_ema_period:
            return self._wait("h1_history_missing", candles=len(h1))

        current_time = int(context.current_time)
        current_ny = self._local_datetime(current_time, self.entry_timezone)
        if not self._in_clock_window(
            current_ny.time(), self.entry_start, self.entry_end
        ):
            return self._wait("outside_new_york_entry_window")

        current_index = {
            int(row["time"]): index for index, row in enumerate(m5)
        }.get(current_time)
        if current_index is None:
            return self._wait("current_m5_bar_missing")

        trading_date = self._local_datetime(
            current_time, self.asia_timezone
        ).date()
        asia_rows = [
            row
            for row in m5[: current_index + 1]
            if self._local_datetime(int(row["time"]), self.asia_timezone).date()
            == trading_date
            and self._in_clock_window(
                self._local_datetime(int(row["time"]), self.asia_timezone).time(),
                self.asia_start,
                self.asia_end,
            )
        ]
        if not asia_rows:
            return self._wait("asia_range_missing")
        asia_high = max(float(row["high"]) for row in asia_rows)
        asia_low = min(float(row["low"]) for row in asia_rows)

        asia_range = {
            "date": str(trading_date),
            "timezone": self.asia_timezone_name,
            "start": self.asia_start.strftime("%H:%M"),
            "end": self.asia_end.strftime("%H:%M"),
            "high": asia_high,
            "low": asia_low,
        }
        sweep_candidates: list[dict[str, Any]] = []
        for index, row in enumerate(m5[: current_index + 1]):
            local_ny = self._local_datetime(int(row["time"]), self.entry_timezone)
            if local_ny.date() != current_ny.date() or not self._in_clock_window(
                local_ny.time(), self.entry_start, self.entry_end
            ):
                continue
            swept_high = float(row["high"]) > asia_high and float(row["close"]) < asia_high
            swept_low = float(row["low"]) < asia_low and float(row["close"]) > asia_low
            if swept_high == swept_low:
                continue
            direction = "BEARISH" if swept_high else "BULLISH"
            h1_bias = self._h1_bias_at(
                h1,
                evaluation_time=int(row["time"]) + self.M5_SECONDS,
            )
            if h1_bias != direction:
                continue
            sweep_candidates.append({
                "direction": direction,
                "h1_bias": h1_bias,
                "index": index,
                "time": int(row["time"]),
                "extreme": (
                    float(row["high"])
                    if direction == "BEARISH"
                    else float(row["low"])
                ),
                "bar": dict(row),
            })

        if not sweep_candidates:
            return self._wait(
                "direction_compatible_asia_sweep_missing",
                asia_high=asia_high,
                asia_low=asia_low,
            )

        expiry_time = int(
            datetime.combine(
                current_ny.date(),
                self.entry_end,
                tzinfo=self.entry_timezone,
            ).timestamp()
        )
        for sweep in sweep_candidates:
            setup = self._setup_for_sweep(
                rows=m5,
                sweep=sweep,
                asia_range=asia_range,
                current_index=current_index,
                expiry_time=expiry_time,
            )
            if setup is None:
                continue
            if int(setup["signal_time"]) != current_time:
                return self._wait("daily_setup_already_consumed")

            pending = dict(setup["pending_limit_contract"])
            context.state["pending_limit_contract"] = pending
            context.state["scalping_signal_contract"] = dict(setup)
            context.state["direction"] = setup["direction"]
            context.trade["direction"] = setup["direction"]
            context.put("ict_ny_asia_sweep_m5_setup", dict(setup))
            return self.success(
                passed=True,
                data={
                    "entry_ready": True,
                    "direction": setup["direction"],
                    "side": setup["side"],
                    "timeframe": "M5",
                    "active_zone": dict(setup["entry_fvg"]),
                    "best_fvg": dict(setup["entry_fvg"]),
                    "signal_contract": dict(setup),
                    "pending_limit_contract": pending,
                },
                diagnostics={
                    "semantic_event": "ICT_NY_ASIA_SWEEP_M5_LIMIT_ENTRY",
                    "timeframe": "M5",
                    "direction": setup["direction"],
                    "signal_time": setup["signal_time"],
                    "expiry_time": expiry_time,
                },
            )

        return self._wait("mss_displacement_fvg_sequence_not_complete")

    def _setup_for_sweep(
        self,
        *,
        rows: list[dict[str, float]],
        sweep: dict[str, Any],
        asia_range: dict[str, Any],
        current_index: int,
        expiry_time: int,
    ) -> dict[str, Any] | None:
        direction = str(sweep["direction"])
        sweep_index = int(sweep["index"])
        mss: dict[str, Any] | None = None

        for index in range(sweep_index + 1, current_index + 1):
            swing = self._latest_confirmed_swing(rows, index, direction)
            if swing is None:
                continue
            close = float(rows[index]["close"])
            previous_close = float(rows[index - 1]["close"])
            level = float(swing["price"])
            broke = (
                direction == "BULLISH"
                and previous_close <= level
                and close > level
            ) or (
                direction == "BEARISH"
                and previous_close >= level
                and close < level
            )
            if broke:
                mss = {
                    "direction": direction,
                    "time": int(rows[index]["time"]),
                    "index": index,
                    "broken_swing": dict(swing),
                    "close": close,
                }
                break
        if mss is None:
            return None

        # The first qualifying FVG owns the setup. Its middle candle must be
        # the accepted displacement and must not precede the MSS candle.
        for index in range(max(2, int(mss["index"]) + 1), current_index + 1):
            fvg = self._new_fvg_at(rows, index)
            if fvg is None or str(fvg["direction"]) != direction:
                continue
            displacement_index = index - 1
            if displacement_index < int(mss["index"]):
                continue
            displacement = self._displacement_at(
                rows,
                displacement_index,
                direction,
            )
            if displacement is None:
                continue
            return self._contract(
                direction=direction,
                signal_time=int(rows[index]["time"]),
                sweep=sweep,
                asia_range=asia_range,
                mss=mss,
                displacement=displacement,
                entry_fvg=fvg,
                expiry_time=expiry_time,
            )
        return None

    def _contract(
        self,
        *,
        direction: str,
        signal_time: int,
        sweep: dict[str, Any],
        asia_range: dict[str, Any],
        mss: dict[str, Any],
        displacement: dict[str, Any],
        entry_fvg: dict[str, Any],
        expiry_time: int,
    ) -> dict[str, Any]:
        entry_price = (
            float(entry_fvg["low"]) + float(entry_fvg["high"])
        ) / 2.0
        invalidation_price = (
            float(entry_fvg["low"])
            if direction == "BULLISH"
            else float(entry_fvg["high"])
        )
        pending = {
            "zone_id": entry_fvg["zone_id"],
            "timeframe": "M5",
            "zone_direction": direction,
            "zone_event_type": "FVG",
            "zone_status": "FRESH",
            "zone_active": True,
            "zone_low": float(entry_fvg["low"]),
            "zone_high": float(entry_fvg["high"]),
            "entry_midpoint": entry_price,
            "invalidation_price": invalidation_price,
            "signal_time": int(signal_time),
            "expiry_time": int(expiry_time),
            "expiry_policy": "NEW_YORK_11_00",
        }
        return {
            "strategy_model": "ICT_NY_ASIA_SWEEP_M5_MSS_FVG_LIMIT",
            "direction": direction,
            "side": "LONG" if direction == "BULLISH" else "SHORT",
            "signal_time": int(signal_time),
            "entry_timeframe": "M5",
            "order_type": "LIMIT",
            "entry_price": entry_price,
            "entry_timing": "FIRST_RETRACE_TO_50_PERCENT_FVG",
            "confirmation_type": "H1_BIAS_SWEEP_MSS_DISPLACEMENT_FVG",
            "stop_loss": float(sweep["extreme"]),
            "stop_boundary": float(sweep["extreme"]),
            "stop_buffer_ticks": int(self.stop_buffer_ticks),
            "stop_reference": "ASIA_SWEEP_EXTREME",
            "take_profit_r": 2.0,
            "one_trade_per_day_per_symbol": True,
            "h1_bias": str(sweep["h1_bias"]),
            "asia_range": dict(asia_range),
            "liquidity_sweep": dict(sweep),
            "mss": dict(mss),
            "displacement": dict(displacement),
            "entry_fvg": dict(entry_fvg),
            "pending_limit_contract": pending,
        }

    def _h1_bias_at(
        self,
        rows: list[dict[str, float]],
        *,
        evaluation_time: int,
    ) -> str | None:
        latest_closed_open = int(evaluation_time) - self.H1_SECONDS
        closes = [
            float(row["close"])
            for row in rows
            if int(row["time"]) <= latest_closed_open
        ]
        if len(closes) < self.h1_slow_ema_period:
            return None
        fast = self._ema(closes, self.h1_fast_ema_period)
        slow = self._ema(closes, self.h1_slow_ema_period)
        last_close = closes[-1]
        if last_close > fast and fast > slow:
            return "BULLISH"
        if last_close < fast and fast < slow:
            return "BEARISH"
        return None

    def _latest_confirmed_swing(
        self,
        rows: list[dict[str, float]],
        break_index: int,
        direction: str,
    ) -> dict[str, Any] | None:
        latest_pivot = break_index - self.fractal_right_bars - 1
        first_pivot = max(
            self.fractal_left_bars,
            latest_pivot - self.mss_swing_lookback + 1,
        )
        for pivot in range(latest_pivot, first_pivot - 1, -1):
            if direction == "BULLISH":
                price = float(rows[pivot]["high"])
                left = [
                    float(rows[i]["high"])
                    for i in range(pivot - self.fractal_left_bars, pivot)
                ]
                right = [
                    float(rows[i]["high"])
                    for i in range(pivot + 1, pivot + self.fractal_right_bars + 1)
                ]
                confirmed = all(price > value for value in left + right)
                swing_type = "SWING_HIGH"
            else:
                price = float(rows[pivot]["low"])
                left = [
                    float(rows[i]["low"])
                    for i in range(pivot - self.fractal_left_bars, pivot)
                ]
                right = [
                    float(rows[i]["low"])
                    for i in range(pivot + 1, pivot + self.fractal_right_bars + 1)
                ]
                confirmed = all(price < value for value in left + right)
                swing_type = "SWING_LOW"
            if confirmed:
                return {
                    "type": swing_type,
                    "time": int(rows[pivot]["time"]),
                    "index": pivot,
                    "price": price,
                    "left_bars": self.fractal_left_bars,
                    "right_bars": self.fractal_right_bars,
                }
        return None

    def _displacement_at(
        self,
        rows: list[dict[str, float]],
        index: int,
        direction: str,
    ) -> dict[str, Any] | None:
        if index <= self.atr_period or index >= len(rows):
            return None
        row = rows[index]
        open_price = float(row["open"])
        close = float(row["close"])
        high = float(row["high"])
        low = float(row["low"])
        directional = (
            direction == "BULLISH" and close > open_price
        ) or (
            direction == "BEARISH" and close < open_price
        )
        candle_range = high - low
        body = abs(close - open_price)
        if not directional or candle_range <= 0:
            return None
        atr = self._atr(rows, index, self.atr_period)
        if atr is None:
            return None
        body_ratio = body / candle_range
        if (
            body < atr * self.displacement_atr_multiple
            or body_ratio < self.displacement_body_ratio
        ):
            return None
        return {
            **dict(row),
            "index": index,
            "direction": direction,
            "body": body,
            "range": candle_range,
            "body_ratio": body_ratio,
            "atr": atr,
            "atr_period": self.atr_period,
            "atr_multiple_required": self.displacement_atr_multiple,
            "body_ratio_required": self.displacement_body_ratio,
        }

    @staticmethod
    def _atr(
        rows: list[dict[str, float]],
        index: int,
        period: int,
    ) -> float | None:
        if index < period:
            return None
        values: list[float] = []
        for cursor in range(index - period + 1, index + 1):
            high = float(rows[cursor]["high"])
            low = float(rows[cursor]["low"])
            previous_close = float(rows[cursor - 1]["close"])
            values.append(
                max(
                    high - low,
                    abs(high - previous_close),
                    abs(low - previous_close),
                )
            )
        return sum(values) / float(period)

    @staticmethod
    def _new_fvg_at(
        rows: list[dict[str, float]],
        index: int,
    ) -> dict[str, Any] | None:
        if index < 2 or index >= len(rows):
            return None
        first = rows[index - 2]
        third = rows[index]
        if float(third["low"]) > float(first["high"]):
            direction = "BULLISH"
            low = float(first["high"])
            high = float(third["low"])
        elif float(third["high"]) < float(first["low"]):
            direction = "BEARISH"
            low = float(third["high"])
            high = float(first["low"])
        else:
            return None
        end_time = int(third["time"])
        return {
            "zone_id": f"FVG:{direction}:{end_time}",
            "event_type": "FVG",
            "direction": direction,
            "low": low,
            "high": high,
            "midpoint": (low + high) / 2.0,
            "end_time": end_time,
            "timeframe": "M5",
            "status": "FRESH",
        }

    @staticmethod
    def _ema(values: list[float], period: int) -> float:
        result = sum(values[:period]) / float(period)
        multiplier = 2.0 / float(period + 1)
        for value in values[period:]:
            result = (float(value) - result) * multiplier + result
        return result

    @staticmethod
    def _local_datetime(timestamp: int, timezone: ZoneInfo) -> datetime:
        return datetime.fromtimestamp(int(timestamp), tz=timezone)

    @staticmethod
    def _in_clock_window(value: time, start: time, end: time) -> bool:
        return start <= value < end

    @staticmethod
    def _parse_time(value: Any) -> time:
        hour, minute = str(value).strip().split(":", 1)
        return time(hour=int(hour), minute=int(minute))

    def _wait(self, reason: str, **diagnostics: Any) -> ModuleExecutionResult:
        return self.success(
            passed=False,
            data={"entry_ready": False, "reason": reason},
            diagnostics={
                "semantic_event": "ICT_NY_ASIA_SWEEP_M5_LIMIT_ENTRY",
                "rejection_reason": reason,
                **diagnostics,
            },
        )

    @staticmethod
    def _rows(value: Any) -> list[dict[str, float]]:
        if value is None:
            return []
        if hasattr(value, "to_dict"):
            try:
                raw = value.to_dict(orient="records")
            except TypeError:
                raw = []
        else:
            try:
                raw = list(value)
            except TypeError:
                return []
        rows: list[dict[str, float]] = []
        for item in raw:
            try:
                rows.append({
                    "time": int(item["time"]),
                    "open": float(item["open"]),
                    "high": float(item["high"]),
                    "low": float(item["low"]),
                    "close": float(item["close"]),
                })
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
        rows.sort(key=lambda item: int(item["time"]))
        return rows
