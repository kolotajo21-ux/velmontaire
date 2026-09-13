import time

import MetaTrader5 as mt5

from config import (
    SYMBOL,
    H1_CANDLES,
    M5_CANDLES,
    SWING_LENGTH,
)

from market_data import connect_mt5, get_rates
from structure import find_swings, detect_trend
from concepts.liquidity import detect_liquidity_sweep
from choch import detect_choch
from bos import detect_bos_after_choch
from signal_engine import SignalState


CHECK_INTERVAL_SECONDS = 5
HISTORY_LOOKBACK = 120


def get_h1_trend():
    h1_rates = get_rates(
        SYMBOL,
        mt5.TIMEFRAME_H1,
        H1_CANDLES,
    )

    if h1_rates is None:
        return "RANGE"

    swing_highs, swing_lows = find_swings(
        h1_rates,
        SWING_LENGTH,
    )

    return detect_trend(
        swing_highs,
        swing_lows,
    )


def process_candles(
    rates,
    direction,
    state,
):
    start_index = max(
        20,
        len(rates) - HISTORY_LOOKBACK,
    )

    for index in range(
        start_index,
        len(rates) - 1,
    ):
        rates_slice = rates[: index + 1]

        if state.stage == "WAIT_SWEEP":
            sweep = detect_liquidity_sweep(
                rates_slice,
                direction,
                SWING_LENGTH,
            )

            if sweep is not None:
                state.register_sweep(sweep)

                print("\n✅ Найден Liquidity Sweep")
                print(f"Тип: {sweep['type']}")
                print(f"Время: {sweep['time']}")
                print(f"Следующая стадия: {state.stage}")

        elif state.stage == "WAIT_CHOCH":
            choch = detect_choch(
                rates_slice,
                direction,
                SWING_LENGTH,
            )

            if choch is not None:
                if state.register_choch(choch):
                    print("\n✅ Найден CHOCH")
                    print(f"Тип: {choch['type']}")
                    print(f"Время: {choch['time']}")
                    print(f"Следующая стадия: {state.stage}")

        elif state.stage == "WAIT_BOS":
            bos = detect_bos_after_choch(
                rates_slice,
                direction,
                state.choch["time"],
                SWING_LENGTH,
            )

            if bos is not None:
                if state.register_bos(bos):
                    print("\n✅ Найден BOS")
                    print(f"Тип: {bos['type']}")
                    print(f"Время: {bos['time']}")
                    print(f"Следующая стадия: {state.stage}")

        if state.is_ready():
            return state

    return state


def print_status(
    trend,
    state,
    candle_time,
):
    print(
        f"\nНовая M5 свеча: {candle_time}"
        f" | H1: {trend}"
        f" | Stage: {state.stage}"
    )


if not connect_mt5():
    raise SystemExit

state = SignalState()
active_direction = None
last_closed_candle_time = None

print("\n===== LIVE BOT ЗАПУЩЕН =====")
print(f"Символ: {SYMBOL}")
print("Остановка: Ctrl + C")

try:
    while True:
        h1_trend = get_h1_trend()

        m5_rates = get_rates(
            SYMBOL,
            mt5.TIMEFRAME_M5,
            M5_CANDLES,
        )

        if m5_rates is None:
            print("❌ Не удалось получить M5-свечи")
            time.sleep(CHECK_INTERVAL_SECONDS)
            continue

        # Последняя полностью закрытая свеча
        closed_candle = m5_rates[-2]
        closed_candle_time = int(
            closed_candle["time"]
        )

        # Не обрабатываем одну свечу несколько раз
        if (
            closed_candle_time
            == last_closed_candle_time
        ):
            time.sleep(CHECK_INTERVAL_SECONDS)
            continue

        last_closed_candle_time = (
            closed_candle_time
        )

        print_status(
            h1_trend,
            state,
            closed_candle_time,
        )

        if h1_trend not in (
            "BULLISH",
            "BEARISH",
        ):
            print("⛔ H1 находится в RANGE")
            state.reset()
            active_direction = None
            continue

        # Если направление H1 изменилось —
        # старый сетап сбрасываем
        if (
            active_direction is not None
            and h1_trend != active_direction
        ):
            print(
                "⚠️ Направление H1 изменилось. "
                "Сетап сброшен."
            )

            state.reset()

        active_direction = h1_trend

        state = process_candles(
            m5_rates,
            active_direction,
            state,
        )

        if state.is_ready():
            print("\n🔥 СЕТАП ГОТОВ К ПОИСКУ ВХОДА")
            print(f"Direction: {state.direction}")
            print(f"Sweep: {state.sweep['time']}")
            print(f"CHOCH: {state.choch['time']}")
            print(f"BOS: {state.bos['time']}")

            # Пока не открываем сделку.
            # После расчёта Entry/SL/TP подключим executor.
            break

        time.sleep(CHECK_INTERVAL_SECONDS)

except KeyboardInterrupt:
    print("\n🛑 Бот остановлен вручную")

finally:
    mt5.shutdown()
    print("MT5 отключён")