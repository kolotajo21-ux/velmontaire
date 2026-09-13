from structure import find_swings


def detect_liquidity_sweep(
    rates,
    trend,
    swing_length=2,
):
    swing_highs, swing_lows = find_swings(
        rates,
        swing_length,
    )

    if not swing_highs or not swing_lows:
        return None

    last_candle = rates[-2]

    last_high = float(last_candle["high"])
    last_low = float(last_candle["low"])
    last_close = float(last_candle["close"])
    last_time = int(last_candle["time"])

    last_swing_high = swing_highs[-1]
    last_swing_low = swing_lows[-1]

    # Для продажи:
    # цена сняла предыдущий High тенью,
    # но закрылась обратно ниже уровня
    if trend == "BEARISH":
        swept_level = float(
            last_swing_high["price"]
        )

        if (
            last_high > swept_level
            and last_close < swept_level
        ):
            return {
                "type": "BUY_SIDE_SWEEP",
                "direction": "BEARISH",
                "swept_level": swept_level,
                "extreme": last_high,
                "close": last_close,
                "time": last_time,
            }

    # Для покупки:
    # цена сняла предыдущий Low тенью,
    # но закрылась обратно выше уровня
    if trend == "BULLISH":
        swept_level = float(
            last_swing_low["price"]
        )

        if (
            last_low < swept_level
            and last_close > swept_level
        ):
            return {
                "type": "SELL_SIDE_SWEEP",
                "direction": "BULLISH",
                "swept_level": swept_level,
                "extreme": last_low,
                "close": last_close,
                "time": last_time,
            }

    return None