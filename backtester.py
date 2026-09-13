from __future__ import annotations

import csv
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import MetaTrader5 as mt5

from config import (
    MT5_PATH,
    MT5_TIMEOUT,
    SYMBOLS,
)

from engine.strategy_engine import (
    StrategyConfig,
    StrategyEngine,
)

from engine.trade_simulator import (
    SimulationConfig,
    TradeSimulator,
)


print("BACKTESTER VERSION: SMC X PRIME")


STARTING_BALANCE = 5000.0
RISK_PERCENT = 1.0

MINIMUM_RR = 2.0
MAXIMUM_RR = 3.0
PREFERRED_RR = 3.0

STOP_BUFFER_FRACTION = 0.05

BREAK_EVEN_TRIGGER_R = 1.0
PENDING_EXPIRY_BARS = 288
INTRABAR_PRIORITY = "STOP_FIRST"

H4_WARMUP_BARS = 150
D1_WARMUP_BARS = 250
M5_WARMUP_BARS = 120

MAX_SIMULTANEOUS_TRADES_PER_SYMBOL = 1
SKIP_FAILED_SYMBOLS = True

EXPORT_DIAGNOSTICS_CSV = True
DIAGNOSTICS_CSV_PATH = Path(
    "backtest_diagnostics.csv"
)


TEST_PERIODS = [
    (
        "2025 Q1",
        datetime(
            2025,
            1,
            1,
            tzinfo=timezone.utc,
        ),
        datetime(
            2025,
            4,
            1,
            tzinfo=timezone.utc,
        ),
    ),
    (
        "2025 Q2",
        datetime(
            2025,
            4,
            1,
            tzinfo=timezone.utc,
        ),
        datetime(
            2025,
            7,
            1,
            tzinfo=timezone.utc,
        ),
    ),
    (
        "2025 Q3",
        datetime(
            2025,
            7,
            1,
            tzinfo=timezone.utc,
        ),
        datetime(
            2025,
            10,
            1,
            tzinfo=timezone.utc,
        ),
    ),
    (
        "2025 Q4",
        datetime(
            2025,
            10,
            1,
            tzinfo=timezone.utc,
        ),
        datetime(
            2026,
            1,
            1,
            tzinfo=timezone.utc,
        ),
    ),
    (
        "2026 Q1",
        datetime(
            2026,
            1,
            1,
            tzinfo=timezone.utc,
        ),
        datetime(
            2026,
            4,
            1,
            tzinfo=timezone.utc,
        ),
    ),
    (
        "2026 Q2",
        datetime(
            2026,
            4,
            1,
            tzinfo=timezone.utc,
        ),
        datetime(
            2026,
            7,
            1,
            tzinfo=timezone.utc,
        ),
    ),
]


@dataclass
class SymbolResult:
    symbol: str
    signals: int
    trades: list[Any]

    wins: int
    losses: int
    break_even: int
    expired: int

    total_r: float
    win_rate: float
    profit_factor: float

    net_profit: float
    final_balance: float
    max_drawdown_percent: float


@dataclass
class PeriodResult:
    name: str
    start_date: datetime
    end_date: datetime

    symbol_results: list[SymbolResult]
    failed_symbols: list[tuple[str, str]]


def connect_mt5() -> None:
    initialized = mt5.initialize(
        path=MT5_PATH,
        timeout=MT5_TIMEOUT,
    )

    if not initialized:
        raise RuntimeError(
            "Не удалось подключиться к MT5: "
            f"{mt5.last_error()}"
        )

    print("✅ MT5 подключён")


def load_rates(
    symbol: str,
    timeframe: int,
    start: datetime,
    end: datetime,
) -> Any:
    selected = mt5.symbol_select(
        symbol,
        True,
    )

    if not selected:
        raise RuntimeError(
            f"Не удалось выбрать {symbol}: "
            f"{mt5.last_error()}"
        )

    rates = mt5.copy_rates_range(
        symbol,
        timeframe,
        start,
        end,
    )

    if rates is None:
        raise RuntimeError(
            f"Ошибка загрузки {symbol}: "
            f"{mt5.last_error()}"
        )

    if len(rates) == 0:
        raise RuntimeError(
            f"Для {symbol} MT5 вернул 0 свечей"
        )

    return rates


