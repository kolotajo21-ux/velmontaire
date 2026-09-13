from __future__ import annotations

from typing import Any

from core.context import ModuleExecutionResult, StrategyContext
from core.interfaces import EntryModule
from core.strategy import ModuleRole, StrategyModuleDefinition


class H4FVGRejectionM15IFVGModule(EntryModule):
    """Causal H4 first-touch rejection -> M15 IFVG/FVG entry model."""

    provider = "h4_fvg_rejection_m15_ifvg"
    role = ModuleRole.ENTRY
    version = "1.2.1"
    capabilities = (
        "h4_rejection_m15_setup",
        "h4_fvg_first_touch",
        "h4_rejection_block",
        "m15_ifvg_fvg_immediate_entry",
    )
    dependencies = ()

    H4_SECONDS = 4 * 60 * 60
    M15_SECONDS = 15 * 60

    def __init__(
        self,
        definition: StrategyModuleDefinition | None = None,
    ) -> None:
        super().__init__(definition=definition)
        metadata = dict(
            (self.definition.parameters or {}).get("event_metadata") or {}
        )
        self.context_bars = int(metadata.get("context_bars") or 16)
        self.max_fvg_delay_bars = int(
            metadata.get("max_new_fvg_delay_bars") or 16
        )
        self.wick_to_body_minimum = float(
            metadata.get("wick_to_body_minimum") or 2.0
        )
        self.wick_range_minimum = float(
            metadata.get("wick_range_minimum") or 0.5
        )
        self.stop_buffer_pips = float(
            metadata.get("stop_buffer_pips") or 1.0
        )
        if self.context_bars < 1 or self.max_fvg_delay_bars < 1:
            raise ValueError("h4_m15_window_bars_must_be_positive")
        self._h4_context_cache_key: tuple[Any, ...] | None = None
        self._h4_context_cache: list[dict[str, Any]] = []

    def execute(self, context: StrategyContext) -> ModuleExecutionResult:
        h4 = self._rows(context.get_rates("H4"))
        m15 = self._rows(context.get_rates("M15"))
        if len(h4) < 9:
            return self._wait("h4_history_missing", candles=len(h4))
        if len(m15) < 6:
            return self._wait("m15_history_missing", candles=len(m15))

        current_time = int(context.current_time)
        contexts = self._h4_contexts(h4)
        eligible = [
            item
            for item in contexts
            if int(item["context_start_time"]) <= current_time
            and current_time < (
                int(item["context_expiry_time"])
                + self.max_fvg_delay_bars * self.M15_SECONDS
            )
        ]
        if not eligible:
            return self._wait("h4_first_touch_rejection_context_missing")

        # The newest eligible H4 reaction owns the M15 search. Its original
        # four-hour window gates the IFVG inversion. Once an IFVG is locked,
        # the new directional FVG gets its own post-inversion window.
        h4_context = max(
            eligible,
            key=lambda item: int(item["context_start_time"]),
        )
        setup = self._m15_setup(
            rows=m15,
            h4_context=h4_context,
            current_time=current_time,
        )
        if setup is None:
            return self._wait("m15_ifvg_fvg_sequence_not_complete")

        context.state["scalping_signal_contract"] = dict(setup)
        context.state["direction"] = setup["direction"]
        context.trade["direction"] = setup["direction"]
        context.put("h4_rejection_m15_setup", dict(setup))
        return self.success(
            passed=True,
            data={
                "entry_ready": True,
                "direction": setup["direction"],
                "side": setup["side"],
                "timeframe": "M15",
                "active_zone": dict(setup["entry_fvg"]),
                "best_fvg": dict(setup["entry_fvg"]),
                "best_ifvg": dict(setup["ifvg"]),
                "signal_contract": dict(setup),
            },
            diagnostics={
                "semantic_event": "H4_REJECTION_M15_IFVG_FVG_ENTRY",
                "timeframe": "M15",
                "direction": setup["direction"],
                "signal_time": setup["signal_time"],
            },
        )

    def _h4_contexts(self, rows: list[dict[str, float]]) -> list[dict[str, Any]]:
        cache_key = self._h4_cache_key(rows)
        if cache_key == self._h4_context_cache_key:
            return self._h4_context_cache

        # Order flow used to be recalculated from the beginning of H4 history
        # for every possible FVG touch. Build the same causal value once for
        # every H4 prefix and reuse it below.
        order_flow_by_index = self._order_flow_series(rows)
        contexts: list[dict[str, Any]] = []
        for creation_index in range(2, len(rows)):
            zone = self._new_fvg_at(rows, creation_index, timeframe="H4")
            if zone is None:
                continue
            available_time = int(rows[creation_index]["time"]) + self.H4_SECONDS
            for touch_index in range(creation_index + 1, len(rows)):
                bar = rows[touch_index]
                if int(bar["time"]) < available_time:
                    continue
                if not self._touches(bar, zone):
                    continue

                # Only the first touch is eligible. If it is not a valid
                # rejection block, this H4 FVG is consumed permanently.
                direction = str(zone["direction"])
                if (
                    order_flow_by_index[touch_index] == direction
                    and self._is_rejection_block(bar, zone, direction)
                ):
                    start = int(bar["time"]) + self.H4_SECONDS
                    contexts.append({
                        "direction": direction,
                        "context_start_time": start,
                        "context_expiry_time": (
                            start + self.context_bars * self.M15_SECONDS
                        ),
                        "h4_fvg": dict(zone),
                        "rejection_block": {
                            **dict(bar),
                            "timeframe": "H4",
                            "wick_to_body_minimum": self.wick_to_body_minimum,
                            "wick_range_minimum": self.wick_range_minimum,
                        },
                        "touch_number": 1,
                        "order_flow": direction,
                    })
                break
        self._h4_context_cache_key = cache_key
        self._h4_context_cache = contexts
        return contexts

    @staticmethod
    def _h4_cache_key(rows: list[dict[str, float]]) -> tuple[Any, ...]:
        if not rows:
            return (0,)
        first = rows[0]
        last = rows[-1]
        return (
            len(rows),
            int(first["time"]),
            int(last["time"]),
            float(last["open"]),
            float(last["high"]),
            float(last["low"]),
            float(last["close"]),
        )

    def _m15_setup(
        self,
        *,
        rows: list[dict[str, float]],
        h4_context: dict[str, Any],
        current_time: int,
    ) -> dict[str, Any] | None:
        direction = str(h4_context["direction"])
        context_start = int(h4_context["context_start_time"])
        context_expiry = int(h4_context["context_expiry_time"])
        index_by_time = {int(row["time"]): index for index, row in enumerate(rows)}
        search_expiry = (
            context_expiry + self.max_fvg_delay_bars * self.M15_SECONDS
        )
        window_times = [
            int(row["time"])
            for row in rows
            if context_start <= int(row["time"]) < search_expiry
            and int(row["time"]) <= current_time
        ]
        if not window_times:
            return None
        first_index = index_by_time[window_times[0]]

        sources = self._active_fvgs_before(
            rows,
            cutoff_index=first_index,
        )
        active_ifvg: dict[str, Any] | None = None

        for bar_time in window_times:
            index = index_by_time[bar_time]
            bar = rows[index]

            if active_ifvg is not None:
                delay = index - int(active_ifvg["creation_index"])
                if delay > self.max_fvg_delay_bars:
                    active_ifvg = None

            retained: list[dict[str, Any]] = []
            inverted: list[dict[str, Any]] = []
            for source in sources:
                inverse_direction = (
                    "BEARISH" if source["direction"] == "BULLISH" else "BULLISH"
                )
                is_inverted = (
                    source["direction"] == "BEARISH"
                    and float(bar["close"]) > float(source["high"])
                ) or (
                    source["direction"] == "BULLISH"
                    and float(bar["close"]) < float(source["low"])
                )
                if is_inverted:
                    inverted.append({
                        "zone_id": f"IFVG:{inverse_direction}:{bar_time}",
                        "event_type": "IFVG",
                        "direction": inverse_direction,
                        "low": float(source["low"]),
                        "high": float(source["high"]),
                        "end_time": bar_time,
                        "creation_index": index,
                        "source_fvg_id": source["zone_id"],
                        "timeframe": "M15",
                    })
                else:
                    retained.append(source)
            sources = retained
            matching = [item for item in inverted if item["direction"] == direction]
            # The H4 reaction may create an IFVG only during its original
            # four-hour context. A valid IFVG then locks the setup and starts
            # the independent 16-candle new-FVG clock.
            if matching and bar_time < context_expiry:
                active_ifvg = matching[-1]

            new_fvg = self._new_fvg_at(rows, index, timeframe="M15")
            if new_fvg is not None:
                new_fvg["creation_index"] = index
                sources.append(new_fvg)
                if (
                    active_ifvg is not None
                    and str(new_fvg["direction"]) == direction
                    and int(new_fvg["end_time"]) > int(active_ifvg["end_time"])
                    and index - int(active_ifvg["creation_index"])
                    <= self.max_fvg_delay_bars
                ):
                    # A past completed setup consumes this H4 context, which
                    # enforces one trade per H4 FVG + rejection block.
                    if bar_time != current_time:
                        return None
                    boundary = (
                        min(float(active_ifvg["low"]), float(new_fvg["low"]))
                        if direction == "BULLISH"
                        else max(float(active_ifvg["high"]), float(new_fvg["high"]))
                    )
                    return self._contract(
                        direction=direction,
                        signal_time=bar_time,
                        ifvg=active_ifvg,
                        entry_fvg=new_fvg,
                        stop_boundary=boundary,
                        h4_context=h4_context,
                    )
        return None

    @classmethod
    def _active_fvgs_before(
        cls,
        rows: list[dict[str, float]],
        *,
        cutoff_index: int,
    ) -> list[dict[str, Any]]:
        zones: list[dict[str, Any]] = []
        for index in range(2, cutoff_index):
            zone = cls._new_fvg_at(rows, index, timeframe="M15")
            if zone is not None:
                zone["creation_index"] = index
                zones.append(zone)
        active: list[dict[str, Any]] = []
        for zone in zones:
            invalidated = False
            for later in rows[int(zone["creation_index"]) + 1:cutoff_index]:
                if (
                    zone["direction"] == "BULLISH"
                    and float(later["close"]) < float(zone["low"])
                ) or (
                    zone["direction"] == "BEARISH"
                    and float(later["close"]) > float(zone["high"])
                ):
                    invalidated = True
                    break
            if not invalidated:
                active.append(zone)
        return active[-80:]

    @classmethod
    def _order_flow(cls, rows: list[dict[str, float]]) -> str | None:
        """Last confirmed H4 BOS, valid while its protected swing holds."""
        series = cls._order_flow_series(rows)
        return series[-1] if series else None

    @classmethod
    def _order_flow_series(
        cls,
        rows: list[dict[str, float]],
    ) -> list[str | None]:
        """Causal order-flow result for every H4 prefix in one pass."""
        fractals_by_available_index: dict[int, list[dict[str, Any]]] = {}
        for index in range(2, len(rows) - 2):
            bar = rows[index]
            neighbours = rows[index - 2:index] + rows[index + 1:index + 3]
            if all(float(bar["high"]) > float(item["high"]) for item in neighbours):
                fractals_by_available_index.setdefault(index + 2, []).append({
                    "kind": "HIGH",
                    "price": float(bar["high"]),
                    "source_index": index,
                    "available_index": index + 2,
                })
            if all(float(bar["low"]) < float(item["low"]) for item in neighbours):
                fractals_by_available_index.setdefault(index + 2, []).append({
                    "kind": "LOW",
                    "price": float(bar["low"]),
                    "source_index": index,
                    "available_index": index + 2,
                })

        active_highs: list[dict[str, Any]] = []
        active_lows: list[dict[str, Any]] = []
        broken: set[tuple[str, int]] = set()
        last_bos: dict[str, Any] | None = None
        protected_broken = False
        result: list[str | None] = []

        for bar_index, bar in enumerate(rows):
            close = float(bar["close"])

            # The legacy prefix calculation invalidates an existing BOS only
            # on bars strictly after its creation. A BOS created below on this
            # same bar starts fresh and replaces the previous state.
            if last_bos is not None and bar_index > int(last_bos["bar_index"]):
                direction = str(last_bos["direction"])
                protected_price = float(last_bos["protected_price"])
                if (
                    direction == "BULLISH" and close < protected_price
                ) or (
                    direction == "BEARISH" and close > protected_price
                ):
                    protected_broken = True

            for level in fractals_by_available_index.get(bar_index, ()):
                if level["kind"] == "HIGH":
                    active_highs.append(level)
                else:
                    active_lows.append(level)

            for level in active_highs:
                key = ("HIGH", int(level["source_index"]))
                if key in broken or close <= float(level["price"]):
                    continue
                broken.add(key)
                protected = active_lows[-1] if active_lows else None
                if protected is not None:
                    last_bos = {
                        "direction": "BULLISH",
                        "bar_index": bar_index,
                        "protected_price": float(protected["price"]),
                    }
                    protected_broken = False

            for level in active_lows:
                key = ("LOW", int(level["source_index"]))
                if key in broken or close >= float(level["price"]):
                    continue
                broken.add(key)
                protected = active_highs[-1] if active_highs else None
                if protected is not None:
                    last_bos = {
                        "direction": "BEARISH",
                        "bar_index": bar_index,
                        "protected_price": float(protected["price"]),
                    }
                    protected_broken = False

            result.append(
                None
                if last_bos is None or protected_broken
                else str(last_bos["direction"])
            )
        return result

    def _is_rejection_block(
        self,
        bar: dict[str, float],
        zone: dict[str, Any],
        direction: str,
    ) -> bool:
        open_ = float(bar["open"])
        close = float(bar["close"])
        high = float(bar["high"])
        low = float(bar["low"])
        body = max(abs(close - open_), 1e-12)
        candle_range = max(high - low, 1e-12)
        if direction == "BULLISH":
            wick = min(open_, close) - low
            body_outside = open_ > float(zone["high"]) and close > float(zone["high"])
        else:
            wick = high - max(open_, close)
            body_outside = open_ < float(zone["low"]) and close < float(zone["low"])
        return (
            body_outside
            and wick >= self.wick_to_body_minimum * body
            and wick / candle_range >= self.wick_range_minimum
        )

    @staticmethod
    def _touches(bar: dict[str, float], zone: dict[str, Any]) -> bool:
        return (
            float(bar["high"]) >= float(zone["low"])
            and float(bar["low"]) <= float(zone["high"])
        )

    @staticmethod
    def _new_fvg_at(
        rows: list[dict[str, float]],
        index: int,
        *,
        timeframe: str,
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
            "timeframe": timeframe,
            "status": "FRESH",
        }

    def _contract(
        self,
        *,
        direction: str,
        signal_time: int,
        ifvg: dict[str, Any],
        entry_fvg: dict[str, Any],
        stop_boundary: float,
        h4_context: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "strategy_model": "H4_FVG_REJECTION_M15_IFVG_FVG",
            "direction": direction,
            "side": "LONG" if direction == "BULLISH" else "SHORT",
            "signal_time": int(signal_time),
            "entry_timeframe": "M15",
            "order_type": "MARKET",
            "entry_timing": "NEXT_M15_OPEN_AFTER_NEW_FVG_CLOSE",
            "confirmation_type": "NEW_DIRECTIONAL_FVG_CLOSED",
            "stop_loss": float(stop_boundary),
            "stop_boundary": float(stop_boundary),
            "stop_buffer_pips": float(self.stop_buffer_pips),
            "stop_reference": "FARTHEST_IFVG_OR_ENTRY_FVG_BOUNDARY",
            "take_profit_r": 2.0,
            "max_new_fvg_delay_bars": int(self.max_fvg_delay_bars),
            "context_bars": int(self.context_bars),
            "one_trade_per_h4_context": True,
            "ifvg": dict(ifvg),
            "entry_fvg": dict(entry_fvg),
            "h4_context": dict(h4_context),
        }

    def _wait(self, reason: str, **diagnostics: Any) -> ModuleExecutionResult:
        return self.success(
            passed=False,
            data={"entry_ready": False, "reason": reason},
            diagnostics={
                "semantic_event": "H4_REJECTION_M15_IFVG_FVG_ENTRY",
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
