import MetaTrader5 as mt5
from datetime import datetime
from typing import Any, Optional

from market_data import connect_mt5, get_rates
from config import SYMBOL, H4_CANDLES

from fvg import (
    has_bullish_fvg,
    has_bearish_fvg,
)


# Максимальный возраст блока.
MAX_OB_AGE = 120

# Минимальный импульс относительно размера OB.
MIN_IMPULSE_RATIO = 2.0

# Сколько свечей после OB проверяем на импульс и BOS.
IMPULSE_LOOKAHEAD = 4

# Сколько прошлых свечей формируют уровень структуры.
STRUCTURE_LOOKBACK = 20


def get_pip_size(symbol: Optional[str] = None) -> float:
    """
    Размер одного pip для разных групп инструментов.

    Параметр symbol сделан необязательным, чтобы старые вызовы
    функций продолжали работать.
    """
    symbol_name = (symbol or SYMBOL).upper()

    if "JPY" in symbol_name:
        return 0.01

    if any(
        name in symbol_name
        for name in (
            "XAU",
            "GOLD",
        )
    ):
        return 0.10

    if any(
        name in symbol_name
        for name in (
            "NAS",
            "US100",
            "USTEC",
            "GER",
            "DE40",
            "DAX",
        )
    ):
        return 1.0

    return 0.0001


def price_to_pips(
    price_difference: float,
    symbol: Optional[str] = None,
) -> float:
    pip_size = get_pip_size(symbol)

    if pip_size <= 0:
        return 0.0

    return abs(float(price_difference)) / pip_size


def calculate_score(
    impulse_ratio: float,
    fresh: bool,
    age: int,
    range_pips: float,
    bos_confirmed: bool,
    fvg_confirmed: bool,
) -> int:

    score = 0

    # BOS обязателен
    if bos_confirmed:
        score += 25

    # Импульс
    if impulse_ratio >= 2.0:
        score += 20
    elif impulse_ratio >= 1.5:
        score += 10

    if impulse_ratio >= 3.0:
        score += 10

    if impulse_ratio >= 4.0:
        score += 5

    # Свежесть
    if fresh:
        score += 20

    # FVG — только бонус
    if fvg_confirmed:
        score += 10

    # Возраст
    if age <= 20:
        score += 10
    elif age <= 40:
        score += 5

    # Размер блока
    if 8 <= range_pips <= 60:
        score += 10
    elif range_pips > 120:
        score -= 15

    return max(0, min(score, 100))


def find_previous_high(
    rates,
    index: int,
) -> Optional[float]:
    start = max(0, index - STRUCTURE_LOOKBACK)
    previous_candles = rates[start:index]

    if len(previous_candles) == 0:
        return None

    return float(
        max(
            candle["high"]
            for candle in previous_candles
        )
    )


def find_previous_low(
    rates,
    index: int,
) -> Optional[float]:
    start = max(0, index - STRUCTURE_LOOKBACK)
    previous_candles = rates[start:index]

    if len(previous_candles) == 0:
        return None

    return float(
        min(
            candle["low"]
            for candle in previous_candles
        )
    )


def find_bullish_bos(
    rates,
    ob_index: int,
    structure_high: float,
) -> tuple[bool, Optional[int], Optional[float]]:

    end = min(
        len(rates),
        ob_index + 1 + IMPULSE_LOOKAHEAD,
    )

    ob_low = float(rates[ob_index]["low"])
    ob_range = structure_high - ob_low

    MIN_BOS_BREAK_RATIO = 0.15

    for index in range(ob_index + 1, end):
        close_price = float(rates[index]["close"])

        break_distance = close_price - structure_high

        if break_distance >= ob_range * MIN_BOS_BREAK_RATIO:
            return True, index, close_price

    return False, None, None