def enum_text(
    value: Any,
) -> str:
    if value is None:
        return ""

    raw_value = getattr(
        value,
        "value",
        value,
    )

    return str(
        raw_value
    ).upper()


def get_trade_outcome(
    trade: Any,
) -> str:
    for attribute in (
        "outcome",
        "result",
        "status",
    ):
        value = getattr(
            trade,
            attribute,
            None,
        )

        if value is None:
            continue

        text = enum_text(
            value
        )

        if (
            "BREAK" in text
            or text == "BE"
        ):
            return "BREAK_EVEN"

        if (
            "WIN" in text
            or "TARGET" in text
            or "TAKE_PROFIT" in text
            or text == "TP"
        ):
            return "WIN"

        if (
            "LOSS" in text
            or "STOP_LOSS" in text
            or text == "SL"
        ):
            return "LOSS"

        if (
            "EXPIRED" in text
            or "CANCEL" in text
            or "NOT_TRIGGERED" in text
        ):
            return "EXPIRED"

        if "OPEN" in text:
            return "OPEN"

        if "PENDING" in text:
            return "PENDING"

    return "UNKNOWN"


def get_trade_time(
    trade: Any,
    attribute: str,
) -> int | None:
    value = getattr(
        trade,
        attribute,
        None,
    )

    if value is None:
        return None

    try:
        return int(
            value
        )

    except (
        TypeError,
        ValueError,
    ):
        return None


def get_trade_r(
    trade: Any,
) -> float:
    for attribute in (
        "result_r",
        "r_multiple",
        "realized_r",
        "profit_r",
    ):
        value = getattr(
            trade,
            attribute,
            None,
        )

        if value is None:
            continue

        try:
            return float(
                value
            )

        except (
            TypeError,
            ValueError,
        ):
            continue

    outcome = get_trade_outcome(
        trade
    )

    if outcome == "LOSS":
        return -1.0

    if outcome == "BREAK_EVEN":
        return 0.0

    if outcome == "WIN":
        trade_data = getattr(
            trade,
            "trade_data",
            None,
        )

        if isinstance(
            trade_data,
            dict,
        ):
            rr = trade_data.get(
                "rr",
                PREFERRED_RR,
            )

            try:
                return float(
                    rr
                )

            except (
                TypeError,
                ValueError,
            ):
                pass

        rr = getattr(
            trade,
            "rr",
            None,
        )

        if rr is not None:
            try:
                return float(
                    rr
                )

            except (
                TypeError,
                ValueError,
            ):
                pass

        return PREFERRED_RR

    return 0.0


def trade_sort_time(
    trade: Any,
) -> int:
    return (
        get_trade_time(
            trade,
            "close_time",
        )
        or get_trade_time(
            trade,
            "open_time",
        )
        or get_trade_time(
            trade,
            "signal_time",
        )
        or 0
    )


def count_active_trades(
    trades: list[Any],
    symbol: str,
    signal_time: int,
) -> int:
    active_count = 0

    for trade in trades:
        trade_symbol = getattr(
            trade,
            "symbol",
            None,
        )

        if trade_symbol != symbol:
            continue

        open_time = get_trade_time(
            trade,
            "open_time",
        )

        close_time = get_trade_time(
            trade,
            "close_time",
        )

        # Неисполненная лимитка не считается активной позицией.
        if (
            open_time is None
            or open_time > signal_time
        ):
            continue

        # Сделка уже закрылась до нового сигнала.
        if (
            close_time is not None
            and close_time <= signal_time
        ):
            continue

        active_count += 1

    return active_count

