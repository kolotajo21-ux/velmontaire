from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from structure import (
    StructureEngine,
    build_structure_snapshot,
    normalize_direction,
)


VALID_DIRECTIONS = {
    "BULLISH",
    "BEARISH",
}

VALID_EVENTS = {
    "WAIT",
    "SIGNAL",
    "NO_SIGNAL",
    "REJECTED",
    "ERROR",
}


@dataclass(slots=True)
class StrategyResult:
    event: str
    direction: str | None = None
    reason: str = ""

    higher_timeframe_structure: dict[str, Any] | None = None
    h4_order_block: dict[str, Any] | None = None

    liquidity_sweep: dict[str, Any] | None = None
    internal_choch: dict[str, Any] | None = None
    internal_bos: dict[str, Any] | None = None

    trade: dict[str, Any] | None = None

    diagnostics: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "direction": self.direction,
            "reason": self.reason,

            "higher_timeframe_structure": (
                self.higher_timeframe_structure
            ),

            "h4_order_block": (
                self.h4_order_block
            ),

            "liquidity_sweep": (
                self.liquidity_sweep
            ),

            "internal_choch": (
                self.internal_choch
            ),

            "internal_bos": (
                self.internal_bos
            ),

            "trade": self.trade,

            "diagnostics": dict(
                self.diagnostics
            ),
        }


@dataclass(slots=True)
class StrategyConfig:
    higher_timeframe_swing_length: int = 3
    signal_timeframe_swing_length: int = 2
    internal_swing_length: int = 2

    minimum_structure_body_ratio: float = 0.45
    minimum_structure_range_atr: float = 0.70
    minimum_close_beyond_atr: float = 0.03

    order_block_search_bars: int = 12
    maximum_bars_to_bos: int = 6
    maximum_order_block_age: int = 120

    minimum_bos_body_ratio: float = 0.45
    minimum_order_block_body_ratio: float = 0.20

    minimum_displacement_ratio: float = 1.15
    preferred_displacement_ratio: float = 1.50

    require_fvg: bool = False
    allow_fvg_bonus: bool = True

    minimum_order_block_score: float = 60.0

    sweep_lookback: int = 20
    minimum_sweep_atr: float = 0.02

    minimum_rr: float = 2.0
    preferred_rr: float = 3.0
    maximum_rr: float = 3.5

    stop_buffer_atr: float = 0.05

    use_last_closed_candle: bool = True

    # Название стратегии
    strategy_name: str = "SMC X PRIME"

    # Минимальное количество свечей
    minimum_d1_candles: int = 80
    minimum_h4_candles: int = 200
    minimum_m5_candles: int = 300

    # Поиск ликвидности
    liquidity_lookback: int = 20
    internal_search_bars: int = 120

    require_liquidity_reclaim: bool = True
    require_directional_sweep_close: bool = True

    minimum_sweep_ratio: float = 0.10

    # M5 Order Block
    m5_order_block_search_bars: int = 12
    maximum_m5_bars_to_bos: int = 6
    minimum_m5_order_block_body_ratio: float = 0.20

    # Вход
    entry_mode: str = "PROXIMAL"      # PROXIMAL / MIDPOINT / DISTAL
    stop_buffer_fraction: float = 0.05

    # Динамический TP
    target_liquidity_lookback: int = 40

    # D1 Blocker
    daily_blocker_lookback: int = 30
    minimum_daily_room_r: float = 2.0

    # Таймфреймы
    higher_timeframe: str = "D1"
    zone_timeframe: str = "H4"
    entry_timeframe: str = "M5"

    # Длительность одной M5 свечи
    m5_timeframe_seconds: int = 300

def get_field(
    candle: Any,
    name: str,
    default: float = 0.0,
) -> float:
    try:
        return float(candle[name])
    except (
        KeyError,
        IndexError,
        TypeError,
        ValueError,
    ):
        return float(default)


def get_time(
    candle: Any,
) -> int:
    try:
        return int(candle["time"])
    except (
        KeyError,
        IndexError,
        TypeError,
        ValueError,
    ):
        return 0


def candle_body(
    candle: Any,
) -> float:
    return abs(
        get_field(candle, "close")
        - get_field(candle, "open")
    )


def candle_range(
    candle: Any,
) -> float:
    return max(
        0.0,
        get_field(candle, "high")
        - get_field(candle, "low"),
    )


def candle_body_ratio(
    candle: Any,
) -> float:
    total_range = candle_range(candle)

    if total_range <= 0:
        return 0.0

    return candle_body(candle) / total_range


def candle_direction(
    candle: Any,
) -> str:
    open_price = get_field(
        candle,
        "open",
    )

    close_price = get_field(
        candle,
        "close",
    )

    if close_price > open_price:
        return "BULLISH"

    if close_price < open_price:
        return "BEARISH"

    return "NEUTRAL"


def opposite_direction(
    direction: str,
) -> str:
    normalized = normalize_direction(
        direction
    )

    if normalized == "BULLISH":
        return "BEARISH"

    if normalized == "BEARISH":
        return "BULLISH"

    raise ValueError(
        f"Некорректное направление: {direction}"
    )
def safe_float(
    value: Any,
    default: float | None = None,
) -> float | None:
    """
    Безопасно преобразует значение в float.

    Если преобразование невозможно, возвращает default.
    """
    try:
        if value is None:
            return default

        return float(value)

    except (
        TypeError,
        ValueError,
        OverflowError,
    ):
        return default

def get_block_low(
    block: dict[str, Any],
) -> float:
    for key in (
        "low",
        "distal",
        "bottom",
        "zone_low",
    ):
        if key in block:
            return float(block[key])

    raise KeyError(
        "В Order Block отсутствует нижняя граница"
    )


def get_block_high(
    block: dict[str, Any],
) -> float:
    for key in (
        "high",
        "proximal",
        "top",
        "zone_high",
    ):
        if key in block:
            return float(block[key])

    raise KeyError(
        "В Order Block отсутствует верхняя граница"
    )


def calculate_true_range(
    rates: Any,
    index: int,
) -> float:
    if rates is None:
        return 0.0

    if index < 0 or index >= len(rates):
        return 0.0

    high = get_field(
        rates[index],
        "high",
    )

    low = get_field(
        rates[index],
        "low",
    )

    if index == 0:
        return max(
            0.0,
            high - low,
        )

    previous_close = get_field(
        rates[index - 1],
        "close",
    )

    return max(
        high - low,
        abs(high - previous_close),
        abs(low - previous_close),
    )


def calculate_atr(
    rates: Any,
    end_index: int,
    period: int = 14,
) -> float:
    if rates is None or len(rates) == 0:
        return 0.0

    end_index = min(
        max(0, int(end_index)),
        len(rates) - 1,
    )

    period = max(
        1,
        int(period),
    )

    start_index = max(
        0,
        end_index - period + 1,
    )

    values = [
        calculate_true_range(
            rates,
            index,
        )
        for index in range(
            start_index,
            end_index + 1,
        )
    ]

    values = [
        value
        for value in values
        if value > 0
    ]

    if not values:
        return 0.0

    return sum(values) / len(values)


def average(
    values: Iterable[float],
) -> float:
    values_list = [
        float(value)
        for value in values
    ]

    if not values_list:
        return 0.0

    return (
        sum(values_list)
        / len(values_list)
    )


def clamp(
    value: float,
    minimum: float,
    maximum: float,
) -> float:
    return max(
        float(minimum),
        min(
            float(maximum),
            float(value),
        ),
    )


def normalize_rr(
    rr: float,
    minimum_rr: float,
    maximum_rr: float,
) -> float:
    return clamp(
        value=float(rr),
        minimum=float(minimum_rr),
        maximum=float(maximum_rr),
    )


def order_block_is_valid(
    block: dict[str, Any],
) -> bool:
    try:
        low = get_block_low(block)
        high = get_block_high(block)
    except (
        KeyError,
        TypeError,
        ValueError,
    ):
        return False

    if high <= low:
        return False

    direction = normalize_direction(
        block.get("direction")
        or block.get("type")
    )

    return direction in VALID_DIRECTIONS


def order_block_contains_price(
    block: dict[str, Any],
    price: float,
) -> bool:
    if not order_block_is_valid(block):
        return False

    low = get_block_low(block)
    high = get_block_high(block)

    return low <= float(price) <= high