def find_bearish_bos(
    rates,
    ob_index: int,
    structure_low: float,
) -> tuple[bool, Optional[int], Optional[float]]:

    end = min(
        len(rates),
        ob_index + 1 + IMPULSE_LOOKAHEAD,
    )

    ob_high = float(rates[ob_index]["high"])
    ob_range = ob_high - structure_low

    MIN_BOS_BREAK_RATIO = 0.15

    for index in range(ob_index + 1, end):
        close_price = float(rates[index]["close"])

        break_distance = structure_low - close_price

        if break_distance >= ob_range * MIN_BOS_BREAK_RATIO:
            return True, index, close_price

    return False, None, None

def bullish_block_was_mitigated(
    rates,
    ob_index: int,
    bos_index: int,
    ob_high: float,
    ob_low: float,
) -> tuple[bool, int]:
    """
    Проверяем касание OB только после формирования BOS.

    Свечи самого импульса не считаются митигейтом.
    """
    mitigation_count = 0

    for candle in rates[bos_index + 1:]:
        candle_low = float(candle["low"])
        candle_high = float(candle["high"])

        zone_touched = (
            candle_low <= ob_high
            and candle_high >= ob_low
        )

        if zone_touched:
            mitigation_count += 1

    return mitigation_count > 0, mitigation_count


def bearish_block_was_mitigated(
    rates,
    ob_index: int,
    bos_index: int,
    ob_high: float,
    ob_low: float,
) -> tuple[bool, int]:
    mitigation_count = 0

    for candle in rates[bos_index + 1:]:
        candle_low = float(candle["low"])
        candle_high = float(candle["high"])

        zone_touched = (
            candle_high >= ob_low
            and candle_low <= ob_high
        )

        if zone_touched:
            mitigation_count += 1

    return mitigation_count > 0, mitigation_count


def find_all_bullish_order_blocks(
    rates,
    symbol: Optional[str] = None,
) -> list[dict[str, Any]]:
    order_blocks: list[dict[str, Any]] = []

    minimum_bars = (
        STRUCTURE_LOOKBACK
        + IMPULSE_LOOKAHEAD
        + 1
    )

    if rates is None or len(rates) < minimum_bars:
        return order_blocks

    last_possible_index = (
        len(rates)
        - IMPULSE_LOOKAHEAD
    )

    for i in range(
        STRUCTURE_LOOKBACK,
        last_possible_index,
    ):
        candle = rates[i]

        open_price = float(candle["open"])
        close_price = float(candle["close"])
        ob_high = float(candle["high"])
        ob_low = float(candle["low"])

        # Bullish OB — последняя медвежья свеча
        # перед бычьим displacement.
        if close_price >= open_price:
            continue

        ob_range = ob_high - ob_low

        ob_range = ob_high - ob_low

        if ob_range <= 0:
            continue

        body = abs(close_price - open_price)
        body_ratio = body / ob_range

        MIN_BODY_RATIO = 0.60

        if body_ratio < MIN_BODY_RATIO:
             continue

        if ob_range <= 0:
            continue

        previous_high = find_previous_high(
            rates,
            i,
        )

        if previous_high is None:
            continue

        (
            bos_confirmed,
            bos_index,
            bos_close,
        ) = find_bullish_bos(
            rates,
            i,
            previous_high,
        )

        # BOS остаётся обязательным.
        if not bos_confirmed:
            continue

        if bos_index is None or bos_close is None:
            continue
        
        MAX_BARS_TO_BOS = 5

        bars_to_bos = bos_index - i

        if bars_to_bos > MAX_BARS_TO_BOS:
         continue

        impulse_move = bos_close - ob_high
        impulse_ratio = impulse_move / ob_range

        if impulse_ratio < MIN_IMPULSE_RATIO:
            continue

        # FVG теперь только дополнительный плюс.
        fvg_confirmed = bool(
            has_bullish_fvg(rates, i)
        )

        mitigated, mitigation_count = (
            bullish_block_was_mitigated(
                rates=rates,
                ob_index=i,
                bos_index=bos_index,
                ob_high=ob_high,
                ob_low=ob_low,
            )
        )

        age = len(rates) - 1 - i

        if age > MAX_OB_AGE:
            continue

        fresh = not mitigated

        range_pips = price_to_pips(
            ob_range,
            symbol,
        )

        score = calculate_score(
            impulse_ratio=impulse_ratio,
            fresh=fresh,
            age=age,
            range_pips=range_pips,
            bos_confirmed=bos_confirmed,
            fvg_confirmed=fvg_confirmed,
        )

        order_blocks.append(
            {
                "type": "BULLISH",
                "time": int(candle["time"]),
                "time_text": datetime.fromtimestamp(
                    int(candle["time"])
                ).strftime("%Y-%m-%d %H:%M:%S"),

                "high": ob_high,
                "low": ob_low,

                # Зона для лимитного входа.
                "proximal": ob_high,
                "distal": ob_low,
                "midpoint": (
                    ob_high + ob_low
                ) / 2.0,

                "range_pips": round(
                    range_pips,
                    2,
                ),
                "impulse_ratio": round(
                    impulse_ratio,
                    2,
                ),

                "bos": True,
                "bos_index": bos_index,
                "bos_time": int(
                    rates[bos_index]["time"]
                ),
                "fvg": fvg_confirmed,
                "broken_level": previous_high,

                "fresh": fresh,
                "mitigated": mitigated,
                "mitigation_count": (
                    mitigation_count
                ),

                "age": age,
                "score": score,
            }
        )

    return order_blocks


