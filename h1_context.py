import MetaTrader5 as mt5

from config import (
    SYMBOL,
    H1_CANDLES,
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


def detect_h1_context(rates):
    swing_highs, swing_lows = find_swings(
        rates,
        SWING_LENGTH,
    )

    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return None

    trend = detect_trend(
        swing_highs,
        swing_lows,
    )

    dealing_high = swing_highs[-1]["price"]
    dealing_low = swing_lows[-1]["price"]

    if dealing_high <= dealing_low:
        return None

    equilibrium = (dealing_high + dealing_low) / 2
    last_close = float(rates[-2]["close"])

    if last_close < equilibrium:
        zone = "DISCOUNT"
    elif last_close > equilibrium:
        zone = "PREMIUM"
    else:
        zone = "EQUILIBRIUM"

    return {
        "trend": trend,
        "last_close": last_close,
        "dealing_high": dealing_high,
        "dealing_low": dealing_low,
        "equilibrium": equilibrium,
        "zone": zone,
    }


def print_h1_context(context):
    print("\n===== H1 CONTEXT =====")
    print(f"Trend: {context['trend']}")
    print(f"Last close: {context['last_close']}")
    print(f"Dealing high: {context['dealing_high']}")
    print(f"Dealing low: {context['dealing_low']}")
    print(f"Equilibrium 50%: {context['equilibrium']}")
    print(f"Current zone: {context['zone']}")

    print("\n===== РАЗРЕШЕНИЕ =====")

    if (
        context["trend"] == "BULLISH"
        and context["zone"] == "DISCOUNT"
    ):
        print("✅ Разрешены Bullish Order Blocks")

    elif (
        context["trend"] == "BEARISH"
        and context["zone"] == "PREMIUM"
    ):
        print("✅ Разрешены Bearish Order Blocks")

    else:
        print("⛔ Сейчас подходящего H1-контекста нет")


def main():
    if not connect_mt5():
        raise SystemExit

    try:
        rates = get_rates(
            SYMBOL,
            mt5.TIMEFRAME_H1,
            H1_CANDLES,
        )

        if rates is None:
            raise SystemExit

        context = detect_h1_context(rates)

        if context is None:
            print("❌ Не удалось определить H1-контекст")
            return

        print_h1_context(context)

    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()