def calculate_result(
    symbol: str,
    signals: int,
    trades: list[Any],
) -> SymbolResult:
    wins = 0
    losses = 0
    break_even = 0
    expired = 0

    total_r = 0.0
    gross_profit_r = 0.0
    gross_loss_r = 0.0

    balance = STARTING_BALANCE
    peak_balance = STARTING_BALANCE
    max_drawdown_percent = 0.0

    ordered_trades = sorted(
        trades,
        key=trade_sort_time,
    )

    for trade in ordered_trades:
        outcome = get_trade_outcome(
            trade
        )

        trade_r = get_trade_r(
            trade
        )

        if outcome == "WIN":
            wins += 1

        elif outcome == "LOSS":
            losses += 1

        elif outcome == "BREAK_EVEN":
            break_even += 1

        elif outcome == "EXPIRED":
            expired += 1

        if trade_r > 0:
            gross_profit_r += trade_r

        elif trade_r < 0:
            gross_loss_r += abs(
                trade_r
            )

        total_r += trade_r

        risk_money = (
            balance
            * (
                RISK_PERCENT
                / 100.0
            )
        )

        balance += (
            risk_money
            * trade_r
        )

        peak_balance = max(
            peak_balance,
            balance,
        )

        if peak_balance > 0:
            drawdown_percent = (
                (
                    peak_balance
                    - balance
                )
                / peak_balance
                * 100.0
            )

            max_drawdown_percent = max(
                max_drawdown_percent,
                drawdown_percent,
            )

    closed_trades = (
        wins
        + losses
        + break_even
    )

    win_rate = (
        wins
        / closed_trades
        * 100.0
        if closed_trades > 0
        else 0.0
    )

    if gross_loss_r > 0:
        profit_factor = (
            gross_profit_r
            / gross_loss_r
        )

    elif gross_profit_r > 0:
        profit_factor = float(
            "inf"
        )

    else:
        profit_factor = 0.0

    return SymbolResult(
        symbol=symbol,
        signals=signals,
        trades=trades,
        wins=wins,
        losses=losses,
        break_even=break_even,
        expired=expired,
        total_r=round(
            total_r,
            2,
        ),
        win_rate=round(
            win_rate,
            2,
        ),
        profit_factor=profit_factor,
        net_profit=round(
            balance
            - STARTING_BALANCE,
            2,
        ),
        final_balance=round(
            balance,
            2,
        ),
        max_drawdown_percent=round(
            max_drawdown_percent,
            2,
        ),
    )


def safe_value(
    value: Any,
) -> Any:
    if value is None:
        return ""

    if isinstance(
        value,
        bool,
    ):
        return int(
            value
        )

    if isinstance(
        value,
        (
            str,
            int,
            float,
        ),
    ):
        return value

    return str(
        value
    )


def safe_dict(
    value: Any,
) -> dict[str, Any]:
    if isinstance(
        value,
        dict,
    ):
        return value

    return {}


def get_trade_data(
    trade: Any,
) -> dict[str, Any]:
    trade_data = getattr(
        trade,
        "trade_data",
        None,
    )

    return safe_dict(
        trade_data
    )


def get_trade_diagnostics(
    trade: Any,
) -> dict[str, Any]:
    trade_data = get_trade_data(
        trade
    )

    diagnostics = trade_data.get(
        "diagnostics",
        {},
    )

    return safe_dict(
        diagnostics
    )


