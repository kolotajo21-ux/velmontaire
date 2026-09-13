from __future__ import annotations

import MetaTrader5 as mt5

from config import (
    SYMBOL,
    D1_CANDLES,
    H4_CANDLES,
    M5_CANDLES,
    MT5_PATH,
    MT5_TIMEOUT,

)


def connect_mt5():
    connected = mt5.initialize(
        path=MT5_PATH,
        timeout=MT5_TIMEOUT,
    )

    if not connected:
        print("❌ Ошибка подключения:", mt5.last_error())
        return False

    return True


def get_rates(symbol, timeframe, count):
    if not mt5.symbol_select(symbol, True):
        print(f"❌ Не удалось выбрать {symbol}")
        return None

    rates = mt5.copy_rates_from_pos(
        symbol,
        timeframe,
        0,
        count,
    )

    if rates is None:
        print("❌ Не удалось получить свечи")
        print(mt5.last_error())
        return None

    return rates


if __name__ == "__main__":
    if not connect_mt5():
        raise SystemExit

    h1_rates = get_rates(
        SYMBOL,
        mt5.TIMEFRAME_H1,
        H4_CANDLES,
    )

    m5_rates = get_rates(
        SYMBOL,
        mt5.TIMEFRAME_M5,
        M5_CANDLES,
    )

    if h1_rates is not None:
        print(f"✅ H1 свечей: {len(h1_rates)}")

    if m5_rates is not None:
        print(f"✅ M5 свечей: {len(m5_rates)}")

    mt5.shutdown()