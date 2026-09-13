from typing import Any


def is_swing_high(rates: Any, index: int, length: int) -> bool:
    current_high = rates[index]["high"]

    for i in range(index - length, index + length + 1):
        if i == index:
            continue

        if rates[i]["high"] >= current_high:
            return False

    return True


def is_swing_low(rates: Any, index: int, length: int) -> bool:
    current_low = rates[index]["low"]

    for i in range(index - length, index + length + 1):
        if i == index:
            continue

        if rates[i]["low"] <= current_low:
            return False

    return True


def find_swings(rates: Any, length: int) -> tuple[list[dict], list[dict]]:
    swing_highs = []
    swing_lows = []

    for index in range(length, len(rates) - length):
        candle_time = int(rates[index]["time"])

        if is_swing_high(rates, index, length):
            swing_highs.append(
                {
                    "index": index,
                    "time": candle_time,
                    "price": float(rates[index]["high"]),
                }
            )

        if is_swing_low(rates, index, length):
            swing_lows.append(
                {
                    "index": index,
                    "time": candle_time,
                    "price": float(rates[index]["low"]),
                }
            )

    return swing_highs, swing_lows


def detect_structure(
    rates: Any,
    swing_highs: list[dict],
    swing_lows: list[dict],
) -> dict:
    if len(rates) < 2:
        raise ValueError("Недостаточно свечей для анализа структуры")

    last_closed_index = len(rates) - 2
    last_close = float(rates[last_closed_index]["close"])

    valid_highs = [
        swing for swing in swing_highs
        if swing["index"] < last_closed_index
    ]

    valid_lows = [
        swing for swing in swing_lows
        if swing["index"] < last_closed_index
    ]

    last_swing_high = valid_highs[-1] if valid_highs else None
    last_swing_low = valid_lows[-1] if valid_lows else None

    bos = "NONE"
    trend = "RANGE"
    broken_level = None

    if last_swing_high and last_close > last_swing_high["price"]:
        bos = "UP"
        trend = "BULLISH"
        broken_level = last_swing_high["price"]

    elif last_swing_low and last_close < last_swing_low["price"]:
        bos = "DOWN"
        trend = "BEARISH"
        broken_level = last_swing_low["price"]

    return {
        "last_close": last_close,
        "bos": bos,
        "trend": trend,
        "broken_level": broken_level,
        "last_swing_high": last_swing_high,
        "last_swing_low": last_swing_low,
    }