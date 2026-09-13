from __future__ import annotations

from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from core.context import ModuleExecutionResult, StrategyContext
from core.interfaces import EntryModule
from core.strategy import ModuleRole, StrategyModuleDefinition


class NYAsiaSweepM5IFVGModule(EntryModule):
    """Asia range sweep in New York -> M5 IFVG/FVG immediate entry."""

    provider = "ny_asia_sweep_m5_ifvg"
    role = ModuleRole.ENTRY
    version = "1.0.0"
    capabilities = (
        "ny_asia_sweep_m5_setup",
        "asia_liquidity_sweep",
        "m5_ifvg_fvg_immediate_entry",
    )
    dependencies = ()

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
        self.asia_start = self._parse_time(
            metadata.get("asia_start") or "03:00"
        )
        self.asia_end = self._parse_time(
            metadata.get("asia_end") or "10:00"
        )
        self.entry_start = self._parse_time(
            metadata.get("entry_start") or "09:30"
        )
        self.entry_end = self._parse_time(
            metadata.get("entry_end") or "11:00"
        )
        self.max_sweep_to_inversion_bars = int(
            metadata.get("max_sweep_to_inversion_bars") or 12
        )
        self.max_new_fvg_delay_bars = int(
            metadata.get("max_new_fvg_delay_bars") or 6
        )
        self.stop_buffer_pips = float(
            metadata.get("stop_buffer_pips") or 1.0
        )
        if (
            self.max_sweep_to_inversion_bars < 1
            or self.max_new_fvg_delay_bars < 1
        ):
            raise ValueError("ny_asia_sweep_windows_must_be_positive")

    def execute(self, context: StrategyContext) -> ModuleExecutionResult:
        rows = self._rows(context.get_rates("M5"))
        if len(rows) < 20:
            return self._wait("m5_history_missing", candles=len(rows))

        current_time = int(context.current_time)
        current_entry_local = self._local_datetime(
            current_time, self.entry_timezone
        )
        if not self._in_clock_window(
            current_entry_local.time(), self.entry_start, self.entry_end
        ):
            return self._wait("outside_new_york_entry_window")

        trading_date = self._local_datetime(
            current_time, self.asia_timezone
        ).date()
        asia_indices = [
            index
            for index, row in enumerate(rows)
            if self._local_datetime(
                int(row["time"]), self.asia_timezone
            ).date() == trading_date
            and self._in_clock_window(
                self._local_datetime(
                    int(row["time"]), self.asia_timezone
                ).time(),
                self.asia_start,
                self.asia_end,
            )
        ]
        if not asia_indices:
            return self._wait("asia_range_missing")

        asia_high = max(float(rows[index]["high"]) for index in asia_indices)
        asia_low = min(float(rows[index]["low"]) for index in asia_indices)
        index_by_time = {
            int(row["time"]): index for index, row in enumerate(rows)
        }
        current_index = index_by_time.get(current_time)
        if current_index is None:
            return self._wait("current_m5_bar_missing")

        sweep_candidates: list[dict[str, Any]] = []
        for index, row in enumerate(rows[: current_index + 1]):
            local = self._local_datetime(int(row["time"]), self.entry_timezone)
            if local.date() != current_entry_local.date() or not self._in_clock_window(
                local.time(), self.entry_start, self.entry_end
            ):
                continue
            swept_high = (
                float(row["high"]) > asia_high
                and float(row["close"]) < asia_high
            )
            swept_low = (
                float(row["low"]) < asia_low
                and float(row["close"]) > asia_low
            )
            if swept_high == swept_low:
                continue
            direction = "BEARISH" if swept_high else "BULLISH"
            sweep_candidates.append({
                "direction": direction,
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
                "asia_high_low_sweep_missing",
                asia_high=asia_high,
                asia_low=asia_low,
            )

        asia_range = {
            "date": str(trading_date),
            "timezone": self.asia_timezone_name,
            "start": self.asia_start.strftime("%H:%M"),
            "end": self.asia_end.strftime("%H:%M"),
            "high": asia_high,
            "low": asia_low,
        }
        # Newest sweep owns the live setup unless an older sweep already
        # completed a signal earlier in the same session.
        for sweep in sweep_candidates:
            setup = self._setup_for_sweep(
                rows=rows,
                sweep=sweep,
                asia_range=asia_range,
                current_index=current_index,
                current_time=current_time,
            )
            if setup is not None:
                if int(setup["signal_time"]) != current_time:
                    return self._wait("daily_setup_already_consumed")
                context.state["scalping_signal_contract"] = dict(setup)
                context.state["direction"] = setup["direction"]
                context.trade["direction"] = setup["direction"]
                context.put("ny_asia_sweep_m5_setup", dict(setup))
                return self.success(
                    passed=True,
                    data={
                        "entry_ready": True,
                        "direction": setup["direction"],
                        "side": setup["side"],
                        "timeframe": "M5",
                        "active_zone": dict(setup["entry_fvg"]),
                        "best_fvg": dict(setup["entry_fvg"]),
                        "best_ifvg": dict(setup["ifvg"]),
                        "signal_contract": dict(setup),
                    },
                    diagnostics={
                        "semantic_event": "NY_ASIA_SWEEP_M5_IFVG_FVG_ENTRY",
                        "timeframe": "M5",
                        "direction": setup["direction"],
                        "signal_time": setup["signal_time"],
                    },
                )

        return self._wait("m5_ifvg_fvg_sequence_not_complete")

    def _setup_for_sweep(
        self,
        *,
        rows: list[dict[str, float]],
        sweep: dict[str, Any],
        asia_range: dict[str, Any],
        current_index: int,
        current_time: int,
    ) -> dict[str, Any] | None:
        direction = str(sweep["direction"])
        opposing = "BEARISH" if direction == "BULLISH" else "BULLISH"
        sweep_index = int(sweep["index"])
        active_sources: list[dict[str, Any]] = []
        active_ifvg: dict[str, Any] | None = None
        last_index = min(
            current_index,
            sweep_index
            + self.max_sweep_to_inversion_bars
            + self.max_new_fvg_delay_bars,
        )

        for index in range(max(2, sweep_index), last_index + 1):
            row = rows[index]
            bar_time = int(row["time"])
            close = float(row["close"])

            retained: list[dict[str, Any]] = []
            for source in active_sources:
                inverted = (
                    opposing == "BEARISH" and close > float(source["high"])
                ) or (
                    opposing == "BULLISH" and close < float(source["low"])
                )
                if not inverted:
                    retained.append(source)
                    continue
                if index - sweep_index <= self.max_sweep_to_inversion_bars:
                    active_ifvg = {
                        "zone_id": f"IFVG:{direction}:{bar_time}",
                        "event_type": "IFVG",
                        "direction": direction,
                        "low": float(source["low"]),
                        "high": float(source["high"]),
                        "end_time": bar_time,
                        "creation_index": index,
                        "source_fvg_id": source["zone_id"],
                        "timeframe": "M5",
                    }
            active_sources = retained

            new_fvg = self._new_fvg_at(rows, index)
            if new_fvg is None:
                continue
            new_fvg["creation_index"] = index
            if str(new_fvg["direction"]) == opposing:
                active_sources.append(new_fvg)
            if (
                active_ifvg is not None
                and str(new_fvg["direction"]) == direction
                and int(new_fvg["end_time"]) > int(active_ifvg["end_time"])
                and index - int(active_ifvg["creation_index"])
                <= self.max_new_fvg_delay_bars
            ):
                return self._contract(
                    direction=direction,
                    signal_time=bar_time,
                    ifvg=active_ifvg,
                    entry_fvg=new_fvg,
                    sweep=sweep,
                    asia_range=asia_range,
                )
        return None

    def _contract(
        self,
        *,
        direction: str,
        signal_time: int,
        ifvg: dict[str, Any],
        entry_fvg: dict[str, Any],
        sweep: dict[str, Any],
        asia_range: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "strategy_model": "NY_ASIA_SWEEP_M5_IFVG_FVG",
            "direction": direction,
            "side": "LONG" if direction == "BULLISH" else "SHORT",
            "signal_time": int(signal_time),
            "entry_timeframe": "M5",
            "order_type": "MARKET",
            "entry_timing": "NEXT_M5_OPEN_AFTER_NEW_FVG_CLOSE",
            "confirmation_type": "ASIA_SWEEP_CLOSE_BACK_IFVG_NEW_FVG",
            "stop_loss": float(sweep["extreme"]),
            "stop_boundary": float(sweep["extreme"]),
            "stop_buffer_pips": float(self.stop_buffer_pips),
            "stop_reference": "ASIA_SWEEP_EXTREME",
            "take_profit_r": 2.0,
            "max_sweep_to_inversion_bars": int(
                self.max_sweep_to_inversion_bars
            ),
            "max_new_fvg_delay_bars": int(self.max_new_fvg_delay_bars),
            "one_trade_per_day_per_symbol": True,
            "asia_range": dict(asia_range),
            "liquidity_sweep": dict(sweep),
            "ifvg": dict(ifvg),
            "entry_fvg": dict(entry_fvg),
        }

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
            "end_time": end_time,
            "timeframe": "M5",
            "status": "FRESH",
        }

    @staticmethod
    def _local_datetime(timestamp: int, timezone: ZoneInfo) -> datetime:
        return datetime.fromtimestamp(int(timestamp), tz=timezone)

    @staticmethod
    def _in_clock_window(value: time, start: time, end: time) -> bool:
        return start <= value < end

    @staticmethod
    def _parse_time(value: Any) -> time:
        raw = str(value).strip()
        hour, minute = raw.split(":", 1)
        return time(hour=int(hour), minute=int(minute))

    def _wait(self, reason: str, **diagnostics: Any) -> ModuleExecutionResult:
        return self.success(
            passed=False,
            data={"entry_ready": False, "reason": reason},
            diagnostics={
                "semantic_event": "NY_ASIA_SWEEP_M5_IFVG_FVG_ENTRY",
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