def order_block_was_mitigated(
    rates: Any,
    block: dict[str, Any],
    start_index: int,
    end_index: int | None = None,
) -> bool:
    if rates is None:
        return False

    if not order_block_is_valid(block):
        return False

    low = get_block_low(block)
    high = get_block_high(block)

    start_index = max(
        0,
        int(start_index),
    )

    if end_index is None:
        end_index = len(rates) - 1

    end_index = min(
        int(end_index),
        len(rates) - 1,
    )

    if start_index > end_index:
        return False

    for index in range(
        start_index,
        end_index + 1,
    ):
        candle_low = get_field(
            rates[index],
            "low",
        )

        candle_high = get_field(
            rates[index],
            "high",
        )

        if (
            candle_low <= high
            and candle_high >= low
        ):
            return True

    return False


def detect_fvg(
    rates: Any,
    index: int,
    direction: str,
) -> dict[str, Any] | None:
    normalized = normalize_direction(
        direction
    )

    if normalized is None:
        return None

    if rates is None:
        return None

    if index < 2 or index >= len(rates):
        return None

    first = rates[index - 2]
    third = rates[index]

    if normalized == "BULLISH":
        first_high = get_field(
            first,
            "high",
        )

        third_low = get_field(
            third,
            "low",
        )

        if third_low <= first_high:
            return None

        return {
            "direction": "BULLISH",
            "low": first_high,
            "high": third_low,
            "size": third_low - first_high,
            "start_index": index - 2,
            "end_index": index,
            "time": get_time(third),
        }

    first_low = get_field(
        first,
        "low",
    )

    third_high = get_field(
        third,
        "high",
    )

    if third_high >= first_low:
        return None

    return {
        "direction": "BEARISH",
        "low": third_high,
        "high": first_low,
        "size": first_low - third_high,
        "start_index": index - 2,
        "end_index": index,
        "time": get_time(third),
    }


def calculate_order_block_score(
    *,
    displacement_ratio: float,
    bars_to_bos: int,
    maximum_bars_to_bos: int,
    age: int,
    maximum_age: int,
    body_ratio: float,
    bos_body_ratio: float,
    fvg: bool,
) -> float:
    displacement_quality = clamp(
        (
            displacement_ratio - 1.0
        ) / 1.75,
        0.0,
        1.0,
    )

    proximity_quality = clamp(
        1.0
        - (
            max(0, bars_to_bos - 1)
            / max(
                1,
                maximum_bars_to_bos - 1,
            )
        ),
        0.0,
        1.0,
    )

    freshness_quality = clamp(
        1.0
        - (
            max(0, age)
            / max(1, maximum_age)
        ),
        0.0,
        1.0,
    )

    body_quality = clamp(
        body_ratio / 0.75,
        0.0,
        1.0,
    )

    bos_quality = clamp(
        bos_body_ratio / 0.75,
        0.0,
        1.0,
    )

    score = (
        displacement_quality * 30.0
        + proximity_quality * 20.0
        + freshness_quality * 20.0
        + body_quality * 15.0
        + bos_quality * 15.0
    )

    if fvg:
        score += 5.0

    return round(
        min(score, 100.0),
        2,
    )


def choose_best_order_block(
    blocks: list[dict[str, Any]],
    direction: str | None = None,
    minimum_score: float = 0.0,
) -> dict[str, Any] | None:
    normalized_direction = normalize_direction(
        direction
    )

    candidates: list[dict[str, Any]] = []

    for block in blocks:
        if not order_block_is_valid(block):
            continue

        block_direction = normalize_direction(
            block.get("direction")
            or block.get("type")
        )

        if (
            normalized_direction is not None
            and block_direction
            != normalized_direction
        ):
            continue

        score = float(
            block.get(
                "quality_score",
                block.get("score", 0.0),
            )
        )

        if score < float(minimum_score):
            continue

        candidates.append(
            dict(block)
        )

    if not candidates:
        return None

    candidates.sort(
        key=lambda block: (
            float(
                block.get(
                    "quality_score",
                    block.get(
                        "score",
                        0.0,
                    ),
                )
            ),
            -int(
                block.get(
                    "age",
                    0,
                )
            ),
            int(
                block.get(
                    "bos_time",
                    0,
                )
            ),
        ),
        reverse=True,
    )

    return candidates[0]


