from structure import find_swings


MIN_BOS_BODY_RATIO = 0.45
MIN_BOS_BREAK_RATIO = 0.10


def find_candle_index_by_time(
    rates,
    candle_time,
):
    target_time = int(candle_time)

    for index, candle in enumerate(rates):
        if int(candle["time"]) == target_time:
            return index

    return None


def detect_bos_after_choch(
    rates,
    direction,
    choch_time,
    swing_length=2,
):
    """
    Ищет первый подтверждённый BOS после CHOCH.

    BULLISH:
    CHOCH вверх -> откат -> Swing Low ->
    закрытие бычьей свечи выше локального High.

    BEARISH:
    CHOCH вниз -> откат -> Swing High ->
    закрытие медвежьей свечи ниже локального Low.

    Последняя свеча rates не используется,
    потому что она может быть ещё не закрыта.
    """

    if rates is None or len(rates) < 7:
        return None

    direction = str(direction).upper()

    if direction not in {
        "BULLISH",
        "BEARISH",
    }:
        return None

    # Исключаем текущую незакрытую свечу.
    closed_rates = rates[:-1]

    choch_index = find_candle_index_by_time(
        closed_rates,
        choch_time,
    )

    if choch_index is None:
        return None

    # Свеча CHOCH не должна участвовать
    # в поиске отката после самой себя.
    search_start_index = choch_index + 1

    if (
        len(closed_rates)
        - search_start_index
        < swing_length * 2 + 1
    ):
        return None

    rates_after_choch = closed_rates[
        search_start_index:
    ]

    swing_highs, swing_lows = find_swings(
        rates_after_choch,
        swing_length,
    )

    if direction == "BULLISH":
        return _detect_bullish_bos(
            closed_rates=closed_rates,
            choch_index=choch_index,
            search_start_index=search_start_index,
            swing_lows=swing_lows,
        )

    return _detect_bearish_bos(
        closed_rates=closed_rates,
        choch_index=choch_index,
        search_start_index=search_start_index,
        swing_highs=swing_highs,
    )


def _detect_bullish_bos(
    closed_rates,
    choch_index,
    search_start_index,
    swing_lows,
):
    if not swing_lows:
        return None

    # Первый подтверждённый Swing Low после CHOCH.
    pullback_low = swing_lows[0]

    pullback_index = (
        search_start_index
        + int(pullback_low["index"])
    )

    if pullback_index <= choch_index:
        return None

    # Ищем максимум импульса от CHOCH
    # до начала подтверждённого отката.
    impulse_candles = closed_rates[
        choch_index:pullback_index
    ]

    if len(impulse_candles) == 0:
        return None

    bos_level = max(
        float(candle["high"])
        for candle in impulse_candles
    )

    for index in range(
        pullback_index + 1,
        len(closed_rates),
    ):
        candle = closed_rates[index]
        previous_candle = closed_rates[index - 1]

        open_price = float(candle["open"])
        high = float(candle["high"])
        low = float(candle["low"])
        close = float(candle["close"])

        previous_close = float(
            previous_candle["close"]
        )

        candle_range = high - low

        if candle_range <= 0:
            continue

        # BOS вверх должна подтверждать
        # именно бычья свеча.
        if close <= open_price:
            continue

        body_ratio = (
            abs(close - open_price)
            / candle_range
        )

        break_distance = close - bos_level
        break_ratio = (
            break_distance
            / candle_range
        )

        # Проверяем именно первое пересечение:
        # раньше цена была ниже/на уровне,
        # теперь закрылась выше.
        crossed_level = (
            previous_close <= bos_level
            and close > bos_level
        )

        if (
            crossed_level
            and body_ratio
            >= MIN_BOS_BODY_RATIO
            and break_ratio
            >= MIN_BOS_BREAK_RATIO
        ):
            bos_time = int(candle["time"])

            return {
                "event_id": (
                    f"BULLISH_BOS_"
                    f"{bos_time}_"
                    f"{bos_level:.10f}"
                ),
                "type": "BULLISH_BOS",
                "direction": "BULLISH",
                "broken_level": float(
                    bos_level
                ),
                "close": close,
                "time": bos_time,
                "index": index,
                "choch_index": choch_index,
                "pullback_index": (
                    pullback_index
                ),
                "pullback_extreme": float(
                    closed_rates[
                        pullback_index
                    ]["low"]
                ),
                "body_ratio": float(
                    body_ratio
                ),
                "break_ratio": float(
                    break_ratio
                ),
            }

    return None


def _detect_bearish_bos(
    closed_rates,
    choch_index,
    search_start_index,
    swing_highs,
):
    if not swing_highs:
        return None

    # Первый подтверждённый Swing High после CHOCH.
    pullback_high = swing_highs[0]

    pullback_index = (
        search_start_index
        + int(pullback_high["index"])
    )

    if pullback_index <= choch_index:
        return None

    # Ищем минимум импульса от CHOCH
    # до начала подтверждённого отката.
    impulse_candles = closed_rates[
        choch_index:pullback_index
    ]

    if len(impulse_candles) == 0:
        return None

    bos_level = min(
        float(candle["low"])
        for candle in impulse_candles
    )

    for index in range(
        pullback_index + 1,
        len(closed_rates),
    ):
        candle = closed_rates[index]
        previous_candle = closed_rates[index - 1]

        open_price = float(candle["open"])
        high = float(candle["high"])
        low = float(candle["low"])
        close = float(candle["close"])

        previous_close = float(
            previous_candle["close"]
        )

        candle_range = high - low

        if candle_range <= 0:
            continue

        # BOS вниз должна подтверждать
        # именно медвежья свеча.
        if close >= open_price:
            continue

        body_ratio = (
            abs(close - open_price)
            / candle_range
        )

        break_distance = bos_level - close
        break_ratio = (
            break_distance
            / candle_range
        )

        # Первое закрытие ниже уровня.
        crossed_level = (
            previous_close >= bos_level
            and close < bos_level
        )

        if (
            crossed_level
            and body_ratio
            >= MIN_BOS_BODY_RATIO
            and break_ratio
            >= MIN_BOS_BREAK_RATIO
        ):
            bos_time = int(candle["time"])

            return {
                "event_id": (
                    f"BEARISH_BOS_"
                    f"{bos_time}_"
                    f"{bos_level:.10f}"
                ),
                "type": "BEARISH_BOS",
                "direction": "BEARISH",
                "broken_level": float(
                    bos_level
                ),
                "close": close,
                "time": bos_time,
                "index": index,
                "choch_index": choch_index,
                "pullback_index": (
                    pullback_index
                ),
                "pullback_extreme": float(
                    closed_rates[
                        pullback_index
                    ]["high"]
                ),
                "body_ratio": float(
                    body_ratio
                ),
                "break_ratio": float(
                    break_ratio
                ),
            }

    return None