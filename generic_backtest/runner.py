from __future__ import annotations

import faulthandler
import calendar
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd

from core.module_loader import StrategyModuleLoader
from core.strategy_registry import StrategyModuleRegistry
from strategy_compiler import StrategyCompiler
from strategy_runtime import GenericStrategyRuntimeExecutor, TradePlanResolver

from .schema_codec import strategy_schema_from_dict
from .synthetic_dxy import load_synthetic_dxy


@dataclass(slots=True)
class HistoricalFrame:
    symbol: str
    timeframe: str
    rates: pd.DataFrame
    pip_size: float = 0.0001
    tick_size: float = 0.00001
    pip_value_per_lot: float = 10.0
    broker_minimum_stop_distance: float = 0.0
    lot_step: float = 0.01
    minimum_lot: float = 0.01
    maximum_lot: float = 100.0


class ProductionGenericHistoricalRunner:
    HOTFIX_VERSION = "GENERIC_SCHEMA_EXECUTION_V4"
    PROGRESS_INTERVAL_SECONDS = 5.0
    STALL_TRACEBACK_SECONDS = 45.0
    PENDING_LIMIT_MAX_WAIT_BARS = 250
    SKIPPABLE_TRADE_PLAN_REJECTION_PREFIXES = (
        "entry_price_unresolved",
        "stop_loss_unresolved",
        "invalid_long_stop_loss",
        "invalid_short_stop_loss",
        "stop_loss_below_execution_minimum",
        "take_profit_unresolved",
        "take_profit_session_",
        "session_liquidity_",
        "invalid_long_take_profit",
        "invalid_short_take_profit",
        "invalid_minimum_net_reward_r",
        "net_reward_below_minimum_rr",
        "risk_size_unresolved",
        "first_problem_area_blocks_fixed_rr",
    )

    def __init__(self, history_source: Any, *, starting_balance: float = 5000) -> None:
        self.history_source = history_source
        self.default_balance = float(starting_balance)

    @staticmethod
    def _log(message: str) -> None:
        print(f"[GENERIC BACKTEST] {message}", flush=True)

    @classmethod
    def _is_skippable_trade_plan_rejection(cls, reason: str) -> bool:
        normalized = str(reason or "").strip()
        return bool(normalized) and normalized.startswith(
            cls.SKIPPABLE_TRADE_PLAN_REJECTION_PREFIXES
        )

    @staticmethod
    def _trade_plan_rejection_code(reason: str) -> str:
        return str(reason or "unknown_trade_plan_rejection").split(":", 1)[0]

    def run(
        self, *, schema_payload: dict[str, Any], symbol: str, timeframe: str,
        date_from=None, date_to=None, starting_balance=None,
        spread_pips=0.0, commission_per_lot=0.0, slippage_pips=0.0,
    ) -> dict[str, Any]:
        # Backtest/PAPER/LIVE asset scope is chosen by the user at runtime.
        # We do NOT weaken GenericStrategyRuntimeExecutor's symbol guard.
        # Instead we compile a transient, runtime-scoped copy of the immutable
        # strategy schema for the selected symbol.
        symbol = str(symbol or "").strip().upper()
        timeframe = str(timeframe or "").strip().upper()

        if not symbol:
            raise ValueError("symbol_required")
        if not timeframe:
            raise ValueError("timeframe_required")

        self._log(
            f"phase=RUN_ENTERED symbol={symbol} timeframe={timeframe} "
            f"date_from={date_from} date_to={date_to}"
        )

        self._log("phase=SCHEMA_DECODE started")
        schema = strategy_schema_from_dict(schema_payload)
        self._log("phase=SCHEMA_DECODE completed")

        # Preserve the stored immutable strategy version. `schema` is only the
        # decoded in-memory copy used for this single backtest job.
        original_symbols = list(getattr(schema, "symbols", []) or [])
        schema.symbols = [symbol]

        self._log("phase=MODULE_LOAD started")
        registry = StrategyModuleRegistry()
        report = StrategyModuleLoader(
            registry,
            package_name="modules",
            fail_fast=False,
        ).load()
        self._log(
            f"phase=MODULE_LOAD completed success={report.success}"
        )

        if not report.success:
            raise RuntimeError(
                "strategy_module_load_failed:" + str(report.to_dict())
            )

        self._log("phase=STRATEGY_COMPILE started")
        compilation = StrategyCompiler(registry).compile(schema)
        self._log(
            f"phase=STRATEGY_COMPILE completed success={compilation.success}"
        )
        if not compilation.success or compilation.compiled is None:
            raise RuntimeError(
                "strategy_compile_failed:" + "|".join(compilation.errors)
            )

        compiled = compilation.compiled

        # Load only timeframes that are actually referenced by executable
        # conditions / price references, plus the UI-selected execution TF.
        #
        # Do NOT preload every value from compiled.timeframes: that collection
        # may contain informational/allowed timeframes (for example W1) that the
        # current strategy branch never uses. Loading all of them can make a
        # valid backtest fail simply because an unrelated timeframe has no bar
        # inside a short requested date range.
        required_timeframes = {timeframe}
        dxy_requirements: dict[str, set[str]] = {}

        # Some semantic events carry their actual timeframe in metadata even if
        # it was not promoted to schema.timeframes. Collect those as well.
        def collect_condition_timeframes(node):
            if not isinstance(node, dict):
                return

            payload = node.get("payload")
            if isinstance(payload, dict):
                metadata = payload.get("metadata")
                if isinstance(metadata, dict):
                    tf = metadata.get("timeframe")
                    if tf:
                        required_timeframes.add(str(tf).strip().upper())

                    # Semantic conditions may reference multiple timeframes,
                    # for example an HTF POI using both H4 and H1.
                    tfs = metadata.get("timeframes")
                    if isinstance(tfs, (list, tuple, set)):
                        for item in tfs:
                            normalized_tf = str(item or "").strip().upper()
                            if normalized_tf:
                                required_timeframes.add(normalized_tf)
                    elif tfs:
                        normalized_tf = str(tfs).strip().upper()
                        if normalized_tf:
                            required_timeframes.add(normalized_tf)

                    context_tfs = metadata.get("context_timeframes")
                    if isinstance(context_tfs, (list, tuple, set)):
                        for item in context_tfs:
                            normalized_tf = str(item or "").strip().upper()
                            if normalized_tf:
                                required_timeframes.add(normalized_tf)
                    elif context_tfs:
                        normalized_tf = str(context_tfs).strip().upper()
                        if normalized_tf:
                            required_timeframes.add(normalized_tf)

                    if metadata.get("dxy_context_required") is True:
                        dxy_symbol = str(
                            metadata.get("dxy_symbol") or ""
                        ).strip().upper()
                        dxy_timeframe = str(
                            metadata.get("dxy_timeframe") or "H4"
                        ).strip().upper()
                        if not dxy_symbol:
                            raise RuntimeError("dxy_symbol_missing")
                        dxy_requirements.setdefault(
                            dxy_symbol,
                            set(),
                        ).add(dxy_timeframe)

            for child in node.get("children", []) or []:
                collect_condition_timeframes(child)

        for compiled_entry in compiled.entries:
            collect_condition_timeframes(compiled_entry.get("conditions") or {})

            entry_price = compiled_entry.get("entry_price")
            if isinstance(entry_price, dict):
                tf = entry_price.get("timeframe")
                if tf:
                    required_timeframes.add(str(tf).strip().upper())

        self._log(
            "phase=TIMEFRAME_DISCOVERY completed required="
            + ",".join(sorted(required_timeframes))
        )

        # Preload history before the requested backtest start so higher
        # timeframes have enough closed candles on the very first simulated bar.
        # Without this, an H4 module can receive only a few H4 candles even
        # though the M5 execution series already has hundreds of bars.
        timeframe_seconds = {
            "M1": 60,
            "M5": 5 * 60,
            "M15": 15 * 60,
            "M30": 30 * 60,
            "H1": 60 * 60,
            "H4": 4 * 60 * 60,
            "D1": 24 * 60 * 60,
            "W1": 7 * 24 * 60 * 60,
        }

        def parse_requested_start(value):
            if not value:
                return None
            raw = str(value).strip()
            parsed = None
            for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y-%m-%dT%H:%M:%S"):
                try:
                    parsed = datetime.strptime(raw, fmt)
                    break
                except ValueError:
                    pass
            if parsed is None:
                parsed = datetime.fromisoformat(raw)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            else:
                parsed = parsed.astimezone(timezone.utc)
            return parsed.replace(hour=0, minute=0, second=0, microsecond=0)

        requested_start = parse_requested_start(date_from)
        requested_start_ts = (
            int(requested_start.timestamp())
            if requested_start is not None
            else None
        )

        # 250 trading bars gives structure/trend/POI modules a safe production
        # warmup.  Calendar subtraction by bar duration alone is insufficient
        # around weekends (for example, a Monday M5 test used to request only
        # Sunday and therefore started with zero closed structure history).
        # Add a full calendar-week cushion; requested_start_ts below still
        # prevents any trade from being simulated before the user's date_from.
        preload_bars = 250
        preload_calendar_cushion = timedelta(days=7)

        frames_by_timeframe = {}
        for required_tf in sorted(required_timeframes):
            load_date_from = date_from

            if requested_start is not None:
                seconds = timeframe_seconds.get(required_tf)
                if seconds is not None:
                    preload_start = (
                        requested_start
                        - timedelta(seconds=seconds * preload_bars)
                        - preload_calendar_cushion
                    )
                    load_date_from = preload_start.date().isoformat()

            self._log(
                f"phase=HISTORY_LOAD started timeframe={required_tf} "
                f"date_from={load_date_from} date_to={date_to}"
            )
            loaded = self.history_source.load(
                symbol=symbol,
                timeframe=required_tf,
                date_from=load_date_from,
                date_to=date_to,
            )
            tf_rates = loaded.rates.copy()
            self._log(
                f"phase=HISTORY_LOAD returned timeframe={required_tf} "
                f"raw_bars={len(tf_rates)}"
            )

            if (
                tf_rates.empty
                or not {"time", "open", "high", "low", "close"}.issubset(
                    tf_rates.columns
                )
            ):
                raise RuntimeError(
                    f"historical_rates_invalid:{required_tf}"
                )

            tf_rates = (
                tf_rates
                .sort_values("time")
                .drop_duplicates(subset=["time"], keep="last")
                .reset_index(drop=True)
            )
            frames_by_timeframe[required_tf] = (loaded, tf_rates)
            self._log(
                f"phase=HISTORY_LOAD completed timeframe={required_tf} "
                f"bars={len(tf_rates)}"
            )

        frames_by_symbol: dict[
            str,
            dict[str, tuple[Any, pd.DataFrame]],
        ] = {symbol: frames_by_timeframe}
        context_symbol_sources: dict[str, dict[str, dict[str, Any]]] = {}

        for context_symbol, context_timeframes in sorted(
            dxy_requirements.items()
        ):
            symbol_frames: dict[str, tuple[Any, pd.DataFrame]] = {}
            for context_tf in sorted(context_timeframes):
                load_date_from = date_from
                if requested_start is not None:
                    seconds = timeframe_seconds.get(context_tf)
                    if seconds is None:
                        raise RuntimeError(
                            f"unsupported_context_timeframe:{context_tf}"
                        )
                    load_date_from = (
                        requested_start
                        - timedelta(seconds=seconds * preload_bars)
                    ).date().isoformat()

                self._log(
                    "phase=CONTEXT_HISTORY_LOAD started "
                    f"symbol={context_symbol} timeframe={context_tf} "
                    f"date_from={load_date_from} date_to={date_to}"
                )
                native_error: Exception | None = None
                loaded = None
                context_rates = pd.DataFrame()
                try:
                    loaded = self.history_source.load(
                        symbol=context_symbol,
                        timeframe=context_tf,
                        date_from=load_date_from,
                        date_to=date_to,
                    )
                except Exception as exc:
                    native_error = exc

                if native_error is None:
                    try:
                        context_rates = loaded.rates.copy()
                    except Exception as exc:
                        native_error = exc
                    else:
                        if (
                            context_rates.empty
                            or not {
                                "time", "open", "high", "low", "close"
                            }.issubset(context_rates.columns)
                        ):
                            native_error = RuntimeError(
                                "native_context_history_invalid"
                            )

                if native_error is not None:
                    # The strategy contract refers to the canonical DXY name.
                    # If the broker does not publish that instrument, construct
                    # a synchronized directional proxy from the six official
                    # basket components. Other explicit broker symbols remain
                    # fail-closed so a misspelling is never silently replaced.
                    if context_symbol != "DXY":
                        raise RuntimeError(
                            "dxy_history_load_failed:"
                            f"symbol={context_symbol}:timeframe={context_tf}:"
                            f"{type(native_error).__name__}:{native_error}"
                        ) from native_error

                    self._log(
                        "phase=SYNTHETIC_DXY_BUILD started "
                        f"timeframe={context_tf} reason="
                        f"{type(native_error).__name__}:{native_error}"
                    )
                    try:
                        synthetic = load_synthetic_dxy(
                            self.history_source,
                            timeframe=context_tf,
                            date_from=load_date_from,
                            date_to=date_to,
                        )
                    except Exception as exc:
                        raise RuntimeError(
                            "synthetic_dxy_history_load_failed:"
                            f"timeframe={context_tf}:"
                            f"{type(exc).__name__}:{exc}"
                        ) from exc

                    context_rates = synthetic.rates.copy()
                    loaded = HistoricalFrame(
                        symbol="DXY",
                        timeframe=context_tf,
                        rates=context_rates,
                        pip_size=0.01,
                        pip_value_per_lot=1.0,
                    )
                    context_symbol_sources.setdefault(
                        context_symbol,
                        {},
                    )[context_tf] = {
                        "source": "SYNTHETIC_DXY",
                        "components": synthetic.components,
                        "normalization": synthetic.normalization,
                        "ohlc_policy": synthetic.ohlc_policy,
                    }
                    self._log(
                        "phase=SYNTHETIC_DXY_BUILD completed "
                        f"timeframe={context_tf} bars={len(context_rates)} "
                        f"components={','.join(synthetic.components)}"
                    )
                else:
                    context_symbol_sources.setdefault(
                        context_symbol,
                        {},
                    )[context_tf] = {
                        "source": "NATIVE_HISTORY",
                        "symbol": context_symbol,
                    }

                context_rates = (
                    context_rates.sort_values("time")
                    .drop_duplicates(subset=["time"], keep="last")
                    .reset_index(drop=True)
                )
                symbol_frames[context_tf] = (loaded, context_rates)
                self._log(
                    "phase=CONTEXT_HISTORY_LOAD completed "
                    f"symbol={context_symbol} timeframe={context_tf} "
                    f"bars={len(context_rates)}"
                )
            frames_by_symbol[context_symbol] = symbol_frames

        frame, rates = frames_by_timeframe[timeframe]

        try:
            spread_value = max(0.0, float(spread_pips))
            slippage_value = max(0.0, float(slippage_pips))
            commission_value = max(0.0, float(commission_per_lot))
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid_execution_cost_assumption") from exc

        execution_cost_per_lot = (
            (spread_value + slippage_value)
            * float(frame.pip_value_per_lot)
            + commission_value
        )

        broker_minimum_stop_pips = 0.0
        if frame.pip_size > 0:
            broker_minimum_stop_pips = max(
                0.0,
                float(
                    getattr(
                        frame,
                        "broker_minimum_stop_distance",
                        0.0,
                    )
                    or 0.0
                )
                / float(frame.pip_size),
            )

        # A structural stop that is inside the broker's hard stop level or
        # inside modeled entry friction is not executable as designed. Keep
        # zero-cost tests possible, but fail closed when real constraints are
        # supplied.
        friction_minimum_stop_pips = spread_value + slippage_value
        execution_minimum_stop_pips = max(
            broker_minimum_stop_pips,
            friction_minimum_stop_pips,
        )

        if (
            rates.empty
            or not {"time", "open", "high", "low", "close"}.issubset(
                rates.columns
            )
        ):
            raise RuntimeError("historical_rates_invalid")

        start_balance = float(
            self.default_balance
            if starting_balance is None
            else starting_balance
        )
        balance = start_balance

        executor = GenericStrategyRuntimeExecutor(
            registry=registry,
            compiled=compiled,
        )
        resolver = TradePlanResolver(compiled)

        equity_start_time = (
            requested_start_ts
            if requested_start_ts is not None
            else int(rates.iloc[0]["time"])
        )

        equity = [
            {
                "time": equity_start_time,
                "equity": round(balance, 2),
            }
        ]
        trades = []

        runtime_evaluations = 0
        runtime_passed = 0
        runtime_entry_ready = 0
        runtime_entry_ready_suppressed = 0
        runtime_events = Counter()
        runtime_reasons = Counter()
        bars_skipped_while_position_open = 0
        bars_skipped_while_pending_order = 0
        pending_limit_cancellations = Counter()
        unresolved_signals = 0
        same_bar_sl_tp_collisions = 0
        trade_plan_rejections = Counter()
        daily_loss_blocks = 0
        weekly_loss_blocks = 0
        daily_trade_cap_blocks = 0
        trade_days: set[str] = set()

        risk_metadata = dict((compiled.risk or {}).get("metadata") or {})
        daily_loss_limit = risk_metadata.get("max_daily_loss_percent")
        weekly_loss_limit = risk_metadata.get("max_weekly_loss_percent")
        max_trades_per_day_per_symbol = risk_metadata.get(
            "max_trades_per_day_per_symbol"
        )
        max_trades_per_day_per_symbol = (
            int(max_trades_per_day_per_symbol)
            if max_trades_per_day_per_symbol is not None
            else None
        )
        daily_loss_limit = (
            float(daily_loss_limit)
            if daily_loss_limit is not None
            else None
        )
        weekly_loss_limit = (
            float(weekly_loss_limit)
            if weekly_loss_limit is not None
            else None
        )
        risk_timezone_name = str(
            risk_metadata.get("loss_limit_timezone") or "Europe/Kyiv"
        )
        try:
            risk_timezone = ZoneInfo(risk_timezone_name)
            risk_timezone_source = "IANA"
        except ZoneInfoNotFoundError:
            if risk_timezone_name != "Europe/Kyiv":
                raise RuntimeError(
                    f"loss_limit_timezone_unavailable:{risk_timezone_name}"
                )
            risk_timezone = None
            risk_timezone_source = "BUILTIN_EU_DST_FALLBACK"
        day_start_balances: dict[str, float] = {}
        week_start_balances: dict[str, float] = {}

        def period_keys(timestamp: int) -> tuple[str, str]:
            utc_value = datetime.fromtimestamp(
                int(timestamp),
                tz=timezone.utc,
            )
            if risk_timezone is not None:
                local = utc_value.astimezone(risk_timezone)
            else:
                year = utc_value.year

                def last_sunday(month: int) -> datetime:
                    final_day = calendar.monthrange(year, month)[1]
                    value = datetime(
                        year,
                        month,
                        final_day,
                        1,
                        tzinfo=timezone.utc,
                    )
                    return value - timedelta(days=(value.weekday() + 1) % 7)

                dst_start = last_sunday(3)
                dst_end = last_sunday(10)
                offset_hours = 3 if dst_start <= utc_value < dst_end else 2
                local = utc_value.astimezone(
                    timezone(timedelta(hours=offset_hours))
                )
            iso = local.isocalendar()
            return local.date().isoformat(), f"{iso.year}-W{iso.week:02d}"

        def loss_limit_block(timestamp: int) -> str | None:
            day_key, week_key = period_keys(timestamp)
            day_start = day_start_balances.setdefault(day_key, balance)
            week_start = week_start_balances.setdefault(week_key, balance)
            if daily_loss_limit is not None and day_start > 0:
                daily_drawdown = max(0.0, day_start - balance) / day_start * 100.0
                if daily_drawdown + 1e-12 >= daily_loss_limit:
                    return "DAILY"
            if weekly_loss_limit is not None and week_start > 0:
                weekly_drawdown = max(0.0, week_start - balance) / week_start * 100.0
                if weekly_drawdown + 1e-12 >= weekly_loss_limit:
                    return "WEEKLY"
            return None

        warmup = min(
            200,
            max(20, len(rates) // 10),
        )

        # A trade signal is edge-triggered, not level-triggered. Once an
        # ENTRY_READY signal opens a trade, the engine waits for both the
        # position to close and the strategy to return to WAIT before another
        # entry can be accepted. This prevents one continuous setup from
        # opening a new overlapping position on every execution candle.
        signal_armed = True
        i = warmup
        loop_end = len(rates) - 1
        loop_started = time.monotonic()
        last_progress_at = loop_started
        progress_span = max(1, loop_end - warmup)

        def emit_progress(current_index: int, *, force: bool = False) -> None:
            nonlocal last_progress_at
            now = time.monotonic()
            if not force and now - last_progress_at < self.PROGRESS_INTERVAL_SECONDS:
                return

            processed = max(
                0,
                min(current_index - warmup, progress_span),
            )
            elapsed = max(now - loop_started, 0.001)
            rate = processed / elapsed
            remaining = max(progress_span - processed, 0)
            eta_seconds = remaining / rate if rate > 0 else None
            eta_text = (
                f"{eta_seconds:.1f}s"
                if eta_seconds is not None
                else "unknown"
            )
            percent = processed / progress_span * 100.0
            self._log(
                f"progress={percent:.1f}% "
                f"evaluations={runtime_evaluations} "
                f"trades={len(trades)} "
                f"suppressed={runtime_entry_ready_suppressed} "
                f"rate={rate:.1f}_bars/s eta={eta_text}"
            )
            last_progress_at = now

        self._log(
            f"phase=SIMULATION started symbol={symbol} timeframe={timeframe} "
            f"bars={len(rates)} start_index={warmup}"
        )

        stall_traceback_enabled = False
        try:
            # If execution blocks inside a module, Python prints all thread
            # stacks every 45 seconds. The timer is always cancelled below.
            faulthandler.dump_traceback_later(
                self.STALL_TRACEBACK_SECONDS,
                repeat=True,
            )
            stall_traceback_enabled = True
        except (RuntimeError, ValueError):
            self._log("stall traceback unavailable; progress logging remains enabled")

        try:
            while i < loop_end:
                bar = rates.iloc[i]

                current_time = int(bar["time"])

                # Preloaded candles are context only. Never simulate entries before
                # the user's requested backtest start.
                if (
                    requested_start_ts is not None
                    and current_time < requested_start_ts
                ):
                    i += 1
                    emit_progress(i)
                    continue

                # MT5 timestamps identify candle OPEN. The runtime evaluates at
                # execution-bar close and may see only candles that are closed
                # by that instant. This blocks H1/H4 look-ahead.
                execution_seconds = timeframe_seconds.get(timeframe)
                if execution_seconds is None:
                    raise RuntimeError(
                        f"unsupported_execution_timeframe:{timeframe}"
                    )
                evaluation_time = current_time + execution_seconds

                rates_by_timeframe = {}
                for tf_name, (_, tf_rates) in frames_by_timeframe.items():
                    tf_seconds = timeframe_seconds.get(tf_name)
                    if tf_seconds is None:
                        raise RuntimeError(
                            f"unsupported_context_timeframe:{tf_name}"
                        )
                    latest_closed_open_time = evaluation_time - tf_seconds
                    visible_count = int(
                        tf_rates["time"].searchsorted(
                            latest_closed_open_time,
                            side="right",
                        )
                    )
                    visible = tf_rates.iloc[
                        max(0, visible_count - preload_bars):visible_count
                    ].copy()

                    if not visible.empty:
                        rates_by_timeframe[tf_name] = visible

                rates_by_symbol: dict[str, dict[str, pd.DataFrame]] = {}
                market_by_symbol: dict[str, dict[str, float]] = {}
                for context_symbol, symbol_frames in frames_by_symbol.items():
                    if context_symbol == symbol:
                        continue
                    visible_by_tf: dict[str, pd.DataFrame] = {}
                    for context_tf, (_, context_rates) in symbol_frames.items():
                        context_seconds = timeframe_seconds.get(context_tf)
                        if context_seconds is None:
                            raise RuntimeError(
                                f"unsupported_context_timeframe:{context_tf}"
                            )
                        latest_closed = evaluation_time - context_seconds
                        visible_count = int(
                            context_rates["time"].searchsorted(
                                latest_closed,
                                side="right",
                            )
                        )
                        visible = context_rates.iloc[
                            max(0, visible_count - preload_bars):visible_count
                        ].copy()
                        if not visible.empty:
                            visible_by_tf[context_tf] = visible
                    if visible_by_tf:
                        rates_by_symbol[context_symbol] = visible_by_tf
                        latest_frame = next(iter(visible_by_tf.values()))
                        latest_bar = latest_frame.iloc[-1]
                        market_by_symbol[context_symbol] = {
                            "open": float(latest_bar["open"]),
                            "high": float(latest_bar["high"]),
                            "low": float(latest_bar["low"]),
                            "close": float(latest_bar["close"]),
                            "price": float(latest_bar["close"]),
                        }

                context = executor.create_context(
                    symbol=symbol,
                    current_time=current_time,
                    rates_by_timeframe=rates_by_timeframe,
                    market={
                        "open": float(bar["open"]),
                        "high": float(bar["high"]),
                        "low": float(bar["low"]),
                        "close": float(bar["close"]),
                        "price": float(bar["close"]),
                        "bid": float(bar["close"]),
                        "ask": float(bar["close"]),
                        "pip_size": float(frame.pip_size),
                        "tick_size": float(frame.tick_size),
                    },
                    rates_by_symbol=rates_by_symbol,
                    market_by_symbol=market_by_symbol,
                )

                runtime = executor.execute(context)

                runtime_evaluations += 1
                runtime_events[str(getattr(runtime, "event", None))] += 1
                runtime_reasons[str(getattr(runtime, "reason", None))] += 1

                if not runtime.success:
                    raise RuntimeError(
                        "generic_runtime_error:" + runtime.reason
                    )

                if runtime.passed:
                    runtime_passed += 1

                entry_ready = (
                    runtime.passed
                    and runtime.event == "ENTRY_READY"
                    and runtime.entry_index is not None
                )

                if not entry_ready:
                    signal_armed = True
                    i += 1
                    emit_progress(i)
                    continue

                runtime_entry_ready += 1

                if not signal_armed:
                    runtime_entry_ready_suppressed += 1
                    i += 1
                    emit_progress(i)
                    continue

                signal_armed = False

                risk_block = loss_limit_block(current_time)
                if risk_block == "DAILY":
                    daily_loss_blocks += 1
                    i += 1
                    emit_progress(i)
                    continue
                if risk_block == "WEEKLY":
                    weekly_loss_blocks += 1
                    i += 1
                    emit_progress(i)
                    continue

                signal_day, _ = period_keys(current_time)
                signal_day_key = f"{symbol.upper()}:{signal_day}"
                if (
                    max_trades_per_day_per_symbol is not None
                    and max_trades_per_day_per_symbol > 0
                    and signal_day_key in trade_days
                ):
                    daily_trade_cap_blocks += 1
                    i += 1
                    emit_progress(i)
                    continue

                resolution = resolver.resolve(
                    context,
                    balance=balance,
                    entry_index=runtime.entry_index,
                    pip_size=frame.pip_size,
                    pip_value_per_lot=frame.pip_value_per_lot,
                    minimum_stop_pips=execution_minimum_stop_pips,
                    execution_cost_per_lot=execution_cost_per_lot,
                    lot_step=float(getattr(frame, "lot_step", 0.01) or 0.01),
                    minimum_lot=float(
                        getattr(frame, "minimum_lot", 0.01) or 0.01
                    ),
                    maximum_lot=float(
                        getattr(frame, "maximum_lot", 100.0) or 100.0
                    ),
                )

                if not resolution.success or resolution.plan is None:
                    rejection_reason = str(resolution.reason or "")
                    if self._is_skippable_trade_plan_rejection(
                        rejection_reason
                    ):
                        rejection_code = self._trade_plan_rejection_code(
                            rejection_reason
                        )
                        trade_plan_rejections[rejection_code] += 1
                        self._log(
                            "trade_plan_rejected "
                            f"bar_time={current_time} code={rejection_code}"
                        )
                        # No order or position was created. Keep the signal
                        # eligible so a later bar can resolve a newly available
                        # structural entry price instead of suppressing the
                        # remaining backtest after the first unresolved plan.
                        signal_armed = True
                        i += 1
                        emit_progress(i)
                        continue
                    raise RuntimeError(
                        "trade_plan_failed:" + resolution.reason
                    )

                # Signals are produced only after the execution candle has
                # closed. MARKET execution and pending LIMIT activation both
                # begin on the next bar; a LIMIT may never be filled
                # retroactively inside its signal/confirmation candle.
                simulation_start = i + 1
                trade = self._simulate(
                    resolution.plan,
                    rates,
                    simulation_start,
                    frame.pip_size,
                    frame.pip_value_per_lot,
                    spread_pips,
                    commission_per_lot,
                    slippage_pips,
                    signal_time=current_time,
                    pending_max_wait_bars=(
                        self.PENDING_LIMIT_MAX_WAIT_BARS
                    ),
                )

                if trade is None:
                    # The order either never filled or remained open through
                    # the end of available history. A later signal cannot be
                    # executed without violating the one-active-order policy.
                    unresolved_signals += 1
                    break

                if trade.pop("_cancelled", False):
                    resume_index = int(
                        trade.pop("_resume_index", simulation_start)
                    )
                    cancellation_diagnostics = dict(
                        trade.get("diagnostics") or {}
                    )
                    cancellation_reason = str(
                        cancellation_diagnostics.get(
                            "pending_cancel_reason"
                        )
                        or "pending_limit_cancelled"
                    )
                    pending_limit_cancellations[cancellation_reason] += 1
                    bars_skipped_while_pending_order += max(
                        0,
                        resume_index - simulation_start,
                    )
                    self._log(
                        "pending_limit_cancelled "
                        f"signal_time={current_time} "
                        f"reason={cancellation_reason} "
                        f"wait_bars={cancellation_diagnostics.get('pending_wait_bars')}"
                    )
                    signal_armed = True
                    i = max(i + 1, resume_index)
                    emit_progress(i)
                    continue

                exit_index = int(trade.pop("_exit_index"))
                entry_bar_index = int(
                    trade.pop("_entry_bar_index", simulation_start)
                )
                if trade.get("diagnostics", {}).get(
                    "same_bar_sl_tp_collision"
                ):
                    same_bar_sl_tp_collisions += 1
                bars_skipped_while_pending_order += max(
                    0,
                    entry_bar_index - simulation_start,
                )
                bars_skipped_while_position_open += max(
                    0,
                    exit_index - entry_bar_index,
                )

                exit_day_key, exit_week_key = period_keys(trade["exit_time"])
                day_start_balances.setdefault(exit_day_key, balance)
                week_start_balances.setdefault(exit_week_key, balance)
                balance += trade["pnl_money"]
                trade["balance_after"] = round(balance, 2)
                trades.append(trade)
                trade_days.add(signal_day_key)

                equity.append(
                    {
                        "time": trade["exit_time"],
                        "equity": round(balance, 2),
                    }
                )

                # Resume only after the exit candle. While the position was
                # open, no second strategy position was allowed to overlap it.
                i = max(i + 1, exit_index + 1)
                emit_progress(i)
        finally:
            if stall_traceback_enabled:
                faulthandler.cancel_dump_traceback_later()
            emit_progress(i, force=True)

        loop_runtime_seconds = time.monotonic() - loop_started
        self._log(
            f"completed evaluations={runtime_evaluations} "
            f"trades={len(trades)} runtime={loop_runtime_seconds:.2f}s"
        )

        return {
            "success": True,
            "status": "COMPLETED",
            "metrics": self._metrics(
                trades,
                start_balance,
                balance,
                equity,
            ),
            "equity_curve": equity,
            "trades": trades,
            "diagnostics": {
                "hotfix_version": self.HOTFIX_VERSION,
                "engine": "GENERIC_COMPILED_STRATEGY",
                "compilation_id": compiled.compilation_id,
                "schema_version": compiled.schema_version,
                "bars": len(rates),
                "date_from": date_from,
                "date_to": date_to,
                "runtime_symbol": symbol,
                "stored_schema_symbols": original_symbols,
                "runtime_symbol_scope": [symbol],
                "context_symbol_scope": sorted(frames_by_symbol),
                "execution_timeframe": timeframe,
                "requested_start_ts": requested_start_ts,
                "history_preload_bars": preload_bars,
                "loaded_timeframes": sorted(frames_by_timeframe),
                "timeframe_bars": {
                    tf_name: len(tf_rates)
                    for tf_name, (_, tf_rates) in frames_by_timeframe.items()
                },
                "timeframe_ranges": {
                    tf_name: {
                        "first_time": int(tf_rates["time"].iloc[0]),
                        "last_time": int(tf_rates["time"].iloc[-1]),
                    }
                    for tf_name, (_, tf_rates) in frames_by_timeframe.items()
                },
                "context_symbol_bars": {
                    context_symbol: {
                        context_tf: len(context_rates)
                        for context_tf, (_, context_rates) in symbol_frames.items()
                    }
                    for context_symbol, symbol_frames in frames_by_symbol.items()
                    if context_symbol != symbol
                },
                "context_symbol_sources": context_symbol_sources,
                "runtime_diagnostics": {
                    "evaluations": runtime_evaluations,
                    "passed": runtime_passed,
                    "entry_ready": runtime_entry_ready,
                    "entry_ready_suppressed": runtime_entry_ready_suppressed,
                    "events": dict(runtime_events.most_common(20)),
                    "reasons": dict(runtime_reasons.most_common(20)),
                },
                "simulation_diagnostics": {
                    "bars_skipped_while_position_open": bars_skipped_while_position_open,
                    "bars_skipped_while_pending_order": bars_skipped_while_pending_order,
                    "pending_limit_cancellations": dict(
                        pending_limit_cancellations.most_common(20)
                    ),
                    "unresolved_signals": unresolved_signals,
                    "same_bar_sl_tp_collisions": same_bar_sl_tp_collisions,
                    "trade_plan_rejections": dict(
                        trade_plan_rejections.most_common(20)
                    ),
                    "daily_loss_blocks": daily_loss_blocks,
                    "weekly_loss_blocks": weekly_loss_blocks,
                    "daily_trade_cap_blocks": daily_trade_cap_blocks,
                },
                "execution_policy": {
                    "max_open_positions": int(
                        (compiled.risk or {}).get("max_open_positions") or 1
                    ),
                    "max_positions_per_symbol": int(
                        (compiled.risk or {}).get("max_positions_per_symbol") or 1
                    ),
                    "max_trades_per_day_per_symbol": max_trades_per_day_per_symbol,
                    "entry_signal_mode": "RISING_EDGE",
                    "same_bar_exit_policy": "STOP_FIRST",
                    "mtf_visibility": "CLOSED_BARS_ONLY",
                    "bar_timestamp_semantics": "OPEN_TIME",
                    "evaluation_clock": "EXECUTION_BAR_CLOSE",
                    "runtime_window_bars": preload_bars,
                    "pending_limit_expiry_bars": self.PENDING_LIMIT_MAX_WAIT_BARS,
                    "pending_limit_zone_binding": "EXACT_SIGNAL_FVG",
                    "limit_first_tap_simulation": "FUTURE_BAR_ONLY",
                    "pending_limit_activation": "NEXT_EXECUTION_BAR",
                    "minimum_stop_policy": "MAX_BROKER_LEVEL_AND_ENTRY_FRICTION",
                    "m1_scalping_model": "IFVG_FVG_IMMEDIATE_ENTRY",
                    "m1_entry_window": "16:30-18:00 Europe/Kyiv",
                },
                "stop_distance_policy": {
                    "broker_minimum_stop_pips": round(
                        broker_minimum_stop_pips,
                        6,
                    ),
                    "entry_friction_pips": round(
                        friction_minimum_stop_pips,
                        6,
                    ),
                    "execution_minimum_stop_pips": round(
                        execution_minimum_stop_pips,
                        6,
                    ),
                    "zero_cost_laboratory_mode": bool(
                        spread_value == 0.0
                        and slippage_value == 0.0
                        and commission_value == 0.0
                    ),
                    "execution_cost_per_lot": round(
                        execution_cost_per_lot,
                        6,
                    ),
                },
                "risk_policy": {
                    "sizing_cost_policy": (
                        "ALL_IN_STOP_INCLUDES_EXECUTION_COSTS"
                    ),
                    "minimum_reward_basis": (
                        "NET_AFTER_EXECUTION_COSTS"
                    ),
                    "lot_rounding": "DOWN_TO_BROKER_STEP",
                    "risk_percent": (compiled.risk or {}).get("value"),
                    "daily_loss_percent": daily_loss_limit,
                    "weekly_loss_percent": weekly_loss_limit,
                    "basis": risk_metadata.get("loss_limit_basis"),
                    "timezone": risk_timezone_name,
                    "timezone_source": risk_timezone_source,
                },
                "runtime_seconds": round(loop_runtime_seconds, 3),
                "costs": {
                    "spread_pips": spread_pips,
                    "commission_per_lot": commission_per_lot,
                    "slippage_pips": slippage_pips,
                },
            },
        }

    @staticmethod
    def _simulate(
        plan,
        rates,
        start,
        pip_size,
        pip_value,
        spread,
        commission,
        slippage,
        signal_time=None,
        pending_max_wait_bars=250,
    ):
        side = str(plan.side).upper()
        long_side = side in {"LONG", "BUY"}

        entry = float(plan.entry_price)
        sl = float(plan.stop_loss)
        tp = float(plan.take_profit)

        order_type = str(plan.order_type).upper()
        entered = order_type == "MARKET"
        entry_time = None
        entry_bar_index = None
        entry_bar_open = None
        maximum_high = None
        minimum_low = None

        plan_diagnostics = dict(
            getattr(plan, "diagnostics", None) or {}
        )
        pending_contract = dict(
            plan_diagnostics.get("pending_limit_contract") or {}
        )

        def cancel_pending(
            *,
            resume_index: int,
            reason: str,
            wait_bars: int,
        ) -> dict[str, Any]:
            return {
                "_cancelled": True,
                "_resume_index": int(resume_index),
                "diagnostics": {
                    "pending_cancel_reason": str(reason),
                    "pending_wait_bars": int(wait_bars),
                    "pending_max_wait_bars": int(
                        pending_max_wait_bars
                    ),
                    "signal_time": (
                        int(signal_time)
                        if signal_time is not None
                        else None
                    ),
                    "pending_limit_contract": pending_contract,
                },
            }

        if order_type == "LIMIT" and pending_contract:
            contract_status = str(
                pending_contract.get("zone_status") or ""
            ).strip().upper()
            contract_active = bool(
                pending_contract.get("zone_active", True)
            )
            if (
                not contract_active
                or contract_status in {"INVALIDATED", "MITIGATED"}
            ):
                return cancel_pending(
                    resume_index=start,
                    reason="fvg_inactive_before_activation",
                    wait_bars=0,
                )

        for j in range(start, len(rates)):
            bar = rates.iloc[j]
            high = float(bar["high"])
            low = float(bar["low"])

            if not entered:
                pending_wait_bars = max(0, j - start)
                try:
                    pending_expiry_time = int(
                        pending_contract.get("expiry_time")
                    )
                except (TypeError, ValueError, OverflowError):
                    pending_expiry_time = 0
                if (
                    pending_expiry_time > 0
                    and int(bar["time"]) >= pending_expiry_time
                ):
                    return cancel_pending(
                        resume_index=j,
                        reason="pending_limit_session_expired",
                        wait_bars=pending_wait_bars,
                    )
                if (
                    pending_contract
                    and pending_wait_bars >= int(pending_max_wait_bars)
                ):
                    return cancel_pending(
                        resume_index=j,
                        reason="pending_limit_expired",
                        wait_bars=pending_wait_bars,
                    )

                # Only previously closed candles may invalidate a still-pending
                # zone. The current candle is checked for a fill first and can
                # never be used to cancel an order with future information.
                if pending_contract and j > start:
                    previous_close = float(rates.iloc[j - 1]["close"])
                    zone_direction = str(
                        pending_contract.get("zone_direction") or ""
                    ).strip().upper()
                    try:
                        invalidation_price = float(
                            pending_contract.get("invalidation_price")
                        )
                    except (TypeError, ValueError, OverflowError):
                        invalidation_price = 0.0

                    invalidated = (
                        zone_direction == "BULLISH"
                        and invalidation_price > 0
                        and previous_close < invalidation_price
                    ) or (
                        zone_direction == "BEARISH"
                        and invalidation_price > 0
                        and previous_close > invalidation_price
                    )
                    if invalidated:
                        return cancel_pending(
                            resume_index=j,
                            reason="fvg_invalidated_before_fill",
                            wait_bars=pending_wait_bars,
                        )

                # A BUY LIMIT fills when price trades at or below its level;
                # a SELL LIMIT fills when price trades at or above it. This
                # also handles a gap through the order level conservatively.
                limit_touched = (
                    low <= entry
                    if long_side
                    else high >= entry
                )

                if limit_touched:
                    entered = True
                    entry_time = int(bar["time"])
                    entry_bar_index = j
                    entry_bar_open = float(bar["open"])
                else:
                    continue
            elif entry_time is None:
                entry_time = int(bar["time"])
                entry_bar_index = j
                entry_bar_open = float(bar["open"])

            maximum_high = (
                high if maximum_high is None else max(maximum_high, high)
            )
            minimum_low = (
                low if minimum_low is None else min(minimum_low, low)
            )

            hit_sl = low <= sl if long_side else high >= sl
            hit_tp = high >= tp if long_side else low <= tp

            if hit_sl or hit_tp:
                outcome = "SL" if hit_sl else "TP"
                risk_distance = abs(entry - sl)

                if risk_distance <= 0:
                    raise RuntimeError(
                        "invalid_trade_risk_distance"
                    )

                gross_r = (
                    -1.0
                    if outcome == "SL"
                    else abs(tp - entry) / risk_distance
                )

                lot = float(
                    getattr(plan, "lot", 0) or 0
                )

                price_risk_money = (
                    risk_distance
                    / float(pip_size)
                    * float(pip_value)
                    * lot
                )
                gross_money = price_risk_money * gross_r

                cost_money = (
                    (
                        float(spread)
                        + float(slippage)
                    )
                    * float(pip_value)
                    * lot
                    + float(commission) * lot
                )

                pnl_money = gross_money - cost_money
                risk_money = float(plan.risk_money)
                all_in_stop_risk_money = price_risk_money + cost_money
                same_bar_collision = bool(hit_sl and hit_tp)
                bars_held = (
                    j - entry_bar_index + 1
                    if entry_bar_index is not None
                    else None
                )
                if long_side:
                    favorable_pips = (maximum_high - entry) / float(pip_size)
                    adverse_pips = (entry - minimum_low) / float(pip_size)
                else:
                    favorable_pips = (entry - minimum_low) / float(pip_size)
                    adverse_pips = (maximum_high - entry) / float(pip_size)

                plan_payload = plan.to_dict()
                trade_diagnostics = dict(
                    plan_payload.get("diagnostics") or {}
                )
                trade_diagnostics.update(
                    {
                        "signal_time": (
                            int(signal_time)
                            if signal_time is not None
                            else None
                        ),
                        "entry_bar_open": entry_bar_open,
                        "entry_gap_pips": (
                            round(
                                (float(entry_bar_open) - entry)
                                / float(pip_size),
                                6,
                            )
                            if entry_bar_open is not None
                            else None
                        ),
                        "bars_held": bars_held,
                        "pending_wait_bars": (
                            entry_bar_index - start
                            if (
                                str(plan.order_type).upper() == "LIMIT"
                                and entry_bar_index is not None
                            )
                            else 0
                        ),
                        "pending_activation_index": (
                            int(start)
                            if str(plan.order_type).upper() == "LIMIT"
                            else None
                        ),
                        "exit_bar": {
                            "open": float(bar["open"]),
                            "high": high,
                            "low": low,
                            "close": float(bar["close"]),
                        },
                        "sl_hit": bool(hit_sl),
                        "tp_hit": bool(hit_tp),
                        "same_bar_sl_tp_collision": same_bar_collision,
                        "price_risk_money": round(price_risk_money, 2),
                        "all_in_stop_risk_money": round(
                            all_in_stop_risk_money,
                            2,
                        ),
                        "all_in_stop_risk_r": (
                            round(all_in_stop_risk_money / risk_money, 6)
                            if risk_money > 0
                            else 0.0
                        ),
                        "maximum_favorable_excursion_pips": round(
                            favorable_pips,
                            6,
                        ),
                        "maximum_adverse_excursion_pips": round(
                            adverse_pips,
                            6,
                        ),
                    }
                )

                return {
                    **plan_payload,
                    "_exit_index": j,
                    "_entry_bar_index": entry_bar_index,
                    "diagnostics": trade_diagnostics,
                    "entry_time": entry_time,
                    "exit_time": int(bar["time"]),
                    "outcome": outcome,
                    "gross_r": round(gross_r, 6),
                    "cost_money": round(cost_money, 2),
                    "pnl_money": round(pnl_money, 2),
                    "r": (
                        round(
                            pnl_money / risk_money,
                            6,
                        )
                        if risk_money > 0
                        else 0.0
                    ),
                }

        return None

    @staticmethod
    def _metrics(
        trades,
        start_balance,
        end_balance,
        equity,
    ):
        rs = [
            float(trade["r"])
            for trade in trades
        ]

        wins = sum(
            1
            for r in rs
            if r > 0
        )

        gross_win = sum(
            r
            for r in rs
            if r > 0
        )

        gross_loss = abs(
            sum(
                r
                for r in rs
                if r < 0
            )
        )

        peak = float(start_balance)
        max_dd = 0.0

        for point in equity:
            value = float(point["equity"])
            peak = max(peak, value)
            max_dd = max(
                max_dd,
                peak - value,
            )

        return {
            "trades": len(trades),
            "win_rate": (
                round(
                    wins / len(trades),
                    6,
                )
                if trades
                else 0.0
            ),
            "net_r": round(
                sum(rs),
                6,
            ),
            "net_profit": round(
                float(end_balance)
                - float(start_balance),
                2,
            ),
            "profit_factor": (
                round(
                    gross_win / gross_loss,
                    6,
                )
                if gross_loss
                else (
                    999.0
                    if gross_win
                    else None
                )
            ),
            "max_drawdown": round(
                max_dd,
                2,
            ),
            "expectancy_r": (
                round(
                    sum(rs) / len(rs),
                    6,
                )
                if rs
                else 0.0
            ),
            "ending_balance": round(
                float(end_balance),
                2,
            ),
        }
