def find_candle_index_by_time(rates, candle_time):
    for index, candle in enumerate(rates):
        if int(candle["time"]) == int(candle_time):
            return index

    return None


def find_m5_order_block(rates, direction, choch_time, bos_time):
    choch_index = find_candle_index_by_time(rates, choch_time)
    bos_index = find_candle_index_by_time(rates, bos_time)

    if choch_index is None or bos_index is None:
        return None

    if bos_index <= choch_index:
        return None

    # Ищем последнюю противоположную свечу перед BOS
    for index in range(bos_index - 1, choch_index - 1, -1):
        candle = rates[index]

        open_price = float(candle["open"])
        close_price = float(candle["close"])

        if direction == "BULLISH":
            # Для покупки ищем последнюю медвежью свечу
            if close_price < open_price:
                return {
                    "type": "BULLISH_OB",
                    "index": index,
                    "time": int(candle["time"]),
                    "high": float(candle["high"]),
                    "low": float(candle["low"]),
                }

        elif direction == "BEARISH":
            # Для продажи ищем последнюю бычью свечу
            if close_price > open_price:
                return {
                    "type": "BEARISH_OB",
                    "index": index,
                    "time": int(candle["time"]),
                    "high": float(candle["high"]),
                    "low": float(candle["low"]),
                }

    return None


def calculate_trade_levels(
    direction,
    order_block,
    sweep,
    rr=3.0,
    buffer_price=0.00010,
):
    if order_block is None or sweep is None:
        return None

    ob_high = float(order_block["high"])
    ob_low = float(order_block["low"])

    # Вход на 50% M5 Order Block
    entry = (ob_high + ob_low) / 2

    if direction == "BULLISH":
        stop_loss = float(sweep["extreme"]) - buffer_price

        if stop_loss >= entry:
            return None

        risk_distance = entry - stop_loss
        take_profit = entry + (risk_distance * rr)

        order_type = "BUY_LIMIT"

    elif direction == "BEARISH":
        stop_loss = float(sweep["extreme"]) + buffer_price

        if stop_loss <= entry:
            return None

        risk_distance = stop_loss - entry
        take_profit = entry - (risk_distance * rr)

        order_type = "SELL_LIMIT"

    else:
        return None

    if risk_distance <= 0:
        return None

    return {
        "order_type": order_type,
        "direction": direction,
        "entry": round(entry, 5),
        "stop_loss": round(stop_loss, 5),
        "take_profit": round(take_profit, 5),
        "risk_distance": risk_distance,
        "rr": rr,
        "order_block": order_block,
    }