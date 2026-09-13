def has_bullish_fvg(rates, index):
    first_candle = rates[index + 1]
    third_candle = rates[index + 3]

    return (
        float(third_candle["low"])
        > float(first_candle["high"])
    )


def has_bearish_fvg(rates, index):
    first_candle = rates[index + 1]
    third_candle = rates[index + 3]

    return (
        float(third_candle["high"])
        < float(first_candle["low"])
    )