def diagnostics_row(
    period_name: str,
    symbol: str,
    trade: Any,
) -> dict[str, Any]:
    trade_data = get_trade_data(
        trade
    )

    diagnostics = (
        get_trade_diagnostics(
            trade
        )
    )

    h4_order_block = safe_dict(
        trade_data.get(
            "h4_order_block",
            {},
        )
    )

    m5_order_block = safe_dict(
        trade_data.get(
            "m5_order_block",
            {},
        )
    )

    liquidity_sweep = safe_dict(
        trade_data.get(
            "liquidity_sweep",
            {},
        )
    )

    internal_choch = safe_dict(
        trade_data.get(
            "internal_choch",
            {},
        )
    )

    internal_bos = safe_dict(
        trade_data.get(
            "internal_bos",
            {},
        )
    )

    return {
        "period": period_name,
        "symbol": symbol,

        "direction": getattr(
            trade,
            "direction",
            trade_data.get(
                "direction",
                "",
            ),
        ),

        "order_type": getattr(
            trade,
            "order_type",
            trade_data.get(
                "order_type",
                "",
            ),
        ),

        "signal_time": getattr(
            trade,
            "signal_time",
            trade_data.get(
                "signal_time",
                "",
            ),
        ),

        "open_time": getattr(
            trade,
            "open_time",
            "",
        ),

        "pending_end_time": getattr(
            trade,
            "pending_end_time",
            "",
        ),

        "close_time": getattr(
            trade,
            "close_time",
            "",
        ),

        "outcome": get_trade_outcome(
            trade
        ),

        "result_r": get_trade_r(
            trade
        ),

        "entry": getattr(
            trade,
            "entry",
            trade_data.get(
                "entry",
                "",
            ),
        ),

        "initial_stop_loss": getattr(
            trade,
            "initial_stop_loss",
            trade_data.get(
                "stop_loss",
                "",
            ),
        ),

        "take_profit": getattr(
            trade,
            "take_profit",
            trade_data.get(
                "take_profit",
                "",
            ),
        ),

        "rr": getattr(
            trade,
            "rr",
            trade_data.get(
                "rr",
                "",
            ),
        ),

        "strategy_name": diagnostics.get(
            "strategy_name",
            "",
        ),

        "higher_timeframe_direction": (
            diagnostics.get(
                "direction",
                trade_data.get(
                    "direction",
                    "",
                ),
            )
        ),

        "h4_order_block_time": (
            h4_order_block.get(
                "time",
                diagnostics.get(
                    "selected_h4_order_block_time",
                    "",
                ),
            )
        ),

        "h4_bos_time": (
            h4_order_block.get(
                "bos_time",
                diagnostics.get(
                    "selected_h4_bos_time",
                    "",
                ),
            )
        ),

        "h4_quality_score": (
            h4_order_block.get(
                "quality_score",
                h4_order_block.get(
                    "score",
                    diagnostics.get(
                        "selected_h4_quality_score",
                        "",
                    ),
                ),
            )
        ),

        "h4_ob_high": h4_order_block.get(
            "high",
            "",
        ),

        "h4_ob_low": h4_order_block.get(
            "low",
            "",
        ),

        "h4_ob_proximal": h4_order_block.get(
            "proximal",
            "",
        ),

        "h4_ob_distal": h4_order_block.get(
            "distal",
            "",
        ),

        "h4_zone_touch_time": diagnostics.get(
            "h4_zone_touch_time",
            "",
        ),

        "liquidity_sweep_time": (
            liquidity_sweep.get(
                "time",
                diagnostics.get(
                    "liquidity_sweep_time",
                    "",
                ),
            )
        ),

        "liquidity_sweep_level": (
            liquidity_sweep.get(
                "level",
                "",
            )
        ),

        "liquidity_sweep_price": (
            liquidity_sweep.get(
                "price",
                "",
            )
        ),

        "internal_choch_time": (
            internal_choch.get(
                "time",
                diagnostics.get(
                    "internal_choch_time",
                    "",
                ),
            )
        ),

        "internal_choch_level": (
            internal_choch.get(
                "level",
                "",
            )
        ),

        "internal_bos_time": (
            internal_bos.get(
                "time",
                diagnostics.get(
                    "internal_bos_time",
                    "",
                ),
            )
        ),

        "internal_bos_level": (
            internal_bos.get(
                "level",
                "",
            )
        ),

        "m5_order_block_time": (
            m5_order_block.get(
                "time",
                diagnostics.get(
                    "m5_order_block_time",
                    "",
                ),
            )
        ),

        "m5_ob_high": m5_order_block.get(
            "high",
            "",
        ),

        "m5_ob_low": m5_order_block.get(
            "low",
            "",
        ),

        "m5_ob_proximal": m5_order_block.get(
            "proximal",
            "",
        ),

        "m5_ob_distal": m5_order_block.get(
            "distal",
            "",
        ),

        "dynamic_target": trade_data.get(
            "dynamic_target",
            diagnostics.get(
                "dynamic_target",
                "",
            ),
        ),

        "daily_blocker": diagnostics.get(
            "daily_blocker",
            "",
        ),

        "signal_confirmed": diagnostics.get(
            "signal_confirmed",
            "",
        ),

        "d1_candles": diagnostics.get(
            "d1_candles",
            "",
        ),

        "h4_candles": diagnostics.get(
            "h4_candles",
            "",
        ),

        "m5_candles": diagnostics.get(
            "m5_candles",
            "",
        ),

        "closest_distance_to_entry": getattr(
            trade,
            "closest_distance_to_entry",
            "",
        ),

        "closest_distance_r": getattr(
            trade,
            "closest_distance_r",
            "",
        ),

        "closest_price": getattr(
            trade,
            "closest_price",
            "",
        ),

        "closest_bar_index": getattr(
            trade,
            "closest_bar_index",
            "",
        ),

        "closest_time": getattr(
            trade,
            "closest_time",
            "",
        ),

        "max_favorable_price": getattr(
            trade,
            "max_favorable_price",
            "",
        ),

        "max_adverse_price": getattr(
            trade,
            "max_adverse_price",
            "",
        ),

        "bars_until_touch": getattr(
            trade,
            "bars_until_touch",
            "",
        ),

        "touched_after_expiry": getattr(
            trade,
            "touched_after_expiry",
            "",
        ),

        "bars_after_expiry_until_touch": getattr(
            trade,
            "bars_after_expiry_until_touch",
            "",
        ),

        "touch_time_after_expiry": getattr(
            trade,
            "touch_time_after_expiry",
            "",
        ),

        "expired_reason": getattr(
            trade,
            "expired_reason",
            "",
        ),
    }


