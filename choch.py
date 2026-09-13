from structure import find_swings


def detect_choch(rates, trend, swing_length=2):
    swing_highs, swing_lows = find_swings(
        rates,
        swing_length,
    )

    if not swing_highs or not swing_lows:
        return None

    last_close = float(rates[-2]["close"])
    last_time = int(rates[-2]["time"])

    last_swing_high = swing_highs[-1]
    last_swing_low = swing_lows[-1]

    if (
        trend == "BEARISH"
        and last_close > last_swing_high["price"]
    ):
        return {
            "type": "BULLISH_CHOCH",
            "direction": "BULLISH",
            "broken_level": last_swing_high["price"],
            "close": last_close,
            "time": last_time,
        }

    if (
        trend == "BULLISH"
        and last_close < last_swing_low["price"]
    ):
        return {
            "type": "BEARISH_CHOCH",
            "direction": "BEARISH",
            "broken_level": last_swing_low["price"],
            "close": last_close,
            "time": last_time,
        }

    return None