def find_all_bearish_order_blocks(
    rates,
    symbol: Optional[str] = None,
) -> list[dict[str, Any]]:
    order_blocks: list[dict[str, Any]] = []

    minimum_bars = (
        STRUCTURE_LOOKBACK
        + IMPULSE_LOOKAHEAD
        + 1
    )

    if rates is None or len(rates) < minimum_bars:
        return order_blocks

    last_possible_index = (
        len(rates)
        - IMPULSE_LOOKAHEAD
    )

    for i in range(
        STRUCTURE_LOOKBACK,
        last_possible_index,
    ):
        candle = rates[i]

        open_price = float(candle["open"])
        close_price = float(candle["close"])
        ob_high = float(candle["high"])
        ob_low = float(candle["low"])

        # Bearish OB — последняя бычья свеча
        # перед медвежьим displacement.
        if close_price <= open_price:
            continue

        ob_range = ob_high - ob_low

        if ob_range <= 0:
         continue

        body = abs(close_price - open_price)
        body_ratio = body / ob_range

        MIN_BODY_RATIO = 0.60

        if body_ratio < MIN_BODY_RATIO:
                continue

        previous_low = find_previous_low(
            rates,
            i,
        )

        if previous_low is None:
            continue

        (
            bos_confirmed,
            bos_index,
            bos_close,
        ) = find_bearish_bos(
            rates,
            i,
            previous_low,
        )

        if not bos_confirmed:
            continue

        if bos_index is None or bos_close is None:
            continue

        impulse_move = ob_low - bos_close
        impulse_ratio = impulse_move / ob_range

        if impulse_ratio < MIN_IMPULSE_RATIO:
            continue

        fvg_confirmed = bool(
            has_bearish_fvg(rates, i)
        )

        mitigated, mitigation_count = (
            bearish_block_was_mitigated(
                rates=rates,
                ob_index=i,
                bos_index=bos_index,
                ob_high=ob_high,
                ob_low=ob_low,
            )
        )

        age = len(rates) - 1 - i

        if age > MAX_OB_AGE:
            continue

        fresh = not mitigated

        range_pips = price_to_pips(
            ob_range,
            symbol,
        )

        score = calculate_score(
            impulse_ratio=impulse_ratio,
            fresh=fresh,
            age=age,
            range_pips=range_pips,
            bos_confirmed=bos_confirmed,
            fvg_confirmed=fvg_confirmed,
        )

        order_blocks.append(
            {
                "type": "BEARISH",
                "time": int(candle["time"]),
                "time_text": datetime.fromtimestamp(
                    int(candle["time"])
                ).strftime("%Y-%m-%d %H:%M:%S"),

                "high": ob_high,
                "low": ob_low,

                # Зона для лимитного входа.
                "proximal": ob_low,
                "distal": ob_high,
                "midpoint": (
                    ob_high + ob_low
                ) / 2.0,

                "range_pips": round(
                    range_pips,
                    2,
                ),
                "impulse_ratio": round(
                    impulse_ratio,
                    2,
                ),

                "bos": True,
                "bos_index": bos_index,
                "bos_time": int(
                    rates[bos_index]["time"]
                ),
                "fvg": fvg_confirmed,
                "broken_level": previous_low,

                "fresh": fresh,
                "mitigated": mitigated,
                "mitigation_count": (
                    mitigation_count
                ),

                "age": age,
                "score": score,
            }
        )

    return order_blocks