def export_diagnostics(
    period_results: list[PeriodResult],
) -> None:
    if not EXPORT_DIAGNOSTICS_CSV:
        return

    rows: list[
        dict[str, Any]
    ] = []

    for period in period_results:
        for symbol_result in (
            period.symbol_results
        ):
            for trade in (
                symbol_result.trades
            ):
                rows.append(
                    diagnostics_row(
                        period_name=period.name,
                        symbol=symbol_result.symbol,
                        trade=trade,
                    )
                )

    if not rows:
        print(
            "⚠️ Диагностический CSV "
            "не создан: сделок нет"
        )
        return

    DIAGNOSTICS_CSV_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with DIAGNOSTICS_CSV_PATH.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=list(
                rows[0].keys()
            ),
        )

        writer.writeheader()

        for row in rows:
            cleaned_row = {
                key: safe_value(
                    value
                )
                for key, value
                in row.items()
            }

            writer.writerow(
                cleaned_row
            )

    print(
        "\n✅ Диагностика сохранена: "
        f"{DIAGNOSTICS_CSV_PATH.resolve()}"
    )

    print(
        "✅ Строк в CSV: "
        f"{len(rows)}"
    )

def run_symbol(
    symbol: str,
    start_date: datetime,
    end_date: datetime,
) -> SymbolResult:
    print("\n" + "=" * 65)
    print(f"ЗАПУСК: {symbol}")
    print(
        f"ПЕРИОД: {start_date.date()} → {end_date.date()}"
    )
    print("=" * 65)

    history_start = start_date - timedelta(days=400)
    m5_history_start = start_date - timedelta(days=10)

    d1_rates = load_rates(
        symbol=symbol,
        timeframe=mt5.TIMEFRAME_D1,
        start=history_start,
        end=end_date,
    )
    h4_rates = load_rates(
        symbol=symbol,
        timeframe=mt5.TIMEFRAME_H4,
        start=history_start,
        end=end_date,
    )
    m5_rates = load_rates(
        symbol=symbol,
        timeframe=mt5.TIMEFRAME_M5,
        start=m5_history_start,
        end=end_date,
    )

    print(f"D1 свечей: {len(d1_rates)}")
    print(f"H4 свечей: {len(h4_rates)}")
    print(f"M5 свечей: {len(m5_rates)}")

    if len(d1_rates) < D1_WARMUP_BARS:
        raise RuntimeError(
            f"{symbol}: недостаточно D1-свечей"
        )
    if len(h4_rates) < H4_WARMUP_BARS:
        raise RuntimeError(
            f"{symbol}: недостаточно H4-свечей"
        )
    if len(m5_rates) < M5_WARMUP_BARS:
        raise RuntimeError(
            f"{symbol}: недостаточно M5-свечей"
        )

    strategy = StrategyEngine(
        config=StrategyConfig(
            minimum_rr=MINIMUM_RR,
            preferred_rr=PREFERRED_RR,
            maximum_rr=MAXIMUM_RR,
            stop_buffer_fraction=STOP_BUFFER_FRACTION,
        )
    )
    simulator = TradeSimulator(
        SimulationConfig(
            break_even_trigger_r=BREAK_EVEN_TRIGGER_R,
            pending_expiry_bars=PENDING_EXPIRY_BARS,
            intrabar_priority=INTRABAR_PRIORITY,
        )
    )

    d1_times = [
        int(candle["time"])
        for candle in d1_rates
    ]
    h4_times = [
        int(candle["time"])
        for candle in h4_rates
    ]
    m5_times = [
        int(candle["time"])
        for candle in m5_rates
    ]

    d1_close_times = [
        candle_time + 86400
        for candle_time in d1_times
    ]
    h4_close_times = [
        candle_time + 14400
        for candle_time in h4_times
    ]
    m5_close_times = [
        candle_time + 300
        for candle_time in m5_times
    ]

    start_timestamp = int(start_date.timestamp())
    end_timestamp = int(end_date.timestamp())

    first_test_index = bisect_left(
        m5_close_times,
        start_timestamp,
    )
    first_test_index = max(
        first_test_index,
        M5_WARMUP_BARS - 1,
    )

    trades: list[Any] = []
    signals = 0
    no_signal_reasons: dict[str, int] = {}
    processed_signal_times: set[int] = set()
    last_processed_h4_count = -1

    def add_reason(reason: Any) -> None:
        reason_text = str(reason or "UNKNOWN")
        no_signal_reasons[reason_text] = (
            no_signal_reasons.get(reason_text, 0)
            + 1
        )

    for m5_index in range(
        first_test_index,
        len(m5_rates),
    ):
        current_close_time = m5_close_times[m5_index]

        if current_close_time < start_timestamp:
            continue
        if current_close_time >= end_timestamp:
            break

        completed_m5_count = m5_index + 1
        completed_h4_count = bisect_right(
            h4_close_times,
            current_close_time,
        )
        completed_d1_count = bisect_right(
            d1_close_times,
            current_close_time,
        )

        if completed_m5_count < M5_WARMUP_BARS:
            continue
        if completed_h4_count < H4_WARMUP_BARS:
            continue
        if completed_d1_count < D1_WARMUP_BARS:
            continue

        # Диагностический режим: тяжёлый полный анализ запускается
        # только один раз после закрытия каждой новой H4-свечи.
        if completed_h4_count == last_processed_h4_count:
            continue
        last_processed_h4_count = completed_h4_count

        strategy_result = strategy.process(
            h4_rates=h4_rates[:completed_h4_count],
            d1_rates=d1_rates[:completed_d1_count],
            m5_rates=m5_rates[:completed_m5_count],
        )

        event = str(
            getattr(strategy_result, "event", "")
            or ""
        ).upper()

        if event != "SIGNAL":
            add_reason(
                getattr(
                    strategy_result,
                    "reason",
                    event or "UNKNOWN",
                )
            )
            continue

        trade_data = getattr(
            strategy_result,
            "trade",
            None,
        )
        if not isinstance(trade_data, dict):
            add_reason("signal_trade_data_invalid")
            continue

        prepared_trade = dict(trade_data)
        signal_time = int(
            prepared_trade.get(
                "signal_time",
                current_close_time,
            )
        )

        if signal_time in processed_signal_times:
            add_reason("duplicate_signal_time")
            continue

        processed_signal_times.add(signal_time)
        signals += 1

        active_trades = count_active_trades(
            trades=trades,
            symbol=symbol,
            signal_time=signal_time,
        )
        if (
            active_trades
            >= MAX_SIMULTANEOUS_TRADES_PER_SYMBOL
        ):
            add_reason("active_trade_limit")
            continue

        simulation_start_index = bisect_left(
            m5_times,
            signal_time,
        )
        if simulation_start_index >= len(m5_rates):
            add_reason("m5_data_missing_after_signal")
            continue

        simulated_trade = simulator.simulate(
            trade_data=prepared_trade,
            candles=m5_rates[simulation_start_index:],
            signal_time=signal_time,
        )

        simulated_trade.symbol = symbol
        simulated_trade.trade_data = prepared_trade

        diagnostics = getattr(
            strategy_result,
            "diagnostics",
            {},
        )
        if not isinstance(diagnostics, dict):
            diagnostics = {}

        simulated_trade.trade_data[
            "diagnostics"
        ] = dict(diagnostics)

        for field_name in (
            "higher_timeframe_structure",
            "h4_order_block",
            "liquidity_sweep",
            "internal_choch",
            "internal_bos",
        ):
            field_value = getattr(
                strategy_result,
                field_name,
                None,
            )
            if field_value is not None:
                simulated_trade.trade_data[
                    field_name
                ] = field_value

        trades.append(simulated_trade)

    result = calculate_result(
        symbol=symbol,
        signals=signals,
        trades=trades,
    )

    print(f"\n✅ {symbol} завершён")
    print(f"Сигналов: {result.signals}")
    print(f"Сделок: {len(result.trades)}")
    print(
        "W / L / BE / Expired: "
        f"{result.wins} / "
        f"{result.losses} / "
        f"{result.break_even} / "
        f"{result.expired}"
    )
    print(f"Total R: {result.total_r}")
    print(f"Net: ${result.net_profit}")
    print(
        f"Max DD: {result.max_drawdown_percent}%"
    )

    print("\nПричины отсутствия сигналов:")
    if no_signal_reasons:
        for reason, count in sorted(
            no_signal_reasons.items(),
            key=lambda item: item[1],
            reverse=True,
        ):
            print(f"  • {reason}: {count}")
    else:
        print("  • нет")

    return result

