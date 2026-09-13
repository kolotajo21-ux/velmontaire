from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

from core.context import ModuleExecutionResult, StrategyContext
from core.interfaces import EntryModule
from core.strategy import ModuleRole, StrategyModuleDefinition
from strategy_runtime.smc_ict_engine import SMCError, UniversalSMCICTEngine


class M1IFVGFVGRejectionModule(EntryModule):
    """Causal M1 IFVG -> new FVG immediate-entry model."""

    provider = "m1_ifvg_fvg_rejection"
    role = ModuleRole.ENTRY
    version = "2.1.0"
    capabilities = (
        "m1_scalping_setup",
        "m1_ifvg_fvg_rejection",
        "m1_ifvg_fvg_immediate_entry",
        "m1_impulse_fvg",
        "entry_fvg_inside_ifvg",
        "ifvg_entry_sequence_max_three_bars",
        "htf_fvg_or_liquidity_context",
        "first_problem_area_stop",
        "htf_problem_area_permission",
    )
    dependencies = ()

    _TF_SECONDS = {
        "M1": 60,
        "M15": 15 * 60,
        "M30": 30 * 60,
        "H1": 60 * 60,
    }

    def __init__(
        self,
        definition: StrategyModuleDefinition | None = None,
    ) -> None:
        super().__init__(definition=definition)
        metadata = dict(
            (self.definition.parameters or {}).get("event_metadata") or {}
        )
        self.timezone_name = str(
            metadata.get("timezone") or "Europe/Kyiv"
        )
        self.session_start = self._clock(
            metadata.get("session_start"),
            fallback=time(16, 30),
        )
        self.session_end = self._clock(
            metadata.get("session_end"),
            fallback=time(18, 0),
        )
        self.htf_timeframes = tuple(
            str(item).strip().upper()
            for item in (
                metadata.get("context_timeframes")
                or ("H1", "M30", "M15")
            )
        )
        self._timezone = ZoneInfo(self.timezone_name)
        self.max_entry_fvg_delay_bars = int(
            metadata.get("max_entry_fvg_delay_bars") or 3
        )
        if self.max_entry_fvg_delay_bars < 1:
            raise ValueError("max_entry_fvg_delay_bars_must_be_positive")

    def execute(self, context: StrategyContext) -> ModuleExecutionResult:
        m1 = self._rows(context.get_rates("M1"))
        if len(m1) < 6:
            return self._wait("m1_history_missing", candles=len(m1))

        current_time = int(context.current_time)
        local = self._local(current_time)
        if not (
            self.session_start <= local.time() < self.session_end
        ):
            return self._wait(
                "outside_entry_window",
                local_time=local.strftime("%H:%M"),
            )

        session_start_ts = int(
            datetime.combine(
                local.date(),
                self.session_start,
                tzinfo=self._timezone,
            ).timestamp()
        )
        session_rows = [
            row
            for row in m1
            if session_start_ts <= int(row["time"]) <= current_time
        ]
        if not session_rows:
            return self._wait("session_m1_history_missing")

        setup = self._find_current_setup(
            context=context,
            all_m1=m1,
            session_rows=session_rows,
            session_start_ts=session_start_ts,
            current_time=current_time,
        )
        if setup is None:
            return self._wait("m1_setup_not_complete")

        context.state["scalping_signal_contract"] = dict(setup)
        context.state["direction"] = setup["direction"]
        context.trade["direction"] = setup["direction"]
        context.put("m1_scalping_setup", dict(setup))

        data = {
            "entry_ready": True,
            "direction": setup["direction"],
            "side": "LONG" if setup["direction"] == "BULLISH" else "SHORT",
            "timeframe": "M1",
            "active_zone": dict(setup["entry_fvg"]),
            "best_fvg": dict(setup["entry_fvg"]),
            "best_ifvg": dict(setup["ifvg"]),
            "signal_contract": dict(setup),
        }
        return self.success(
            passed=True,
            data=data,
            diagnostics={
                "semantic_event": "M1_IFVG_FVG_IMMEDIATE_ENTRY",
                "timeframe": "M1",
                "direction": setup["direction"],
                "entry_timing": setup["entry_timing"],
                "signal_time": setup["signal_time"],
            },
        )

    def _find_current_setup(
        self,
        *,
        context: StrategyContext,
        all_m1: list[dict[str, float]],
        session_rows: list[dict[str, float]],
        session_start_ts: int,
        current_time: int,
    ) -> dict[str, Any] | None:
        index_by_time = {
            int(row["time"]): index
            for index, row in enumerate(all_m1)
        }
        first_session_index = index_by_time[int(session_rows[0]["time"])]
        seed_start = max(0, first_session_index - 160)
        sources = self._active_sources_before(
            all_m1[seed_start:first_session_index],
            cutoff=session_start_ts,
        )

        htf_context = self._build_htf_context(context, local_date=self._local(
            current_time
        ).date())
        context_direction: str | None = None
        context_contract: dict[str, Any] | None = None
        ifvg_context: dict[str, Any] | None = None
        ifvg: dict[str, Any] | None = None

        for bar in session_rows:
            bar_time = int(bar["time"])
            full_index = index_by_time[bar_time]

            if ifvg is not None:
                bars_after_ifvg = full_index - int(ifvg["creation_index"])
                failed_retest = (
                    ifvg["direction"] == "BULLISH"
                    and bar["close"] < ifvg["low"]
                ) or (
                    ifvg["direction"] == "BEARISH"
                    and bar["close"] > ifvg["high"]
                )
                expired = bars_after_ifvg > self.max_entry_fvg_delay_bars
                if failed_retest or expired:
                    ifvg = None
                    ifvg_context = None

            if ifvg is None:
                interaction = self._context_interaction(
                    bar=bar,
                    htf_context=htf_context,
                )
                if interaction is not None:
                    context_direction = str(interaction["direction"])
                    context_contract = dict(interaction)

            retained: list[dict[str, Any]] = []
            new_ifvgs: list[dict[str, Any]] = []
            for source in sources:
                invalidated = (
                    source["direction"] == "BULLISH"
                    and bar["close"] < source["low"]
                ) or (
                    source["direction"] == "BEARISH"
                    and bar["close"] > source["high"]
                )
                if not invalidated:
                    retained.append(source)
                    continue
                inverse_direction = (
                    "BEARISH"
                    if source["direction"] == "BULLISH"
                    else "BULLISH"
                )
                new_ifvgs.append({
                    "zone_id": f"IFVG:{inverse_direction}:{bar_time}",
                    "event_type": "IFVG",
                    "zone_type": inverse_direction,
                    "direction": inverse_direction,
                    "low": source["low"],
                    "high": source["high"],
                    "end_time": bar_time,
                    "source_fvg_id": source["zone_id"],
                    "active": True,
                    "status": "FRESH",
                    "timeframe": "M1",
                    "creation_index": full_index,
                })
            sources = retained

            for candidate in new_ifvgs:
                if candidate["direction"] == context_direction:
                    ifvg = candidate
                    ifvg_context = (
                        dict(context_contract)
                        if context_contract is not None
                        else None
                    )

            new_fvg = self._new_fvg_at(
                all_m1,
                full_index,
                require_impulse=True,
            )
            if new_fvg is not None:
                sources.append(new_fvg)
                if (
                    ifvg is not None
                    and new_fvg["direction"] == ifvg["direction"]
                    # The video contract is sequential: IFVG first, then a
                    # newly-created FVG. A single candle cannot satisfy both
                    # stages of the setup.
                    and int(new_fvg["end_time"]) > int(ifvg["end_time"])
                    and self._zone_inside(new_fvg, ifvg)
                    and (
                        full_index - int(ifvg["creation_index"])
                        <= self.max_entry_fvg_delay_bars
                    )
                ):
                    # The entry is immediate after the candle that completes
                    # the new directional FVG closes. The historical runner
                    # therefore fills the MARKET order at the next M1 open.
                    if bar_time != current_time:
                        return None
                    direction = str(new_fvg["direction"])
                    closed_rows = all_m1[:full_index + 1]
                    stop_reference = self._nearest_stop_reference(
                        rows=closed_rows,
                        direction=direction,
                        reference_price=float(bar["close"]),
                        ifvg=ifvg,
                    )
                    if stop_reference is None:
                        return None
                    problem_areas = self._problem_areas(
                        context=context,
                        m1_rows=closed_rows,
                        signal_time=bar_time,
                    )
                    return self._contract(
                        direction=direction,
                        ifvg=ifvg,
                        entry_zone=new_fvg,
                        signal_time=bar_time,
                        max_entry_fvg_delay_bars=self.max_entry_fvg_delay_bars,
                        stop_reference=stop_reference,
                        context_source="HTF_FVG_OR_LIQUIDITY",
                        htf_context=ifvg_context,
                        problem_areas=problem_areas,
                    )

        return None

    def _build_htf_context(
        self,
        context: StrategyContext,
        *,
        local_date: Any,
    ) -> dict[str, list[dict[str, Any]]]:
        levels: list[dict[str, Any]] = []
        zones: list[dict[str, Any]] = []

        m15 = self._rows(context.get_rates("M15"))
        session_rows = [
            row
            for row in m15
            if self._local(int(row["time"])).date() == local_date
            and time(1, 0) <= self._local(int(row["time"])).time() < time(15, 0)
        ]
        for name, start, end in (
            ("ASIA", time(1, 0), time(10, 0)),
            ("LONDON", time(10, 0), time(15, 0)),
        ):
            selected = [
                row
                for row in session_rows
                if start <= self._local(int(row["time"])).time() < end
            ]
            if selected:
                levels.extend((
                    {
                        "kind": "HIGH",
                        "price": max(row["high"] for row in selected),
                        "available_time": max(int(row["time"]) for row in selected) + 900,
                        "source": f"{name}_HIGH",
                        "source_time": max(int(row["time"]) for row in selected),
                        "timeframe": "M15",
                    },
                    {
                        "kind": "LOW",
                        "price": min(row["low"] for row in selected),
                        "available_time": max(int(row["time"]) for row in selected) + 900,
                        "source": f"{name}_LOW",
                        "source_time": max(int(row["time"]) for row in selected),
                        "timeframe": "M15",
                    },
                ))

        for timeframe in self.htf_timeframes:
            rows = self._rows(context.get_rates(timeframe))
            seconds = self._TF_SECONDS.get(timeframe)
            if not rows or seconds is None:
                continue
            timeframe_levels = self._confirmed_fractals(rows, seconds)
            for level in timeframe_levels:
                level["timeframe"] = timeframe
            levels.extend(timeframe_levels)

            timeframe_zones = self._htf_fvg_zones(rows, seconds)
            for zone in timeframe_zones:
                zone["timeframe"] = timeframe
            zones.extend(timeframe_zones)

        return {"levels": levels, "zones": zones}

    @staticmethod
    def _context_interaction(
        *,
        bar: dict[str, float],
        htf_context: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any] | None:
        bar_close_time = int(bar["time"]) + 60
        matches: list[dict[str, Any]] = []

        for level in htf_context["levels"]:
            if int(level["available_time"]) > bar_close_time:
                continue
            price = float(level["price"])
            if (
                level["kind"] == "HIGH"
                and bar["high"] > price
                and bar["close"] < price
            ):
                matches.append({
                    "direction": "BEARISH",
                    "interaction_type": "LIQUIDITY_SWEEP",
                    "source": str(level.get("source") or "HIGH"),
                    "timeframe": str(level.get("timeframe") or ""),
                    "level_kind": "HIGH",
                    "price": price,
                    "source_time": level.get("source_time"),
                })
            elif (
                level["kind"] == "LOW"
                and bar["low"] < price
                and bar["close"] > price
            ):
                matches.append({
                    "direction": "BULLISH",
                    "interaction_type": "LIQUIDITY_SWEEP",
                    "source": str(level.get("source") or "LOW"),
                    "timeframe": str(level.get("timeframe") or ""),
                    "level_kind": "LOW",
                    "price": price,
                    "source_time": level.get("source_time"),
                })

        for zone in htf_context["zones"]:
            if int(zone["available_time"]) > bar_close_time:
                continue
            invalidation_time = zone.get("invalidation_time")
            if invalidation_time is not None and int(invalidation_time) <= bar_close_time:
                continue
            touched = bar["high"] >= zone["low"] and bar["low"] <= zone["high"]
            if not touched:
                continue
            if zone["direction"] == "BULLISH" and bar["close"] > zone["low"]:
                matches.append({
                    "direction": "BULLISH",
                    "interaction_type": "FVG_TOUCH",
                    "source": str(zone.get("zone_id") or "FVG"),
                    "timeframe": str(zone.get("timeframe") or ""),
                    "zone_low": float(zone["low"]),
                    "zone_high": float(zone["high"]),
                    "source_time": zone.get("end_time"),
                })
            elif zone["direction"] == "BEARISH" and bar["close"] < zone["high"]:
                matches.append({
                    "direction": "BEARISH",
                    "interaction_type": "FVG_TOUCH",
                    "source": str(zone.get("zone_id") or "FVG"),
                    "timeframe": str(zone.get("timeframe") or ""),
                    "zone_low": float(zone["low"]),
                    "zone_high": float(zone["high"]),
                    "source_time": zone.get("end_time"),
                })

        directions = {str(item["direction"]) for item in matches}
        if len(directions) == 1:
            return {
                "direction": next(iter(directions)),
                "interaction_time": int(bar["time"]),
                "matches": matches,
            }
        return None

    @classmethod
    def _confirmed_fractals(
        cls,
        rows: list[dict[str, float]],
        timeframe_seconds: int,
    ) -> list[dict[str, Any]]:
        levels: list[dict[str, Any]] = []
        for index in range(2, len(rows) - 2):
            candle = rows[index]
            left = rows[index - 2:index]
            right = rows[index + 1:index + 3]
            available_time = int(rows[index + 2]["time"]) + timeframe_seconds
            if all(candle["high"] > item["high"] for item in left + right):
                levels.append({
                    "kind": "HIGH",
                    "price": candle["high"],
                    "available_time": available_time,
                    "source": "CONFIRMED_FRACTAL_HIGH",
                    "source_time": int(candle["time"]),
                })
            if all(candle["low"] < item["low"] for item in left + right):
                levels.append({
                    "kind": "LOW",
                    "price": candle["low"],
                    "available_time": available_time,
                    "source": "CONFIRMED_FRACTAL_LOW",
                    "source_time": int(candle["time"]),
                })
        return levels[-80:]

    @classmethod
    def _htf_fvg_zones(
        cls,
        rows: list[dict[str, float]],
        timeframe_seconds: int,
    ) -> list[dict[str, Any]]:
        zones: list[dict[str, Any]] = []
        for index in range(2, len(rows)):
            zone = cls._new_fvg_at(rows, index)
            if zone is None:
                continue
            zone["available_time"] = int(zone["end_time"]) + timeframe_seconds
            zone["invalidation_time"] = None
            for later in rows[index + 1:]:
                invalidated = (
                    zone["direction"] == "BULLISH" and later["close"] < zone["low"]
                ) or (
                    zone["direction"] == "BEARISH" and later["close"] > zone["high"]
                )
                if invalidated:
                    zone["invalidation_time"] = int(later["time"]) + timeframe_seconds
                    break
            zones.append(zone)
        return zones[-80:]

    @classmethod
    def _active_sources_before(
        cls,
        rows: list[dict[str, float]],
        *,
        cutoff: int,
    ) -> list[dict[str, Any]]:
        zones: list[dict[str, Any]] = []
        for index in range(2, len(rows)):
            zone = cls._new_fvg_at(rows, index, require_impulse=True)
            if zone is not None and int(zone["end_time"]) < cutoff:
                zones.append(zone)

        active: list[dict[str, Any]] = []
        for zone in zones:
            invalidated = False
            for bar in rows:
                if int(bar["time"]) <= int(zone["end_time"]):
                    continue
                if (
                    zone["direction"] == "BULLISH" and bar["close"] < zone["low"]
                ) or (
                    zone["direction"] == "BEARISH" and bar["close"] > zone["high"]
                ):
                    invalidated = True
                    break
            if not invalidated:
                active.append(zone)
        return active[-40:]

    @classmethod
    def _new_fvg_at(
        cls,
        rows: list[dict[str, float]],
        index: int,
        *,
        require_impulse: bool = False,
    ) -> dict[str, Any] | None:
        if index < 2 or index >= len(rows):
            return None
        first = rows[index - 2]
        middle = rows[index - 1]
        third = rows[index]
        if third["low"] > first["high"]:
            direction = "BULLISH"
            low = first["high"]
            high = third["low"]
        elif third["high"] < first["low"]:
            direction = "BEARISH"
            low = third["high"]
            high = first["low"]
        else:
            return None
        if require_impulse and not cls._is_impulse_candle(
            first=first,
            middle=middle,
            third=third,
            direction=direction,
        ):
            return None
        end_time = int(third["time"])
        return {
            "zone_id": f"FVG:{direction}:{end_time}",
            "event_type": "FVG",
            "zone_type": direction,
            "direction": direction,
            "low": float(low),
            "high": float(high),
            "end_time": end_time,
            "active": True,
            "status": "FRESH",
            "timeframe": "M1",
            "impulse_confirmed": bool(require_impulse),
        }

    @staticmethod
    def _is_impulse_candle(
        *,
        first: dict[str, float],
        middle: dict[str, float],
        third: dict[str, float],
        direction: str,
    ) -> bool:
        """Require a directional, locally dominant middle candle body."""
        middle_body = abs(float(middle["close"]) - float(middle["open"]))
        first_body = abs(float(first["close"]) - float(first["open"]))
        third_body = abs(float(third["close"]) - float(third["open"]))
        directional = (
            direction == "BULLISH" and middle["close"] > middle["open"]
        ) or (
            direction == "BEARISH" and middle["close"] < middle["open"]
        )
        return directional and middle_body > max(first_body, third_body)

    @staticmethod
    def _zone_inside(
        inner: dict[str, Any],
        outer: dict[str, Any],
    ) -> bool:
        """True only when the complete new FVG is contained by the IFVG."""
        epsilon = 1e-12
        return (
            float(inner["low"]) + epsilon >= float(outer["low"])
            and float(inner["high"]) <= float(outer["high"]) + epsilon
        )

    @classmethod
    def _nearest_stop_reference(
        cls,
        *,
        rows: list[dict[str, float]],
        direction: str,
        reference_price: float,
        ifvg: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Choose the nearest causal invalidation zone behind the entry."""
        candidates: list[dict[str, Any]] = []

        for level in cls._active_fractal_levels(rows, cls._TF_SECONDS["M1"]):
            if direction == "BULLISH" and level["kind"] == "LOW":
                candidates.append({
                    "kind": "SWING_LOW",
                    "timeframe": "M1",
                    "low": float(level["price"]),
                    "high": float(level["price"]),
                    "source_time": level.get("source_time"),
                })
            elif direction == "BEARISH" and level["kind"] == "HIGH":
                candidates.append({
                    "kind": "SWING_HIGH",
                    "timeframe": "M1",
                    "low": float(level["price"]),
                    "high": float(level["price"]),
                    "source_time": level.get("source_time"),
                })

        for zone in cls._active_order_blocks(
            rows,
            timeframe="M1",
            timeframe_seconds=cls._TF_SECONDS["M1"],
        ):
            if str(zone["direction"]) == direction:
                candidates.append(zone)

        # The entry FVG is the trigger, not a protected structural area.
        # It must never tighten the stop by itself.
        for kind, zone in (("IFVG", ifvg),):
            candidates.append({
                "kind": kind,
                "timeframe": "M1",
                "direction": direction,
                "low": float(zone["low"]),
                "high": float(zone["high"]),
                "source_time": zone.get("end_time"),
            })

        valid: list[tuple[float, float, dict[str, Any]]] = []
        for candidate in candidates:
            low = float(candidate["low"])
            high = float(candidate["high"])
            stop = low if direction == "BULLISH" else high
            distance = (
                reference_price - stop
                if direction == "BULLISH"
                else stop - reference_price
            )
            if distance > 0:
                valid.append((distance, stop, candidate))

        if not valid:
            return None
        _, stop, selected = min(valid, key=lambda item: item[0])
        return {
            **dict(selected),
            "stop_loss": float(stop),
            "selection": "NEAREST_VALID_INVALIDATION_ZONE",
        }

    @classmethod
    def _problem_areas(
        cls,
        *,
        context: StrategyContext,
        m1_rows: list[dict[str, float]],
        signal_time: int,
    ) -> list[dict[str, Any]]:
        """Point-in-time obstacles used to validate whether fixed 1R is clear."""
        areas: list[dict[str, Any]] = []
        frames: list[tuple[str, list[dict[str, float]]]] = [("M1", m1_rows)]
        for timeframe in ("M15", "M30", "H1"):
            frames.append((timeframe, cls._rows(context.get_rates(timeframe))))

        cutoff_close = int(signal_time) + cls._TF_SECONDS["M1"]
        for timeframe, rows in frames:
            seconds = cls._TF_SECONDS[timeframe]
            if len(rows) < 3:
                continue

            for level in cls._active_fractal_levels(rows, seconds):
                if int(level["available_time"]) > cutoff_close:
                    continue
                price = float(level["price"])
                areas.append({
                    "kind": f"SWING_{level['kind']}",
                    "timeframe": timeframe,
                    "direction": (
                        "BEARISH" if level["kind"] == "HIGH" else "BULLISH"
                    ),
                    "low": price,
                    "high": price,
                    "source_time": level.get("source_time"),
                    "available_time": level.get("available_time"),
                })

            for zone in cls._active_fvg_zones(rows, timeframe, seconds):
                if int(zone["available_time"]) <= cutoff_close:
                    areas.append(zone)

            for zone in cls._active_order_blocks(
                rows,
                timeframe=timeframe,
                timeframe_seconds=seconds,
            ):
                if int(zone["available_time"]) <= cutoff_close:
                    areas.append(zone)

        # Bound signal size without changing nearest-price semantics later.
        return areas[-320:]

    @classmethod
    def _active_fractal_levels(
        cls,
        rows: list[dict[str, float]],
        timeframe_seconds: int,
    ) -> list[dict[str, Any]]:
        levels = cls._confirmed_fractals(rows, timeframe_seconds)
        active: list[dict[str, Any]] = []
        for level in levels:
            source_time = int(level.get("source_time") or 0)
            price = float(level["price"])
            later = [row for row in rows if int(row["time"]) > source_time]
            taken = (
                any(float(row["high"]) > price for row in later)
                if level["kind"] == "HIGH"
                else any(float(row["low"]) < price for row in later)
            )
            if not taken:
                active.append(level)
        return active

    @classmethod
    def _active_fvg_zones(
        cls,
        rows: list[dict[str, float]],
        timeframe: str,
        timeframe_seconds: int,
    ) -> list[dict[str, Any]]:
        zones = cls._htf_fvg_zones(rows, timeframe_seconds)
        active: list[dict[str, Any]] = []
        for zone in zones:
            if zone.get("invalidation_time") is not None:
                continue
            active.append({
                "kind": "FVG",
                "timeframe": timeframe,
                "direction": str(zone["direction"]),
                "low": float(zone["low"]),
                "high": float(zone["high"]),
                "source_time": zone.get("end_time"),
                "available_time": zone.get("available_time"),
            })
        return active

    @classmethod
    def _active_order_blocks(
        cls,
        rows: list[dict[str, float]],
        *,
        timeframe: str,
        timeframe_seconds: int,
    ) -> list[dict[str, Any]]:
        if len(rows) < 7:
            return []
        try:
            blocks = UniversalSMCICTEngine().order_blocks(rows)
        except SMCError:
            return []

        active: list[dict[str, Any]] = []
        for block in blocks:
            metadata = dict(block.metadata or {})
            displacement_index = int(
                metadata.get("displacement_index", block.index + 1)
            )
            if displacement_index >= len(rows):
                continue
            invalidated = False
            for later in rows[displacement_index + 1:]:
                close = float(later["close"])
                if (
                    block.direction.value == "BULLISH" and close < block.low
                ) or (
                    block.direction.value == "BEARISH" and close > block.high
                ):
                    invalidated = True
                    break
            if invalidated:
                continue
            active.append({
                "kind": "ORDER_BLOCK",
                "timeframe": timeframe,
                "direction": block.direction.value,
                "low": float(block.low),
                "high": float(block.high),
                "source_time": int(rows[block.index]["time"]),
                "available_time": (
                    int(rows[displacement_index]["time"]) + timeframe_seconds
                ),
            })
        return active[-80:]

    @staticmethod
    def _contract(
        *,
        direction: str,
        ifvg: dict[str, Any] | None,
        entry_zone: dict[str, Any],
        signal_time: int,
        max_entry_fvg_delay_bars: int,
        stop_reference: dict[str, Any],
        context_source: str,
        htf_context: dict[str, Any] | None,
        problem_areas: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if ifvg is None:
            raise ValueError("ifvg_contract_missing")
        return {
            "strategy_model": "M1_IFVG_FVG_IMMEDIATE_ENTRY",
            "direction": direction,
            "side": "LONG" if direction == "BULLISH" else "SHORT",
            "signal_time": int(signal_time),
            "entry_timeframe": "M1",
            "order_type": "MARKET",
            "stop_loss": float(stop_reference["stop_loss"]),
            "stop_reference": "FIRST_PROBLEM_AREA",
            "stop_zone": dict(stop_reference),
            "take_profit_r": 1.0,
            "entry_timing": "NEXT_M1_OPEN_AFTER_NEW_FVG_CLOSE",
            "confirmation_type": "NEW_DIRECTIONAL_FVG_CLOSED",
            "fvg_quality": "DIRECTIONAL_DOMINANT_MIDDLE_BODY",
            "entry_fvg_location": "FULLY_INSIDE_IFVG",
            "max_entry_fvg_delay_bars": int(max_entry_fvg_delay_bars),
            "context_source": context_source,
            "htf_context": dict(htf_context or {}),
            "problem_areas": [dict(item) for item in problem_areas],
            "problem_area_policy": {
                "fixed_rr": 1.0,
                "allow_m1_obstacle_pass": True,
                "required_htf_direction_match": True,
                "block_on_fresh_opposing_htf_zone_before_tp": True,
                "htf_timeframes": ["H1", "M30", "M15"],
            },
            "ifvg": dict(ifvg),
            "entry_fvg": dict(entry_zone),
        }

    def _wait(self, reason: str, **diagnostics: Any) -> ModuleExecutionResult:
        return self.success(
            passed=False,
            data={"entry_ready": False, "reason": reason},
            diagnostics={
                "semantic_event": "M1_IFVG_FVG_IMMEDIATE_ENTRY",
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

    def _local(self, timestamp: int) -> datetime:
        return datetime.fromtimestamp(
            int(timestamp),
            tz=timezone.utc,
        ).astimezone(self._timezone)

    @staticmethod
    def _clock(value: Any, *, fallback: time) -> time:
        raw = str(value or "").strip()
        if not raw:
            return fallback
        try:
            hour, minute = raw.split(":", 1)
            return time(int(hour), int(minute))
        except (TypeError, ValueError):
            raise ValueError(f"invalid_session_time:{raw}")