def print_order_block(
    title: str,
    ob: dict[str, Any],
) -> None:
    print(f"\n===== {title} =====")
    print(f"Type: {ob['type']}")
    print(f"Time: {ob['time_text']}")
    print(f"High: {ob['high']}")
    print(f"Low: {ob['low']}")
    print(f"Proximal: {ob['proximal']}")
    print(f"Distal: {ob['distal']}")
    print(f"Midpoint: {ob['midpoint']}")
    print(f"Range: {ob['range_pips']} pips")
    print(
        f"Impulse ratio: "
        f"{ob['impulse_ratio']}"
    )
    print(f"BOS confirmed: {ob['bos']}")
    print(f"FVG bonus: {ob['fvg']}")
    print(
        f"Broken level: "
        f"{ob['broken_level']}"
    )
    print(f"Fresh: {ob['fresh']}")
    print(f"Mitigated: {ob['mitigated']}")
    print(
        f"Mitigation count: "
        f"{ob['mitigation_count']}"
    )
    print(f"Age: {ob['age']} candles")
    print(f"Score: {ob['score']}/100")


def main() -> None:
    if not connect_mt5():
        raise SystemExit

    try:
        rates = get_rates(
            SYMBOL,
            mt5.TIMEFRAME_H4,
            H4_CANDLES,
        )

        if rates is None:
            raise SystemExit

        bullish_obs = (
            find_all_bullish_order_blocks(
                rates,
                SYMBOL,
            )
        )

        bearish_obs = (
            find_all_bearish_order_blocks(
                rates,
                SYMBOL,
            )
        )

        fresh_bullish = [
            ob
            for ob in bullish_obs
            if ob["fresh"]
        ]

        fresh_bearish = [
            ob
            for ob in bearish_obs
            if ob["fresh"]
        ]

        print(
            f"\nBullish OB: "
            f"{len(bullish_obs)}"
        )
        print(
            f"Свежих Bullish OB: "
            f"{len(fresh_bullish)}"
        )

        print(
            f"\nBearish OB: "
            f"{len(bearish_obs)}"
        )
        print(
            f"Свежих Bearish OB: "
            f"{len(fresh_bearish)}"
        )

        if fresh_bullish:
            best_bullish = max(
                fresh_bullish,
                key=lambda ob: ob["score"],
            )

            print_order_block(
                "ЛУЧШИЙ BULLISH ORDER BLOCK",
                best_bullish,
            )
        else:
            print(
                "\nСвежих Bullish OB не найдено"
            )

        if fresh_bearish:
            best_bearish = max(
                fresh_bearish,
                key=lambda ob: ob["score"],
            )

            print_order_block(
                "ЛУЧШИЙ BEARISH ORDER BLOCK",
                best_bearish,
            )
        else:
            print(
                "\nСвежих Bearish OB не найдено"
            )

    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()