class StrategyEngine:
    """
    Центральный движок стратегии SMC X PRIME.

    Последовательность:

    1. Определить HTF-направление.
    2. Найти валидный H4 Order Block.
    3. Дождаться снятия ликвидности.
    4. Подтвердить внутренний CHOCH.
    5. Подтвердить внутренний BOS.
    6. Найти M5 Order Block.
    7. Рассчитать вход, SL и TP.
    """

    def __init__(
        self,
        config: StrategyConfig | None = None,
    ) -> None:
        self.config = (
            config
            if config is not None
            else StrategyConfig()
        )

        self.higher_timeframe_structure = (
            StructureEngine(
                swing_length=(
                    self.config
                    .higher_timeframe_swing_length
                ),
                minimum_body_ratio=(
                    self.config
                    .minimum_structure_body_ratio
                ),
                minimum_range_atr=(
                    self.config
                    .minimum_structure_range_atr
                ),
                minimum_close_beyond_atr=(
                    self.config
                    .minimum_close_beyond_atr
                ),
            )
        )

        self.signal_timeframe_structure = (
            StructureEngine(
                swing_length=(
                    self.config
                    .signal_timeframe_swing_length
                ),
                minimum_body_ratio=(
                    self.config
                    .minimum_structure_body_ratio
                ),
                minimum_range_atr=(
                    self.config
                    .minimum_structure_range_atr
                ),
                minimum_close_beyond_atr=(
                    self.config
                    .minimum_close_beyond_atr
                ),
            )
        )

        self.internal_structure = (
            StructureEngine(
                swing_length=(
                    self.config
                    .internal_swing_length
                ),
                minimum_body_ratio=(
                    self.config
                    .minimum_structure_body_ratio
                ),
                minimum_range_atr=(
                    self.config
                    .minimum_structure_range_atr
                ),
                minimum_close_beyond_atr=(
                    self.config
                    .minimum_close_beyond_atr
                ),
            )
        )

        self.used_bos_ids: set[
            tuple[str, int]
        ] = set()

        self.last_result: (
            StrategyResult | None
        ) = None

    def reset(self) -> None:
        self.higher_timeframe_structure.reset()
        self.signal_timeframe_structure.reset()
        self.internal_structure.reset()

        self.used_bos_ids.clear()
        self.last_result = None
    def _result(
        self,
        *,
        event: str,
        direction: str | None = None,
        reason: str = "",
        higher_timeframe_structure: (
            dict[str, Any] | None
        ) = None,
        h4_order_block: (
            dict[str, Any] | None
        ) = None,
        liquidity_sweep: (
            dict[str, Any] | None
        ) = None,
        internal_choch: (
            dict[str, Any] | None
        ) = None,
        internal_bos: (
            dict[str, Any] | None
        ) = None,
        trade: dict[str, Any] | None = None,
        diagnostics: (
            dict[str, Any] | None
        ) = None,
    ) -> StrategyResult:
        normalized_event = str(
            event
        ).upper()

        if normalized_event not in VALID_EVENTS:
            normalized_event = "ERROR"

        normalized_direction = (
            normalize_direction(direction)
        )

        result = StrategyResult(
            event=normalized_event,
            direction=normalized_direction,
            reason=str(reason),
            higher_timeframe_structure=(
                higher_timeframe_structure
            ),
            h4_order_block=h4_order_block,
            liquidity_sweep=liquidity_sweep,
            internal_choch=internal_choch,
            internal_bos=internal_bos,
            trade=trade,
            diagnostics=(
                diagnostics
                if diagnostics is not None
                else {}
            ),
        )

        self.last_result = result

        return result

    @staticmethod
    def _as_list(
        rates: Any,
    ) -> list[Any]:
        if rates is None:
            return []

        try:
            return list(rates)
        except TypeError:
            return []

    @staticmethod
    def _event_direction(
        event: dict[str, Any] | None,
    ) -> str | None:
        if not isinstance(
            event,
            dict,
        ):
            return None

        return normalize_direction(
            event.get("direction")
        )

    @staticmethod
    def _event_type(
        event: dict[str, Any] | None,
    ) -> str | None:
        if not isinstance(
            event,
            dict,
        ):
            return None

        value = (
            event.get("event_type")
            or event.get("type")
        )

        if value is None:
            return None

        normalized = str(value).upper()

        if normalized in {
            "BOS",
            "CHOCH",
        }:
            return normalized

        return None

    @staticmethod
    def _event_time(
        event: dict[str, Any] | None,
    ) -> int:
        if not isinstance(
            event,
            dict,
        ):
            return 0

        try:
            return int(
                event.get("time", 0)
            )
        except (
            TypeError,
            ValueError,
        ):
            return 0

    @staticmethod
    def _event_index(
        event: dict[str, Any] | None,
    ) -> int:
        if not isinstance(
            event,
            dict,
        ):
            return -1

        try:
            return int(
                event.get("index", -1)
            )
        except (
            TypeError,
            ValueError,
        ):
            return -1

    @staticmethod
    def _event_id(
        event: dict[str, Any] | None,
    ) -> str:
        if not isinstance(
            event,
            dict,
        ):
            return ""

        value = event.get("event_id")

        if value is not None:
            return str(value)

        event_type = str(
            event.get(
                "event_type",
                event.get("type", ""),
            )
        ).upper()

        direction = str(
            event.get("direction", "")
        ).upper()

        event_time = event.get(
            "time",
            0,
        )

        return (
            f"{event_type}:"
            f"{direction}:"
            f"{event_time}"
        )

    def _process_structure(
        self,
        *,
        engine: StructureEngine,
        rates: Any,
    ) -> tuple[
        dict[str, Any],
        list[dict[str, Any]],
    ]:
        candles = self._as_list(rates)

        if not candles:
            return (
                {
                    "trend": "RANGE",
                    "direction": "RANGE",
                    "last_event": None,
                    "last_bos": None,
                    "last_choch": None,
                    "events": [],
                },
                [],
            )

        events = engine.process(
            rates=candles,
            use_last_closed_candle=(
                self.config
                .use_last_closed_candle
            ),
        )

        normalized_events = [
            dict(event)
            for event in events
            if isinstance(event, dict)
        ]

        return (
            engine.snapshot(),
            normalized_events,
        )

    def _resolve_higher_timeframe_direction(
        self,
        snapshot: dict[str, Any],
    ) -> str | None:
        direction = normalize_direction(
            snapshot.get("trend")
            or snapshot.get("direction")
        )

        if direction in VALID_DIRECTIONS:
            return direction

        last_bos = snapshot.get(
            "last_bos"
        )

        bos_direction = (
            self._event_direction(
                last_bos
            )
        )

        if bos_direction in VALID_DIRECTIONS:
            return bos_direction

        last_choch = snapshot.get(
            "last_choch"
        )

        choch_direction = (
            self._event_direction(
                last_choch
            )
        )

        if choch_direction in VALID_DIRECTIONS:
            return choch_direction

        return None

    def _find_recent_structure_event(
        self,
        *,
        snapshot: dict[str, Any],
        direction: str,
        event_type: str,
        minimum_time: int = 0,
    ) -> dict[str, Any] | None:
        normalized_direction = (
            normalize_direction(direction)
        )

        normalized_event_type = str(
            event_type
        ).upper()

        if normalized_direction is None:
            return None

        if normalized_event_type not in {
            "BOS",
            "CHOCH",
        }:
            return None

        direct_key = (
            "last_bos"
            if normalized_event_type == "BOS"
            else "last_choch"
        )

        direct_event = snapshot.get(
            direct_key
        )

        if (
            self._event_type(direct_event)
            == normalized_event_type
            and self._event_direction(
                direct_event
            )
            == normalized_direction
            and self._event_time(
                direct_event
            )
            >= int(minimum_time)
        ):
            return dict(direct_event)

        history = snapshot.get(
            "events",
            [],
        )

        if not isinstance(
            history,
            list,
        ):
            return None

        for event in reversed(history):
            if not isinstance(
                event,
                dict,
            ):
                continue

            if (
                self._event_type(event)
                != normalized_event_type
            ):
                continue

            if (
                self._event_direction(event)
                != normalized_direction
            ):
                continue

            if (
                self._event_time(event)
                < int(minimum_time)
            ):
                continue

            return dict(event)

        return None

    def _candle_is_opposite(
        self,
        candle: Any,
        direction: str,
    ) -> bool:
        normalized = normalize_direction(
            direction
        )

        candle_side = candle_direction(
            candle
        )

        if normalized == "BULLISH":
            return candle_side == "BEARISH"

        if normalized == "BEARISH":
            return candle_side == "BULLISH"

        return False

    def _candle_matches_direction(
        self,
        candle: Any,
        direction: str,
    ) -> bool:
        normalized = normalize_direction(
            direction
        )

        return (
            normalized is not None
            and candle_direction(candle)
            == normalized
        )

    def _detect_displacement(
        self,
        *,
        rates: Any,
        start_index: int,
        end_index: int,
        direction: str,
    ) -> dict[str, Any]:
        candles = self._as_list(
            rates
        )

        normalized = normalize_direction(
            direction
        )

        if (
            normalized is None
            or not candles
        ):
            return {
                "confirmed": False,
                "ratio": 0.0,
                "average_body": 0.0,
                "impulse_body": 0.0,
                "direction": normalized,
            }

        start_index = max(
            0,
            int(start_index),
        )

        end_index = min(
            int(end_index),
            len(candles) - 1,
        )

        if start_index > end_index:
            return {
                "confirmed": False,
                "ratio": 0.0,
                "average_body": 0.0,
                "impulse_body": 0.0,
                "direction": normalized,
            }

        reference_start = max(
            0,
            start_index - 10,
        )

        reference_bodies = [
            candle_body(
                candles[index]
            )
            for index in range(
                reference_start,
                start_index,
            )
            if candle_body(
                candles[index]
            ) > 0
        ]

        average_body = average(
            reference_bodies
        )

        directional_bodies = [
            candle_body(
                candles[index]
            )
            for index in range(
                start_index,
                end_index + 1,
            )
            if self._candle_matches_direction(
                candles[index],
                normalized,
            )
        ]

        impulse_body = (
            sum(directional_bodies)
        )

        if average_body <= 0:
            average_body = average(
                candle_body(
                    candles[index]
                )
                for index in range(
                    start_index,
                    end_index + 1,
                )
            )

        if average_body <= 0:
            ratio = 0.0
        else:
            impulse_candle_count = max(
                1,
                len(directional_bodies),
            )

            ratio = (
                impulse_body
                / (
                    average_body
                    * impulse_candle_count
                )
            )

        return {
            "confirmed": (
                ratio
                >= self.config
                .minimum_displacement_ratio
            ),
            "preferred": (
                ratio
                >= self.config
                .preferred_displacement_ratio
            ),
            "ratio": float(ratio),
            "average_body": float(
                average_body
            ),
            "impulse_body": float(
                impulse_body
            ),
            "direction": normalized,
            "start_index": start_index,
            "end_index": end_index,
        }

    def _find_fvg_near_bos(
        self,
        *,
        rates: Any,
        bos_index: int,
        direction: str,
    ) -> dict[str, Any] | None:
        candles = self._as_list(
            rates
        )

        if not candles:
            return None

        normalized = normalize_direction(
            direction
        )

        if normalized is None:
            return None

        search_start = max(
            2,
            int(bos_index) - 2,
        )

        search_end = min(
            len(candles) - 1,
            int(bos_index) + 2,
        )

        for index in range(
            search_start,
            search_end + 1,
        ):
            fvg = detect_fvg(
                rates=candles,
                index=index,
                direction=normalized,
            )

            if fvg is not None:
                return fvg

        return None

    def _build_order_block(
        self,
        *,
        rates: Any,
        order_block_index: int,
        bos_event: dict[str, Any],
        direction: str,
        current_index: int,
    ) -> dict[str, Any] | None:
        candles = self._as_list(
            rates
        )

        normalized = normalize_direction(
            direction
        )

        if (
            normalized is None
            or not candles
            or order_block_index < 0
            or order_block_index
            >= len(candles)
        ):
            return None

        bos_index = self._event_index(
            bos_event
        )

        if bos_index < 0:
            return None

        candle = candles[
            order_block_index
        ]

        low = get_field(
            candle,
            "low",
        )

        high = get_field(
            candle,
            "high",
        )

        if high <= low:
            return None

        body_ratio = candle_body_ratio(
            candle
        )

        if (
            body_ratio
            < self.config
            .minimum_order_block_body_ratio
        ):
            return None

        bos_candle = candles[
            bos_index
        ]

        bos_body = candle_body_ratio(
            bos_candle
        )

        if (
            bos_body
            < self.config
            .minimum_bos_body_ratio
        ):
            return None

        bars_to_bos = (
            bos_index
            - order_block_index
        )

        if (
            bars_to_bos <= 0
            or bars_to_bos
            > self.config
            .maximum_bars_to_bos
        ):
            return None

        age = (
            int(current_index)
            - int(order_block_index)
        )

        if (
            age < 0
            or age
            > self.config
            .maximum_order_block_age
        ):
            return None

        displacement = (
            self._detect_displacement(
                rates=candles,
                start_index=(
                    order_block_index + 1
                ),
                end_index=bos_index,
                direction=normalized,
            )
        )

        if not displacement[
            "confirmed"
        ]:
            return None

        fvg = self._find_fvg_near_bos(
            rates=candles,
            bos_index=bos_index,
            direction=normalized,
        )

        if (
            self.config.require_fvg
            and fvg is None
        ):
            return None

        mitigated = (
            order_block_was_mitigated(
                rates=candles,
                block={
                    "direction": normalized,
                    "low": low,
                    "high": high,
                },
                start_index=bos_index + 1,
                end_index=current_index,
            )
        )

        if mitigated:
            return None

        quality_score = (
            calculate_order_block_score(
                displacement_ratio=float(
                    displacement["ratio"]
                ),
                bars_to_bos=bars_to_bos,
                maximum_bars_to_bos=(
                    self.config
                    .maximum_bars_to_bos
                ),
                age=age,
                maximum_age=(
                    self.config
                    .maximum_order_block_age
                ),
                body_ratio=body_ratio,
                bos_body_ratio=bos_body,
                fvg=(
                    fvg is not None
                    and self.config
                    .allow_fvg_bonus
                ),
            )
        )

        if (
            quality_score
            < self.config
            .minimum_order_block_score
        ):
            return None

        bos_time = self._event_time(
            bos_event
        )

        bos_id = (
            normalized,
            bos_time,
        )

        if bos_id in self.used_bos_ids:
            return None

        midpoint = (
            low + high
        ) / 2.0

        return {
            "direction": normalized,
            "type": normalized,

            "low": float(low),
            "high": float(high),

            "proximal": float(
                high
                if normalized == "BULLISH"
                else low
            ),
            "distal": float(
                low
                if normalized == "BULLISH"
                else high
            ),

            "midpoint": float(
                midpoint
            ),

            "time": get_time(
                candle
            ),

            "order_block_index": int(
                order_block_index
            ),

            "bos_index": int(
                bos_index
            ),
            "bos_time": int(
                bos_time
            ),
            "bos_event_id": self._event_id(
                bos_event
            ),
            "bos_level": float(
                bos_event.get(
                    "broken_level",
                    0.0,
                )
            ),

            "bars_to_bos": int(
                bars_to_bos
            ),
            "age": int(age),

            "fresh": True,
            "mitigated": False,

            "ob_body_ratio": float(
                body_ratio
            ),
            "bos_body_ratio": float(
                bos_body
            ),

            "displacement": True,
            "displacement_ratio": float(
                displacement["ratio"]
            ),

            "fvg": (
                fvg is not None
            ),
            "fvg_data": fvg,

            "quality_score": float(
                quality_score
            ),
            "score": float(
                quality_score
            ),

            "score_components": {
                "displacement_ratio": (
                    float(
                        displacement[
                            "ratio"
                        ]
                    )
                ),
                "bars_to_bos": int(
                    bars_to_bos
                ),
                "age": int(age),
                "ob_body_ratio": float(
                    body_ratio
                ),
                "bos_body_ratio": float(
                    bos_body
                ),
                "fvg": (
                    fvg is not None
                ),
            },
        }

    def _find_order_blocks(
        self,
        *,
        rates: Any,
        direction: str,
        structure_snapshot: (
            dict[str, Any]
        ),
    ) -> list[dict[str, Any]]:
        candles = self._as_list(
            rates
        )

        normalized = normalize_direction(
            direction
        )

        if (
            normalized is None
            or len(candles) < 10
        ):
            return []

        current_index = (
            len(candles) - 1
        )

        bos_events: list[
            dict[str, Any]
        ] = []

        history = structure_snapshot.get(
            "events",
            [],
        )

        if isinstance(history, list):
            for event in history:
                if not isinstance(
                    event,
                    dict,
                ):
                    continue

                if (
                    self._event_type(event)
                    != "BOS"
                ):
                    continue

                if (
                    self._event_direction(event)
                    != normalized
                ):
                    continue

                bos_events.append(
                    dict(event)
                )

        last_bos = structure_snapshot.get(
            "last_bos"
        )

        if (
            isinstance(last_bos, dict)
            and self._event_type(
                last_bos
            ) == "BOS"
            and self._event_direction(
                last_bos
            ) == normalized
        ):
            last_bos_id = (
                self._event_id(
                    last_bos
                )
            )

            if all(
                self._event_id(event)
                != last_bos_id
                for event in bos_events
            ):
                bos_events.append(
                    dict(last_bos)
                )

        bos_events.sort(
            key=lambda event: (
                self._event_time(event),
                self._event_index(event),
            ),
            reverse=True,
        )

        blocks: list[
            dict[str, Any]
        ] = []

        seen_bos_ids: set[
            tuple[str, int]
        ] = set()

        for bos_event in bos_events:
            bos_index = self._event_index(
                bos_event
            )

            bos_time = self._event_time(
                bos_event
            )

            bos_id = (
                normalized,
                bos_time,
            )

            if bos_id in seen_bos_ids:
                continue

            seen_bos_ids.add(
                bos_id
            )

            if bos_id in self.used_bos_ids:
                continue

            if (
                bos_index <= 0
                or bos_index
                >= len(candles)
            ):
                continue

            search_start = max(
                0,
                bos_index
                - self.config
                .order_block_search_bars,
            )

            candidates_for_bos: list[
                dict[str, Any]
            ] = []

            for index in range(
                bos_index - 1,
                search_start - 1,
                -1,
            ):
                candle = candles[index]

                if not self._candle_is_opposite(
                    candle,
                    normalized,
                ):
                    continue

                block = (
                    self._build_order_block(
                        rates=candles,
                        order_block_index=index,
                        bos_event=bos_event,
                        direction=normalized,
                        current_index=current_index,
                    )
                )

                if block is None:
                    continue

                candidates_for_bos.append(
                    block
                )

            if not candidates_for_bos:
                continue

            candidates_for_bos.sort(
                key=lambda block: (
                    float(
                        block.get(
                            "quality_score",
                            0.0,
                        )
                    ),
                    -int(
                        block.get(
                            "bars_to_bos",
                            999,
                        )
                    ),
                    int(
                        block.get(
                            "time",
                            0,
                        )
                    ),
                ),
                reverse=True,
            )

            blocks.extend(
                candidates_for_bos
            )
            return blocks       

    def _select_h4_order_block(
        self,
        *,
        blocks: list[dict[str, Any]],
        direction: str,
        current_price: float,
    ) -> dict[str, Any] | None:
        normalized = normalize_direction(
            direction
        )

        if (
            normalized is None
            or not blocks
            or current_price <= 0
        ):
            return None

        valid_blocks: list[
            dict[str, Any]
        ] = []

        for original in blocks:
            block = dict(original)

            low = safe_float(
                block.get("low")
            )

            high = safe_float(
                block.get("high")
            )

            if (
                low is None
                or high is None
                or high <= low
            ):
                continue

            entry = (
                high
                if normalized == "BULLISH"
                else low
            )

            if (
                normalized == "BULLISH"
                and entry >= current_price
            ):
                continue

            if (
                normalized == "BEARISH"
                and entry <= current_price
            ):
                continue

            quality_score = safe_float(
                block.get(
                    "quality_score",
                    block.get("score", 0.0),
                )
            )

            if quality_score is None:
                quality_score = 0.0

            if (
                quality_score
                < self.config
                .minimum_order_block_score
            ):
                continue

            block["_entry"] = float(entry)
            block["_entry_distance"] = float(
                abs(
                    current_price
                    - entry
                )
            )
            block["_block_size"] = float(
                high - low
            )

            valid_blocks.append(
                block
            )

        if not valid_blocks:
            return None

        valid_blocks.sort(
            key=lambda block: (
                float(
                    block.get(
                        "quality_score",
                        block.get(
                            "score",
                            0.0,
                        ),
                    )
                ),
                int(
                    block.get(
                        "bos_time",
                        0,
                    )
                ),
                -float(
                    block.get(
                        "_entry_distance",
                        float("inf"),
                    )
                ),
                -float(
                    block.get(
                        "_block_size",
                        float("inf"),
                    )
                ),
            ),
            reverse=True,
        )

        selected = dict(
            valid_blocks[0]
        )

        selected.pop(
            "_entry",
            None,
        )
        selected.pop(
            "_entry_distance",
            None,
        )
        selected.pop(
            "_block_size",
            None,
        )

        return selected

    def _price_touched_zone(
        self,
        *,
        candle: Any,
        zone_low: float,
        zone_high: float,
    ) -> bool:
        candle_low = get_field(
            candle,
            "low",
        )

        candle_high = get_field(
            candle,
            "high",
        )

        return (
            candle_low <= zone_high
            and candle_high >= zone_low
        )

    def _find_h4_zone_touch(
        self,
        *,
        rates: Any,
        block: dict[str, Any],
    ) -> dict[str, Any] | None:
        candles = self._as_list(
            rates
        )

        if not candles:
            return None

        low = safe_float(
            block.get("low")
        )

        high = safe_float(
            block.get("high")
        )

        if (
            low is None
            or high is None
            or high <= low
        ):
            return None

        block_time = int(
            block.get("time", 0)
        )

        bos_time = int(
            block.get("bos_time", 0)
        )

        search_time = max(
            block_time,
            bos_time,
        )

        for index, candle in enumerate(
            candles
        ):
            candle_time = get_time(
                candle
            )

            if candle_time <= search_time:
                continue

            if self._price_touched_zone(
                candle=candle,
                zone_low=low,
                zone_high=high,
            ):
                return {
                    "confirmed": True,
                    "index": int(index),
                    "time": int(
                        candle_time
                    ),
                    "low": float(
                        get_field(
                            candle,
                            "low",
                        )
                    ),
                    "high": float(
                        get_field(
                            candle,
                            "high",
                        )
                    ),
                    "close": float(
                        get_field(
                            candle,
                            "close",
                        )
                    ),
                    "zone_low": float(
                        low
                    ),
                    "zone_high": float(
                        high
                    ),
                }

        return None

    def _find_liquidity_sweep(
        self,
        *,
        rates: Any,
        direction: str,
        zone_touch_time: int = 0,
    ) -> dict[str, Any] | None:
        candles = self._as_list(
            rates
        )

        normalized = normalize_direction(
            direction
        )

        if (
            normalized is None
            or len(candles) < 5
        ):
            return None

        lookback = max(
            2,
            int(
                self.config
                .liquidity_lookback
            ),
        )

        start_index = max(
            lookback,
            len(candles)
            - int(
                self.config
                .internal_search_bars
            ),
        )

        sweeps: list[
            dict[str, Any]
        ] = []

        for index in range(
            start_index,
            len(candles),
        ):
            candle = candles[index]
            candle_time = get_time(
                candle
            )

            if (
                zone_touch_time > 0
                and candle_time
                < zone_touch_time
            ):
                continue

            previous = candles[
                index - lookback:index
            ]

            if len(previous) < lookback:
                continue

            candle_open = get_field(
                candle,
                "open",
            )

            candle_high = get_field(
                candle,
                "high",
            )

            candle_low = get_field(
                candle,
                "low",
            )

            candle_close = get_field(
                candle,
                "close",
            )

            candle_range = (
                candle_high
                - candle_low
            )

            if candle_range <= 0:
                continue

            if normalized == "BULLISH":
                liquidity_level = min(
                    get_field(
                        item,
                        "low",
                    )
                    for item in previous
                )

                swept = (
                    candle_low
                    < liquidity_level
                )

                reclaimed = (
                    candle_close
                    > liquidity_level
                )

                correct_close = (
                    candle_close
                    >= candle_open
                )

                sweep_distance = (
                    liquidity_level
                    - candle_low
                )

                rejection_distance = (
                    candle_close
                    - candle_low
                )

            else:
                liquidity_level = max(
                    get_field(
                        item,
                        "high",
                    )
                    for item in previous
                )

                swept = (
                    candle_high
                    > liquidity_level
                )

                reclaimed = (
                    candle_close
                    < liquidity_level
                )

                correct_close = (
                    candle_close
                    <= candle_open
                )

                sweep_distance = (
                    candle_high
                    - liquidity_level
                )

                rejection_distance = (
                    candle_high
                    - candle_close
                )

            sweep_ratio = (
                sweep_distance
                / candle_range
            )

            rejection_ratio = (
                rejection_distance
                / candle_range
            )

            if not swept:
                continue

            if (
                self.config
                .require_liquidity_reclaim
                and not reclaimed
            ):
                continue

            if (
                self.config
                .require_directional_sweep_close
                and not correct_close
            ):
                continue

            if (
                sweep_ratio
                < self.config
                .minimum_sweep_ratio
            ):
                continue

            sweep = {
                "confirmed": True,
                "direction": normalized,
                "index": int(index),
                "time": int(
                    candle_time
                ),
                "liquidity_level": float(
                    liquidity_level
                ),
                "sweep_price": float(
                    candle_low
                    if normalized
                    == "BULLISH"
                    else candle_high
                ),
                "open": float(
                    candle_open
                ),
                "high": float(
                    candle_high
                ),
                "low": float(
                    candle_low
                ),
                "close": float(
                    candle_close
                ),
                "sweep_distance": float(
                    sweep_distance
                ),
                "sweep_ratio": float(
                    sweep_ratio
                ),
                "rejection_ratio": float(
                    rejection_ratio
                ),
                "reclaimed": bool(
                    reclaimed
                ),
            }

            sweeps.append(
                sweep
            )

        if not sweeps:
            return None

        sweeps.sort(
            key=lambda sweep: (
                int(
                    sweep.get(
                        "time",
                        0,
                    )
                ),
                float(
                    sweep.get(
                        "rejection_ratio",
                        0.0,
                    )
                ),
                float(
                    sweep.get(
                        "sweep_ratio",
                        0.0,
                    )
                ),
            ),
            reverse=True,
        )

        return dict(
            sweeps[0]
        )

    def _find_internal_choch(
        self,
        *,
        snapshot: dict[str, Any],
        direction: str,
        sweep_time: int,
    ) -> dict[str, Any] | None:
        choch = (
            self._find_recent_structure_event(
                snapshot=snapshot,
                direction=direction,
                event_type="CHOCH",
                minimum_time=sweep_time,
            )
        )

        if choch is None:
            return None

        result = dict(
            choch
        )

        result["confirmed"] = True
        result[
            "confirmation_role"
        ] = "INTERNAL_CHOCH"

        return result

    def _find_internal_bos(
        self,
        *,
        snapshot: dict[str, Any],
        direction: str,
        choch_time: int,
    ) -> dict[str, Any] | None:
        bos = (
            self._find_recent_structure_event(
                snapshot=snapshot,
                direction=direction,
                event_type="BOS",
                minimum_time=choch_time,
            )
        )

        if bos is None:
            return None

        if (
            self._event_time(bos)
            <= int(choch_time)
        ):
            return None

        result = dict(
            bos
        )

        result["confirmed"] = True
        result[
            "confirmation_role"
        ] = "INTERNAL_BOS"

        return result

    def _find_m5_order_block(
        self,
        *,
        rates: Any,
        direction: str,
        internal_bos: dict[str, Any],
        minimum_time: int,
    ) -> dict[str, Any] | None:
        candles = self._as_list(
            rates
        )

        normalized = normalize_direction(
            direction
        )

        if (
            normalized is None
            or len(candles) < 5
        ):
            return None

        bos_index = self._event_index(
            internal_bos
        )

        bos_time = self._event_time(
            internal_bos
        )

        if bos_index < 0:
            for index, candle in enumerate(
                candles
            ):
                if (
                    get_time(candle)
                    == bos_time
                ):
                    bos_index = index
                    break

        if (
            bos_index <= 0
            or bos_index
            >= len(candles)
        ):
            return None

        search_start = max(
            0,
            bos_index
            - self.config
            .m5_order_block_search_bars,
        )

        candidates: list[
            dict[str, Any]
        ] = []

        for index in range(
            bos_index - 1,
            search_start - 1,
            -1,
        ):
            candle = candles[index]

            candle_time = get_time(
                candle
            )

            if (
                candle_time
                < int(minimum_time)
            ):
                continue

            if not self._candle_is_opposite(
                candle,
                normalized,
            ):
                continue

            low = get_field(
                candle,
                "low",
            )

            high = get_field(
                candle,
                "high",
            )

            if high <= low:
                continue

            body_ratio = (
                candle_body_ratio(
                    candle
                )
            )

            if (
                body_ratio
                < self.config
                .minimum_m5_order_block_body_ratio
            ):
                continue

            bars_to_bos = (
                bos_index - index
            )

            if (
                bars_to_bos <= 0
                or bars_to_bos
                > self.config
                .maximum_m5_bars_to_bos
            ):
                continue

            mitigated = (
                order_block_was_mitigated(
                    rates=candles,
                    block={
                        "direction": normalized,
                        "low": low,
                        "high": high,
                    },
                    start_index=bos_index + 1,
                    end_index=(
                        len(candles) - 1
                    ),
                )
            )

            if mitigated:
                continue

            displacement = (
                self._detect_displacement(
                    rates=candles,
                    start_index=index + 1,
                    end_index=bos_index,
                    direction=normalized,
                )
            )

            if not displacement[
                "confirmed"
            ]:
                continue

            midpoint = (
                low + high
            ) / 2.0

            candidate = {
                "direction": normalized,
                "type": normalized,
                "time": int(
                    candle_time
                ),
                "order_block_index": int(
                    index
                ),
                "bos_index": int(
                    bos_index
                ),
                "bos_time": int(
                    bos_time
                ),
                "low": float(
                    low
                ),
                "high": float(
                    high
                ),
                "midpoint": float(
                    midpoint
                ),
                "proximal": float(
                    high
                    if normalized
                    == "BULLISH"
                    else low
                ),
                "distal": float(
                    low
                    if normalized
                    == "BULLISH"
                    else high
                ),
                "bars_to_bos": int(
                    bars_to_bos
                ),
                "ob_body_ratio": float(
                    body_ratio
                ),
                "displacement": True,
                "displacement_ratio": float(
                    displacement[
                        "ratio"
                    ]
                ),
                "fresh": True,
                "mitigated": False,
            }

            candidates.append(
                candidate
            )

        if not candidates:
            return None

        candidates.sort(
            key=lambda block: (
                float(
                    block.get(
                        "displacement_ratio",
                        0.0,
                    )
                ),
                -int(
                    block.get(
                        "bars_to_bos",
                        999,
                    )
                ),
                int(
                    block.get(
                        "time",
                        0,
                    )
                ),
            ),
            reverse=True,
        )

        return dict(
            candidates[0]
        )

    def _calculate_entry_prices(
        self,
        *,
        block: dict[str, Any],
        direction: str,
        current_price: float,
    ) -> dict[str, Any] | None:
        normalized = normalize_direction(
            direction
        )

        if normalized is None:
            return None

        low = safe_float(
            block.get("low")
        )

        high = safe_float(
            block.get("high")
        )

        if (
            low is None
            or high is None
            or high <= low
        ):
            return None

        block_size = (
            high - low
        )

        stop_buffer = max(
            0.0,
            block_size
            * self.config
            .stop_buffer_fraction,
        )

        if (
            self.config
            .entry_mode
            == "MIDPOINT"
        ):
            entry = (
                low + high
            ) / 2.0

        elif (
            self.config
            .entry_mode
            == "DISTAL"
        ):
            entry = (
                low
                if normalized
                == "BULLISH"
                else high
            )

        else:
            entry = (
                high
                if normalized
                == "BULLISH"
                else low
            )

        if normalized == "BULLISH":
            stop_loss = (
                low - stop_buffer
            )

            if entry >= current_price:
                return None

            risk_distance = (
                entry - stop_loss
            )

        else:
            stop_loss = (
                high + stop_buffer
            )

            if entry <= current_price:
                return None

            risk_distance = (
                stop_loss - entry
            )

        if risk_distance <= 0:
            return None

        rr = max(
            self.config.minimum_rr,
            min(
                self.config.maximum_rr,
                self.config.preferred_rr,
            ),
        )

        if normalized == "BULLISH":
            take_profit = (
                entry
                + risk_distance
                * rr
            )

            order_type = "BUY_LIMIT"

        else:
            take_profit = (
                entry
                - risk_distance
                * rr
            )

            order_type = "SELL_LIMIT"

        return {
            "direction": normalized,
            "entry": float(
                entry
            ),
            "entry_price": float(
                entry
            ),
            "stop_loss": float(
                stop_loss
            ),
            "sl": float(
                stop_loss
            ),
            "take_profit": float(
                take_profit
            ),
            "tp": float(
                take_profit
            ),
            "risk_distance": float(
                risk_distance
            ),
            "rr": float(
                rr
            ),
            "order_type": order_type,
        }

    def _find_dynamic_target(
        self,
        *,
        rates: Any,
        direction: str,
        entry: float,
        stop_loss: float,
        fallback_take_profit: float,
    ) -> dict[str, Any]:
        candles = self._as_list(
            rates
        )

        normalized = normalize_direction(
            direction
        )

        risk_distance = abs(
            entry - stop_loss
        )

        if (
            normalized is None
            or not candles
            or risk_distance <= 0
        ):
            return {
                "price": float(
                    fallback_take_profit
                ),
                "rr": float(
                    self.config
                    .preferred_rr
                ),
                "source": "FIXED_RR",
            }

        lookback = max(
            5,
            int(
                self.config
                .target_liquidity_lookback
            ),
        )

        recent = candles[
            -lookback:
        ]

        if normalized == "BULLISH":
            levels = sorted(
                {
                    float(
                        get_field(
                            candle,
                            "high",
                        )
                    )
                    for candle in recent
                    if get_field(
                        candle,
                        "high",
                    ) > entry
                }
            )

            target_candidates = [
                level
                for level in levels
                if (
                    level - entry
                )
                / risk_distance
                >= self.config.minimum_rr
            ]

            target = (
                target_candidates[0]
                if target_candidates
                else fallback_take_profit
            )

            rr = (
                target - entry
            ) / risk_distance

        else:
            levels = sorted(
                {
                    float(
                        get_field(
                            candle,
                            "low",
                        )
                    )
                    for candle in recent
                    if get_field(
                        candle,
                        "low",
                    ) < entry
                },
                reverse=True,
            )

            target_candidates = [
                level
                for level in levels
                if (
                    entry - level
                )
                / risk_distance
                >= self.config.minimum_rr
            ]

            target = (
                target_candidates[0]
                if target_candidates
                else fallback_take_profit
            )

            rr = (
                entry - target
            ) / risk_distance

        if (
            rr < self.config.minimum_rr
            or rr > self.config.maximum_rr
        ):
            target = float(
                fallback_take_profit
            )

            rr = (
                self.config
                .preferred_rr
            )

            source = "FIXED_RR"

        else:
            source = (
                "LIQUIDITY_TARGET"
            )

        return {
            "price": float(
                target
            ),
            "rr": float(
                rr
            ),
            "source": source,
        }

    def _daily_blocker(
        self,
        *,
        rates: Any,
        direction: str,
        entry: float,
        stop_loss: float,
    ) -> dict[str, Any] | None:
        candles = self._as_list(
            rates
        )

        normalized = normalize_direction(
            direction
        )

        if (
            normalized is None
            or len(candles) < 5
        ):
            return None

        risk_distance = abs(
            entry - stop_loss
        )

        if risk_distance <= 0:
            return None

        recent = candles[
            -self.config
            .daily_blocker_lookback:
        ]

        minimum_room_r = (
            self.config
            .minimum_daily_room_r
        )

        if normalized == "BULLISH":
            resistance = max(
                get_field(
                    candle,
                    "high",
                )
                for candle in recent
            )

            room_r = (
                resistance - entry
            ) / risk_distance

            if (
                0 < room_r
                < minimum_room_r
            ):
                return {
                    "blocked": True,
                    "direction": "BEARISH",
                    "level": float(
                        resistance
                    ),
                    "low": float(
                        resistance
                    ),
                    "high": float(
                        resistance
                    ),
                    "room_r": float(
                        room_r
                    ),
                    "reason": (
                        "daily_resistance_"
                        "too_close"
                    ),
                }

        else:
            support = min(
                get_field(
                    candle,
                    "low",
                )
                for candle in recent
            )

            room_r = (
                entry - support
            ) / risk_distance

            if (
                0 < room_r
                < minimum_room_r
            ):
                return {
                    "blocked": True,
                    "direction": "BULLISH",
                    "level": float(
                        support
                    ),
                    "low": float(
                        support
                    ),
                    "high": float(
                        support
                    ),
                    "room_r": float(
                        room_r
                    ),
                    "reason": (
                        "daily_support_"
                        "too_close"
                    ),
                }

        return None

    def _build_trade(
        self,
        *,
        direction: str,
        h4_order_block: dict[str, Any],
        m5_order_block: dict[str, Any],
        internal_bos: dict[str, Any],
        m5_rates: Any,
        h4_rates: Any,
    ) -> dict[str, Any] | None:
        m5 = self._as_list(
            m5_rates
        )

        h4 = self._as_list(
            h4_rates
        )

        if not m5:
            return None

        normalized = normalize_direction(
            direction
        )

        if normalized is None:
            return None

        current_price = get_field(
            m5[-1],
            "close",
        )

        prices = (
            self._calculate_entry_prices(
                block=m5_order_block,
                direction=normalized,
                current_price=current_price,
            )
        )

        if prices is None:
            return None

        target = (
            self._find_dynamic_target(
                rates=h4,
                direction=normalized,
                entry=float(
                    prices["entry"]
                ),
                stop_loss=float(
                    prices["stop_loss"]
                ),
                fallback_take_profit=float(
                    prices[
                        "take_profit"
                    ]
                ),
            )
        )

        prices["take_profit"] = float(
            target["price"]
        )
        prices["tp"] = float(
            target["price"]
        )
        prices["rr"] = float(
            target["rr"]
        )

        signal_time = (
            get_time(m5[-1])
            + self.config
            .m5_timeframe_seconds
        )

        trade = {
            **prices,

            "signal_time": int(
                signal_time
            ),

            "source_timeframe": "M5",
            "strategy_name": (
                self.config
                .strategy_name
            ),

            "h4_order_block_time": int(
                h4_order_block.get(
                    "time",
                    0,
                )
            ),
            "h4_bos_time": int(
                h4_order_block.get(
                    "bos_time",
                    0,
                )
            ),

            "order_block_time": int(
                m5_order_block.get(
                    "time",
                    0,
                )
            ),
            "bos_time": int(
                internal_bos.get(
                    "time",
                    m5_order_block.get(
                        "bos_time",
                        0,
                    ),
                )
            ),

            "quality_score": float(
                h4_order_block.get(
                    "quality_score",
                    h4_order_block.get(
                        "score",
                        0.0,
                    ),
                )
            ),

            "target_source": str(
                target["source"]
            ),

            "higher_timeframe": (
                self.config
                .higher_timeframe
            ),
            "zone_timeframe": (
                self.config
                .zone_timeframe
            ),
            "entry_timeframe": (
                self.config
                .entry_timeframe
            ),
        }

        return trade

    def _mark_bos_used(
        self,
        *,
        direction: str,
        bos_time: int,
    ) -> None:
        normalized = normalize_direction(
            direction
        )

        if (
            normalized is None
            or int(bos_time) <= 0
        ):
            return

        self.used_bos_ids.add(
            (
                normalized,
                int(bos_time),
            )
        ) 
    def process(
        self,
        *,
        h4_rates: Any,
        d1_rates: Any,
        m5_rates: Any,
    ) -> StrategyResult:
        """
        Главный цикл стратегии SMC X PRIME.

        Последовательность:
        1. Определение структуры D1.
        2. Поиск направления старшего таймфрейма.
        3. Обновление структуры H4.
        4. Поиск и выбор H4 Order Block.
        5. Подтверждение касания H4-зоны.
        6. Поиск снятия ликвидности на M5.
        7. Подтверждение внутреннего CHOCH.
        8. Подтверждение внутреннего BOS.
        9. Поиск M5 Order Block.
        10. Расчёт входа, SL и TP.
        11. Проверка D1 blocker.
        12. Создание торгового сигнала.
        """
        h4 = self._as_list(
            h4_rates
        )

        d1 = self._as_list(
            d1_rates
        )

        m5 = self._as_list(
            m5_rates
        )

        diagnostics: dict[str, Any] = {
            "strategy_name": (
                self.config.strategy_name
            ),
            "h4_candles": len(h4),
            "d1_candles": len(d1),
            "m5_candles": len(m5),
        }

        if (
            len(d1)
            < self.config.minimum_d1_candles
        ):
            return self._result(
                event="NO_SIGNAL",
                reason="not_enough_d1_data",
                diagnostics=diagnostics,
            )

        if (
            len(h4)
            < self.config.minimum_h4_candles
        ):
            return self._result(
                event="NO_SIGNAL",
                reason="not_enough_h4_data",
                diagnostics=diagnostics,
            )

        if (
            len(m5)
            < self.config.minimum_m5_candles
        ):
            return self._result(
                event="NO_SIGNAL",
                reason="not_enough_m5_data",
                diagnostics=diagnostics,
            )

        try:
            d1_snapshot, d1_events = (
                self._process_structure(
                    engine=(
                        self
                        .higher_timeframe_structure
                    ),
                    rates=d1,
                )
            )

            diagnostics[
                "d1_new_events"
            ] = len(d1_events)

            diagnostics[
                "d1_trend"
            ] = d1_snapshot.get(
                "trend",
                d1_snapshot.get(
                    "direction",
                    "RANGE",
                ),
            )

            direction = (
                self
                ._resolve_higher_timeframe_direction(
                    d1_snapshot
                )
            )

            if direction is None:
                return self._result(
                    event="NO_SIGNAL",
                    reason=(
                        "higher_timeframe_"
                        "direction_missing"
                    ),
                    higher_timeframe_structure=(
                        d1_snapshot
                    ),
                    diagnostics=diagnostics,
                )

            diagnostics[
                "direction"
            ] = direction

            h4_snapshot, h4_events = (
                self._process_structure(
                    engine=(
                        self
                        .signal_timeframe_structure
                    ),
                    rates=h4,
                )
            )

            diagnostics[
                "h4_new_events"
            ] = len(h4_events)

            h4_blocks = (
                self._find_order_blocks(
                    rates=h4,
                    direction=direction,
                    structure_snapshot=(
                        h4_snapshot
                    ),
                )
            )

            diagnostics[
                "h4_order_block_candidates"
            ] = len(h4_blocks)

            if not h4_blocks:
                return self._result(
                    event="NO_SIGNAL",
                    direction=direction,
                    reason=(
                        "h4_order_block_missing"
                    ),
                    higher_timeframe_structure=(
                        d1_snapshot
                    ),
                    diagnostics=diagnostics,
                )

            current_h4_price = get_field(
                h4[-1],
                "close",
            )

            h4_order_block = (
                self._select_h4_order_block(
                    blocks=h4_blocks,
                    direction=direction,
                    current_price=(
                        current_h4_price
                    ),
                )
            )

            if h4_order_block is None:
                return self._result(
                    event="NO_SIGNAL",
                    direction=direction,
                    reason=(
                        "valid_h4_order_block_"
                        "missing"
                    ),
                    higher_timeframe_structure=(
                        d1_snapshot
                    ),
                    diagnostics=diagnostics,
                )

            diagnostics[
                "selected_h4_order_block_time"
            ] = int(
                h4_order_block.get(
                    "time",
                    0,
                )
            )

            diagnostics[
                "selected_h4_bos_time"
            ] = int(
                h4_order_block.get(
                    "bos_time",
                    0,
                )
            )

            diagnostics[
                "selected_h4_quality_score"
            ] = float(
                h4_order_block.get(
                    "quality_score",
                    h4_order_block.get(
                        "score",
                        0.0,
                    ),
                )
            )

            zone_touch = (
                self._find_h4_zone_touch(
                    rates=m5,
                    block=h4_order_block,
                )
            )

            if zone_touch is None:
                return self._result(
                    event="NO_SIGNAL",
                    direction=direction,
                    reason=(
                        "h4_order_block_"
                        "not_touched"
                    ),
                    higher_timeframe_structure=(
                        d1_snapshot
                    ),
                    h4_order_block=(
                        h4_order_block
                    ),
                    diagnostics=diagnostics,
                )

            diagnostics[
                "h4_zone_touch_time"
            ] = int(
                zone_touch.get(
                    "time",
                    0,
                )
            )

            liquidity_sweep = (
                self._find_liquidity_sweep(
                    rates=m5,
                    direction=direction,
                    zone_touch_time=int(
                        zone_touch.get(
                            "time",
                            0,
                        )
                    ),
                )
            )

            if liquidity_sweep is None:
                return self._result(
                    event="NO_SIGNAL",
                    direction=direction,
                    reason=(
                        "liquidity_sweep_"
                        "missing"
                    ),
                    higher_timeframe_structure=(
                        d1_snapshot
                    ),
                    h4_order_block=(
                        h4_order_block
                    ),
                    diagnostics=diagnostics,
                )

            diagnostics[
                "liquidity_sweep_time"
            ] = int(
                liquidity_sweep.get(
                    "time",
                    0,
                )
            )

            internal_snapshot, internal_events = (
                self._process_structure(
                    engine=(
                        self
                        .internal_structure
                    ),
                    rates=m5,
                )
            )

            diagnostics[
                "internal_new_events"
            ] = len(
                internal_events
            )

            internal_choch = (
                self._find_internal_choch(
                    snapshot=(
                        internal_snapshot
                    ),
                    direction=direction,
                    sweep_time=int(
                        liquidity_sweep.get(
                            "time",
                            0,
                        )
                    ),
                )
            )

            if internal_choch is None:
                return self._result(
                    event="NO_SIGNAL",
                    direction=direction,
                    reason=(
                        "internal_choch_"
                        "missing"
                    ),
                    higher_timeframe_structure=(
                        d1_snapshot
                    ),
                    h4_order_block=(
                        h4_order_block
                    ),
                    liquidity_sweep=(
                        liquidity_sweep
                    ),
                    diagnostics=diagnostics,
                )

            diagnostics[
                "internal_choch_time"
            ] = self._event_time(
                internal_choch
            )

            internal_bos = (
                self._find_internal_bos(
                    snapshot=(
                        internal_snapshot
                    ),
                    direction=direction,
                    choch_time=(
                        self._event_time(
                            internal_choch
                        )
                    ),
                )
            )

            if internal_bos is None:
                return self._result(
                    event="NO_SIGNAL",
                    direction=direction,
                    reason=(
                        "internal_bos_missing"
                    ),
                    higher_timeframe_structure=(
                        d1_snapshot
                    ),
                    h4_order_block=(
                        h4_order_block
                    ),
                    liquidity_sweep=(
                        liquidity_sweep
                    ),
                    internal_choch=(
                        internal_choch
                    ),
                    diagnostics=diagnostics,
                )

            diagnostics[
                "internal_bos_time"
            ] = self._event_time(
                internal_bos
            )

            m5_order_block = (
                self._find_m5_order_block(
                    rates=m5,
                    direction=direction,
                    internal_bos=(
                        internal_bos
                    ),
                    minimum_time=(
                        self._event_time(
                            internal_choch
                        )
                    ),
                )
            )

            if m5_order_block is None:
                return self._result(
                    event="NO_SIGNAL",
                    direction=direction,
                    reason=(
                        "m5_order_block_missing"
                    ),
                    higher_timeframe_structure=(
                        d1_snapshot
                    ),
                    h4_order_block=(
                        h4_order_block
                    ),
                    liquidity_sweep=(
                        liquidity_sweep
                    ),
                    internal_choch=(
                        internal_choch
                    ),
                    internal_bos=(
                        internal_bos
                    ),
                    diagnostics=diagnostics,
                )

            diagnostics[
                "m5_order_block_time"
            ] = int(
                m5_order_block.get(
                    "time",
                    0,
                )
            )

            trade = self._build_trade(
                direction=direction,
                h4_order_block=(
                    h4_order_block
                ),
                m5_order_block=(
                    m5_order_block
                ),
                internal_bos=(
                    internal_bos
                ),
                m5_rates=m5,
                h4_rates=h4,
            )

            if trade is None:
                return self._result(
                    event="NO_SIGNAL",
                    direction=direction,
                    reason=(
                        "trade_prices_invalid"
                    ),
                    higher_timeframe_structure=(
                        d1_snapshot
                    ),
                    h4_order_block=(
                        h4_order_block
                    ),
                    liquidity_sweep=(
                        liquidity_sweep
                    ),
                    internal_choch=(
                        internal_choch
                    ),
                    internal_bos=(
                        internal_bos
                    ),
                    diagnostics=diagnostics,
                )

            blocker = self._daily_blocker(
                rates=d1,
                direction=direction,
                entry=float(
                    trade["entry"]
                ),
                stop_loss=float(
                    trade["stop_loss"]
                ),
            )

            if blocker is not None:
                diagnostics[
                    "daily_blocker"
                ] = blocker

                return self._result(
                    event="NO_SIGNAL",
                    direction=direction,
                    reason=str(
                        blocker.get(
                            "reason",
                            "daily_blocker",
                        )
                    ),
                    higher_timeframe_structure=(
                        d1_snapshot
                    ),
                    h4_order_block=(
                        h4_order_block
                    ),
                    liquidity_sweep=(
                        liquidity_sweep
                    ),
                    internal_choch=(
                        internal_choch
                    ),
                    internal_bos=(
                        internal_bos
                    ),
                    diagnostics=diagnostics,
                )

            h4_bos_time = int(
                h4_order_block.get(
                    "bos_time",
                    0,
                )
            )

            self._mark_bos_used(
                direction=direction,
                bos_time=h4_bos_time,
            )

            diagnostics[
                "signal_confirmed"
            ] = True

            diagnostics[
                "entry"
            ] = float(
                trade["entry"]
            )

            diagnostics[
                "stop_loss"
            ] = float(
                trade["stop_loss"]
            )

            diagnostics[
                "take_profit"
            ] = float(
                trade["take_profit"]
            )

            diagnostics[
                "rr"
            ] = float(
                trade["rr"]
            )

            return self._result(
                event="SIGNAL",
                direction=direction,
                reason="strategy_confirmed",
                higher_timeframe_structure=(
                    d1_snapshot
                ),
                h4_order_block=(
                    h4_order_block
                ),
                liquidity_sweep=(
                    liquidity_sweep
                ),
                internal_choch=(
                    internal_choch
                ),
                internal_bos=(
                    internal_bos
                ),
                trade=trade,
                diagnostics=diagnostics,
            )

        except Exception as error:
            diagnostics[
                "exception_type"
            ] = type(error).__name__

            diagnostics[
                "exception_message"
            ] = str(error)

            return self._result(
                event="ERROR",
                reason=(
                    f"strategy_engine_error: "
                    f"{type(error).__name__}: "
                    f"{error}"
                ),
                diagnostics=diagnostics,
            )


def evaluate_strategy(
    **kwargs: Any,
) -> StrategyResult:
    """
    Создаёт отдельный StrategyEngine
    и возвращает StrategyResult.

    Подходит для одиночного вызова,
    но не сохраняет состояние между свечами.
    """
    engine = StrategyEngine()

    return engine.process(
        **kwargs
    )


def run_strategy(
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Совместимая обёртка, возвращающая dict.
    """
    return evaluate_strategy(
        **kwargs
    ).to_dict()


def generate_signal(
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Старое имя функции сохранено
    для совместимости с проектом.
    """
    return run_strategy(
        **kwargs
    )


__all__ = [
    "StrategyConfig",
    "StrategyEngine",
    "StrategyResult",
    "evaluate_strategy",
    "generate_signal",
    "normalize_direction",
    "run_strategy",
    "safe_float",
]