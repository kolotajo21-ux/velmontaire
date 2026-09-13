import MetaTrader5 as mt5

from config import (
    SYMBOL,
    H1_CANDLES,
    M5_CANDLES,
    SWING_LENGTH,
)

from market_data import (
    connect_mt5,
    get_rates,
)

from structure import (
    find_swings,
    detect_trend,
)

from concepts.liquidity import detect_liquidity_sweep
from choch import detect_choch
from bos import detect_bos_after_choch


RECENT_CANDLES_TO_CHECK = 80


def get_h1_trend(h1_rates):
    swing_highs, swing_lows = find_swings(
        h1_rates,
        SWING_LENGTH,
    )

    return detect_trend(
        swing_highs,
        swing_lows,
    )


def find_sweep_choch_and_bos(
    m5_rates,
    direction,
):
    start_index = max(
        20,
        len(m5_rates) - RECENT_CANDLES_TO_CHECK,
    )

    sweep = None
    choch = None

    for index in range(
        start_index,
        len(m5_rates) - 1,
    ):
        rates_slice = m5_rates[:index + 1]

        if sweep is None:
            sweep = detect_liquidity_sweep(
                rates_slice,
                direction,
                SWING_LENGTH,
            )

            if sweep is not None:
                continue

        if sweep is not None and choch is None:
            detected_choch = detect_choch(
                rates_slice,
                direction,
                SWING_LENGTH,
            )

            if (
                detected_choch is not None
                and detected_choch["time"]
                > sweep["time"]
            ):
                choch = detected_choch
                continue

        if sweep is not None and choch is not None:
            bos = detect_bos_after_choch(
                rates_slice,
                direction,
                choch["time"],
                SWING_LENGTH,
            )

            if (
                bos is not None
                and bos["time"] > choch["time"]
            ):
                return {
                    "direction": direction,
                    "sweep": sweep,
                    "choch": choch,
                    "bos": bos,
                }

    return None


if not connect_mt5():
    raise SystemExit

h1_rates = get_rates(
    SYMBOL,
    mt5.TIMEFRAME_H1,
    H1_CANDLES,
)

m5_rates = get_rates(
    SYMBOL,
    mt5.TIMEFRAME_M5,
    M5_CANDLES,
)

if h1_rates is None or m5_rates is None:
    mt5.shutdown()
    raise SystemExit

h1_trend = get_h1_trend(h1_rates)

print("\n===== M5 ENTRY CHECK =====")
print(f"Symbol: {SYMBOL}")
print(f"H1 trend: {h1_trend}")

if h1_trend not in ("BULLISH", "BEARISH"):
    print("⛔ H1 находится в RANGE")
    mt5.shutdown()
    raise SystemExit

setup = find_sweep_choch_and_bos(
    m5_rates,
    h1_trend,
)

if setup is None:
    print(
        "⛔ Связка Sweep → CHOCH → BOS "
        "не найдена"
    )

else:
    sweep = setup["sweep"]
    choch = setup["choch"]
    bos = setup["bos"]

    print("\n✅ Полное M5 подтверждение найдено")
    print(f"Direction: {setup['direction']}")

    print("\n----- LIQUIDITY SWEEP -----")
    print(f"Type: {sweep['type']}")
    print(f"Swept level: {sweep['swept_level']}")
    print(f"Extreme: {sweep['extreme']}")
    print(f"Close: {sweep['close']}")
    print(f"Time: {sweep['time']}")

    print("\n----- CHOCH -----")
    print(f"Type: {choch['type']}")
    print(f"Broken level: {choch['broken_level']}")
    print(f"Close: {choch['close']}")
    print(f"Time: {choch['time']}")

    print("\n----- BOS -----")
    print(f"Type: {bos['type']}")
    print(f"Broken level: {bos['broken_level']}")
    print(f"Close: {bos['close']}")
    print(f"Pullback extreme: {bos['pullback_extreme']}")
    print(f"Time: {bos['time']}")

mt5.shutdown()