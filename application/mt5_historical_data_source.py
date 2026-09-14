from __future__ import annotations

from datetime import datetime, timedelta, timezone

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None
    MT5_AVAILABLE = False

import pandas as pd

from generic_backtest.runner import HistoricalFrame


class MT5HistoricalDataSource:
    # Dashboard/catalog names are stable product identifiers. Brokers may use
    # different MT5 symbols for the same market. Try the requested symbol
    # first, then known equivalents so brokers that already expose US100 or
    # GER40 keep their existing behaviour.
    SYMBOL_ALIASES = {
        "US100": ("US100", "USTEC", "NAS100"),
        "NAS100": ("NAS100", "USTEC", "US100"),
        "USTEC": ("USTEC", "US100", "NAS100"),
        "GER40": ("GER40", "DE40", "DAX40"),
        "DAX40": ("DAX40", "DE40", "GER40"),
        "DE40": ("DE40", "GER40", "DAX40"),
    }

    TIMEFRAMES = (
        {
            "M1": mt5.TIMEFRAME_M1,
            "M5": mt5.TIMEFRAME_M5,
            "M15": mt5.TIMEFRAME_M15,
            "M30": mt5.TIMEFRAME_M30,
            "H1": mt5.TIMEFRAME_H1,
            "H4": mt5.TIMEFRAME_H4,
            "D1": mt5.TIMEFRAME_D1,
            "W1": mt5.TIMEFRAME_W1,
        }
        if MT5_AVAILABLE
        else {}
    )

    TIMEFRAME_SECONDS = {
        "M1": 60,
        "M5": 5 * 60,
        "M15": 15 * 60,
        "M30": 30 * 60,
        "H1": 60 * 60,
        "H4": 4 * 60 * 60,
        "D1": 24 * 60 * 60,
        "W1": 7 * 24 * 60 * 60,
    }

    # Keeping each MT5 request small prevents a long M1 range from failing and
    # being silently replaced by only the latest `bars` candles.
    RANGE_CHUNK_TARGET_BARS = 4000

    def __init__(self, *, bars: int = 5000) -> None:
        self.bars = max(500, int(bars))

    @staticmethod
    def _parse_date(value: str, *, end_of_day: bool = False) -> datetime:
        raw = str(value or "").strip()
        if not raw:
            raise ValueError("empty_history_date")

        parsed = None
        for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y-%m-%dT%H:%M:%S"):
            try:
                parsed = datetime.strptime(raw, fmt)
                break
            except ValueError:
                pass

        if parsed is None:
            try:
                parsed = datetime.fromisoformat(raw)
            except ValueError as exc:
                raise ValueError(f"invalid_history_date:{raw}") from exc

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        else:
            parsed = parsed.astimezone(timezone.utc)

        if end_of_day:
            parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=0)
        else:
            parsed = parsed.replace(hour=0, minute=0, second=0, microsecond=0)

        return parsed

    @staticmethod
    def _mt5_error_text() -> str:
        try:
            return repr(mt5.last_error())
        except Exception:
            return "unknown_mt5_error"

    @classmethod
    def _load_range_in_chunks(
        cls,
        *,
        symbol: str,
        timeframe: str,
        mt5_timeframe: int,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        timeframe_seconds = cls.TIMEFRAME_SECONDS[timeframe]
        chunk_seconds = timeframe_seconds * (
            cls.RANGE_CHUNK_TARGET_BARS - 1
        )
        cursor = start
        chunks: list[pd.DataFrame] = []
        chunk_count = 0

        while cursor <= end:
            chunk_end = min(end, cursor + timedelta(seconds=chunk_seconds))
            raw = mt5.copy_rates_range(
                symbol,
                mt5_timeframe,
                cursor,
                chunk_end,
            )
            chunk_count += 1

            if raw is None:
                raise RuntimeError(
                    "mt5_history_chunk_failed:"
                    f"symbol={symbol}:"
                    f"timeframe={timeframe}:"
                    f"chunk={chunk_count}:"
                    f"from={cursor.isoformat()}:"
                    f"to={chunk_end.isoformat()}:"
                    f"error={cls._mt5_error_text()}"
                )

            if len(raw) > 0:
                chunk = pd.DataFrame(raw)
                if "time" not in chunk.columns:
                    raise RuntimeError("mt5_history_missing_time_column")
                chunks.append(chunk)

            cursor = chunk_end + timedelta(seconds=timeframe_seconds)

        if not chunks:
            raise RuntimeError(
                "mt5_history_empty:"
                f"symbol={symbol}:"
                f"timeframe={timeframe}:"
                f"from={start.isoformat()}:"
                f"to={end.isoformat()}:"
                f"chunks={chunk_count}:"
                f"error={cls._mt5_error_text()}"
            )

        start_ts = int(start.timestamp())
        end_ts = int(end.timestamp())
        rates = pd.concat(chunks, ignore_index=True)
        rates = rates[
            (rates["time"] >= start_ts)
            & (rates["time"] <= end_ts)
        ]
        rates = (
            rates
            .sort_values("time")
            .drop_duplicates(subset=["time"], keep="last")
            .reset_index(drop=True)
        )

        if rates.empty:
            raise RuntimeError(
                "mt5_history_empty_after_range_filter:"
                f"symbol={symbol}:"
                f"timeframe={timeframe}:"
                f"from={start.isoformat()}:"
                f"to={end.isoformat()}"
            )

        first_bar = datetime.fromtimestamp(
            int(rates["time"].iloc[0]),
            tz=timezone.utc,
        )
        last_bar = datetime.fromtimestamp(
            int(rates["time"].iloc[-1]),
            tz=timezone.utc,
        )
        boundary_tolerance = timedelta(
            seconds=max(4 * 24 * 60 * 60, timeframe_seconds * 2)
        )

        if first_bar > start + boundary_tolerance:
            raise RuntimeError(
                "mt5_history_incomplete_start:"
                f"symbol={symbol}:"
                f"timeframe={timeframe}:"
                f"requested={start.isoformat()}:"
                f"first_bar={first_bar.isoformat()}:"
                f"bars={len(rates)}:"
                f"chunks={chunk_count}"
            )

        if last_bar < end - boundary_tolerance:
            raise RuntimeError(
                "mt5_history_incomplete_end:"
                f"symbol={symbol}:"
                f"timeframe={timeframe}:"
                f"requested={end.isoformat()}:"
                f"last_bar={last_bar.isoformat()}:"
                f"bars={len(rates)}:"
                f"chunks={chunk_count}"
            )

        print(
            "[MT5 HISTORY] "
            f"symbol={symbol} timeframe={timeframe} "
            f"chunks={chunk_count} bars={len(rates)} "
            f"first={first_bar.isoformat()} last={last_bar.isoformat()}",
            flush=True,
        )
        return rates

    @classmethod
    def _resolve_broker_symbol(cls, requested_symbol: str) -> str:
        requested = str(requested_symbol or "").strip().upper()
        candidates = cls.SYMBOL_ALIASES.get(requested, (requested,))

        for candidate in candidates:
            if not mt5.symbol_select(candidate, True):
                continue
            if mt5.symbol_info(candidate) is not None:
                return candidate

        raise RuntimeError(
            "mt5_symbol_select_failed:"
            f"requested={requested}:"
            f"candidates={','.join(candidates)}:"
            f"error={cls._mt5_error_text()}"
        )

    def load(
        self,
        *,
        symbol: str,
        timeframe: str,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> HistoricalFrame:
        if not MT5_AVAILABLE:
            raise RuntimeError(
                "mt5_unavailable: MT5 is disabled in the Linux/Render demo"
            )

        symbol = str(symbol or "").strip().upper()
        timeframe = str(timeframe or "").strip().upper()

        if not symbol:
            raise ValueError("symbol_required")

        tf = self.TIMEFRAMES.get(timeframe)
        if tf is None:
            raise ValueError(
                "unsupported_timeframe:"
                f"value={timeframe!r}:"
                f"available={sorted(self.TIMEFRAMES.keys())}"
            )

        if not mt5.initialize():
            raise RuntimeError(
                f"mt5_initialize_failed:{self._mt5_error_text()}"
            )

        try:
            requested_symbol = symbol
            symbol = self._resolve_broker_symbol(requested_symbol)

            info = mt5.symbol_info(symbol)
            if info is None:
                raise RuntimeError(
                    f"mt5_symbol_info_missing:{symbol}:{self._mt5_error_text()}"
                )

            if date_from and date_to:
                start = self._parse_date(date_from)
                end = self._parse_date(date_to, end_of_day=True)

                now_utc = datetime.now(timezone.utc)
                if end > now_utc:
                    end = now_utc

                if start >= end:
                    raise ValueError(
                        f"invalid_history_range:{start.isoformat()}:{end.isoformat()}"
                    )

                rates = self._load_range_in_chunks(
                    symbol=symbol,
                    timeframe=timeframe,
                    mt5_timeframe=tf,
                    start=start,
                    end=end,
                )
            else:
                raw = mt5.copy_rates_from_pos(symbol, tf, 0, self.bars)

                if raw is None or len(raw) == 0:
                    raise RuntimeError(
                        "mt5_history_empty:"
                        f"symbol={symbol}:"
                        f"timeframe={timeframe}:"
                        f"error={self._mt5_error_text()}"
                    )

                rates = pd.DataFrame(raw)

            point = float(info.point) if info.point else 0.00001
            digits = int(info.digits)
            pip_size = point * 10 if digits in (3, 5) else point
            tick_size = float(info.trade_tick_size) if info.trade_tick_size else point
            tick_value = float(info.trade_tick_value) if info.trade_tick_value else 0.0
            pip_value = (
                tick_value * (pip_size / tick_size)
                if tick_size > 0 and tick_value > 0
                else 10.0
            )
            try:
                broker_minimum_stop_distance = max(
                    0.0,
                    float(getattr(info, "trade_stops_level", 0) or 0)
                    * point,
                )
            except (TypeError, ValueError, OverflowError):
                broker_minimum_stop_distance = 0.0

            try:
                lot_step = max(
                    0.00000001,
                    float(getattr(info, "volume_step", 0.01) or 0.01),
                )
                minimum_lot = max(
                    lot_step,
                    float(getattr(info, "volume_min", lot_step) or lot_step),
                )
                maximum_lot = max(
                    minimum_lot,
                    float(getattr(info, "volume_max", 100.0) or 100.0),
                )
            except (TypeError, ValueError, OverflowError):
                lot_step = 0.01
                minimum_lot = 0.01
                maximum_lot = 100.0

            return HistoricalFrame(
                symbol=symbol,
                timeframe=timeframe,
                rates=rates,
                pip_size=pip_size,
                tick_size=tick_size,
                pip_value_per_lot=pip_value,
                broker_minimum_stop_distance=(
                    broker_minimum_stop_distance
                ),
                lot_step=lot_step,
                minimum_lot=minimum_lot,
                maximum_lot=maximum_lot,
            )
        finally:
            mt5.shutdown()