def run_period(
    name: str,
    start_date: datetime,
    end_date: datetime,
) -> PeriodResult:
    print("\n")
    print("=" * 90)
    print(
        f"ПЕРИОД: {name}"
    )
    print("=" * 90)

    symbol_results: list[SymbolResult] = []
    failed_symbols: list[
        tuple[str, str]
    ] = []

    for symbol in SYMBOLS:
        try:
            result = run_symbol(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
            )

            symbol_results.append(
                result
            )

        except Exception as error:
            print(
                f"\n❌ {symbol}: {error}"
            )

            failed_symbols.append(
                (
                    symbol,
                    str(error),
                )
            )

            if not SKIP_FAILED_SYMBOLS:
                raise

    return PeriodResult(
        name=name,
        start_date=start_date,
        end_date=end_date,
        symbol_results=symbol_results,
        failed_symbols=failed_symbols,
    )

def print_summary(
    period_results: list[PeriodResult],
) -> None:
    print("\n")
    print("=" * 130)
    print("СВОДКА ПО ВСЕМ ТЕСТОВЫМ ПЕРИОДАМ")
    print("=" * 130)

    for period in period_results:
        print(f"\n{period.name}")
        print("-" * 130)

        print(
            f"{'SYMBOL':<12}"
            f"{'SIGNALS':>10}"
            f"{'TRADES':>10}"
            f"{'WINS':>8}"
            f"{'LOSSES':>10}"
            f"{'WIN %':>10}"
            f"{'PF':>10}"
            f"{'TOTAL R':>12}"
            f"{'MAX DD':>12}"
            f"{'NET $':>12}"
        )

        print("-" * 130)

        for result in period.symbol_results:
            pf_text = (
                "INF"
                if result.profit_factor == float("inf")
                else f"{result.profit_factor:.2f}"
            )

            print(
                f"{result.symbol:<12}"
                f"{result.signals:>10}"
                f"{len(result.trades):>10}"
                f"{result.wins:>8}"
                f"{result.losses:>10}"
                f"{result.win_rate:>9.2f}%"
                f"{pf_text:>10}"
                f"{result.total_r:>12.2f}"
                f"{result.max_drawdown_percent:>11.2f}%"
                f"{result.net_profit:>12.2f}"
            )

        if period.failed_symbols:
            print("\nОшибки:")

            for symbol, error in period.failed_symbols:
                print(
                    f"{symbol}: {error}"
                )

def main() -> None:
    period_results: list[PeriodResult] = []

    try:
        connect_mt5()

        for (
            period_name,
            start_date,
            end_date,
        ) in TEST_PERIODS:

            period_result = run_period(
                name=period_name,
                start_date=start_date,
                end_date=end_date,
            )

            period_results.append(
                period_result
            )

        print_summary(
            period_results
        )

        export_diagnostics(
            period_results
        )

    finally:
        mt5.shutdown()
        print("\n✅ MT5 отключён")


if __name__ == "__main__":
    main()