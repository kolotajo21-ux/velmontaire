from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


VALID_TRENDS = {"RANGE", "BULLISH", "BEARISH"}
VALID_BREAK_DIRECTIONS = {"UP", "DOWN"}


@dataclass(slots=True)
class StructurePoint:
    index: int
    time: int
    price: float
    kind: str
    label: str | None = None
    atr: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "time": self.time,
            "price": self.price,
            "kind": self.kind,
            "label": self.label,
            "atr": self.atr,
        }


@dataclass(slots=True)
class StructureEvent:
    event_id: str
    event: str
    event_type: str
    direction: str
    trend_before: str
    trend_after: str

    index: int
    time: int
    close: float

    broken_level: float
    broken_swing: StructurePoint

    body_ratio: float
    break_distance: float
    break_distance_atr: float

    confirmed: bool = True

    def to_dict(self) -> dict[str, Any]:
        is_choch = self.event_type == "CHOCH"

        return {
            "event_id": self.event_id,
            "type": self.event_type,
            "event": self.event,
            "direction": self.direction,
            "bos": (
                "UP"
                if self.direction == "BULLISH"
                else "DOWN"
            ),
            "choch": is_choch,
            "trend_before_break": self.trend_before,
            "trend": self.trend_after,
            "confirmed": self.confirmed,
            "index": self.index,
            "time": self.time,
            "close": self.close,
            "broken_level": self.broken_level,
            "broken_swing": self.broken_swing.to_dict(),
            "body_ratio": self.body_ratio,
            "break_distance": self.break_distance,
            "break_distance_atr": self.break_distance_atr,
        }


@dataclass
class StructureState:
    trend: str = "RANGE"

    last_high: StructurePoint | None = None
    previous_high: StructurePoint | None = None

    last_low: StructurePoint | None = None
    previous_low: StructurePoint | None = None

    last_hh: StructurePoint | None = None
    last_hl: StructurePoint | None = None
    last_lh: StructurePoint | None = None
    last_ll: StructurePoint | None = None

    active_high: StructurePoint | None = None
    active_low: StructurePoint | None = None

    high_broken: bool = False
    low_broken: bool = False

    last_bos_event: StructureEvent | None = None
    last_choch_event: StructureEvent | None = None
    last_event: StructureEvent | None = None

    last_processed_index: int = -1

    events: list[dict[str, Any]] = field(
        default_factory=list
    )

    def add_event(
        self,
        event: StructureEvent,
    ) -> None:
        payload = event.to_dict()

        self.last_event = event

        if event.event_type == "CHOCH":
            self.last_choch_event = event
        else:
            self.last_bos_event = event

        self.events.append(payload)

        if len(self.events) > 500:
            del self.events[:-500]


def validate_swing_length(
    swing_length: int,
) -> int:
    swing_length = int(swing_length)

    if swing_length < 1:
        raise ValueError(
            "swing_length должен быть не меньше 1"
        )

    return swing_length


def candle_range(
    candle: Any,
) -> float:
    high = float(candle["high"])
    low = float(candle["low"])

    return max(0.0, high - low)


def candle_body(
    candle: Any,
) -> float:
    open_price = float(candle["open"])
    close_price = float(candle["close"])

    return abs(close_price - open_price)


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
    open_price = float(candle["open"])
    close_price = float(candle["close"])

    if close_price > open_price:
        return "BULLISH"

    if close_price < open_price:
        return "BEARISH"

    return "NEUTRAL"


def calculate_true_range(
    rates: Any,
    index: int,
) -> float:
    if rates is None:
        return 0.0

    if index < 0 or index >= len(rates):
        return 0.0

    current_high = float(rates[index]["high"])
    current_low = float(rates[index]["low"])

    if index == 0:
        return max(0.0, current_high - current_low)

    previous_close = float(
        rates[index - 1]["close"]
    )

    return max(
        current_high - current_low,
        abs(current_high - previous_close),
        abs(current_low - previous_close),
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

    period = max(1, int(period))

    start_index = max(
        0,
        end_index - period + 1,
    )

    true_ranges = [
        calculate_true_range(rates, index)
        for index in range(
            start_index,
            end_index + 1,
        )
    ]

    true_ranges = [
        value
        for value in true_ranges
        if value > 0
    ]

    if not true_ranges:
        return 0.0

    return sum(true_ranges) / len(true_ranges)


def is_swing_high(
    rates: Any,
    index: int,
    swing_length: int,
) -> bool:
    swing_length = validate_swing_length(
        swing_length
    )

    if rates is None:
        return False

    if index < swing_length:
        return False

    if index + swing_length >= len(rates):
        return False

    current_high = float(
        rates[index]["high"]
    )

    for left_index in range(
        index - swing_length,
        index,
    ):
        if current_high <= float(
            rates[left_index]["high"]
        ):
            return False

    for right_index in range(
        index + 1,
        index + swing_length + 1,
    ):
        if current_high < float(
            rates[right_index]["high"]
        ):
            return False

    return True


def is_swing_low(
    rates: Any,
    index: int,
    swing_length: int,
) -> bool:
    swing_length = validate_swing_length(
        swing_length
    )

    if rates is None:
        return False

    if index < swing_length:
        return False

    if index + swing_length >= len(rates):
        return False

    current_low = float(
        rates[index]["low"]
    )

    for left_index in range(
        index - swing_length,
        index,
    ):
        if current_low >= float(
            rates[left_index]["low"]
        ):
            return False

    for right_index in range(
        index + 1,
        index + swing_length + 1,
    ):
        if current_low > float(
            rates[right_index]["low"]
        ):
            return False

    return True


def classify_high(
    current: StructurePoint,
    previous: StructurePoint | None,
) -> str:
    if previous is None:
        return "HIGH"

    if current.price > previous.price:
        return "HH"

    return "LH"


def classify_low(
    current: StructurePoint,
    previous: StructurePoint | None,
) -> str:
    if previous is None:
        return "LOW"

    if current.price > previous.price:
        return "HL"

    return "LL"


def swings_are_too_close(
    first_price: float,
    second_price: float,
    minimum_distance: float,
) -> bool:
    if minimum_distance <= 0:
        return False

    return (
        abs(
            float(first_price)
            - float(second_price)
        )
        < float(minimum_distance)
    )


def point_to_dict(
    point: StructurePoint,
) -> dict[str, Any]:
    return point.to_dict()


def find_swings(
    rates: Any,
    length: int,
    minimum_distance_atr: float = 0.10,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    length = validate_swing_length(length)

    if rates is None:
        return [], []

    if len(rates) < length * 2 + 1:
        return [], []

    swing_highs: list[StructurePoint] = []
    swing_lows: list[StructurePoint] = []

    previous_high: StructurePoint | None = None
    previous_low: StructurePoint | None = None

    for index in range(
        length,
        len(rates) - length,
    ):
        local_atr = calculate_atr(
            rates=rates,
            end_index=index,
            period=14,
        )

        minimum_distance = (
            local_atr
            * float(minimum_distance_atr)
        )

        if is_swing_high(
            rates=rates,
            index=index,
            swing_length=length,
        ):
            point = StructurePoint(
                index=index,
                time=int(rates[index]["time"]),
                price=float(rates[index]["high"]),
                kind="HIGH",
                atr=local_atr,
            )

            point.label = classify_high(
                current=point,
                previous=previous_high,
            )

            if (
                not swing_highs
                or not swings_are_too_close(
                    first_price=point.price,
                    second_price=swing_highs[-1].price,
                    minimum_distance=minimum_distance,
                )
            ):
                swing_highs.append(point)
                previous_high = point

        if is_swing_low(
            rates=rates,
            index=index,
            swing_length=length,
        ):
            point = StructurePoint(
                index=index,
                time=int(rates[index]["time"]),
                price=float(rates[index]["low"]),
                kind="LOW",
                atr=local_atr,
            )

            point.label = classify_low(
                current=point,
                previous=previous_low,
            )

            if (
                not swing_lows
                or not swings_are_too_close(
                    first_price=point.price,
                    second_price=swing_lows[-1].price,
                    minimum_distance=minimum_distance,
                )
            ):
                swing_lows.append(point)
                previous_low = point

    return (
        [
            point_to_dict(point)
            for point in swing_highs
        ],
        [
            point_to_dict(point)
            for point in swing_lows
        ],
    )


def close_crossed_level(
    rates: Any,
    index: int,
    level: float,
    direction: str,
) -> bool:
    if direction not in VALID_BREAK_DIRECTIONS:
        return False

    if rates is None:
        return False

    if index <= 0 or index >= len(rates):
        return False

    previous_close = float(
        rates[index - 1]["close"]
    )
    current_close = float(
        rates[index]["close"]
    )

    if direction == "UP":
        return (
            previous_close <= level
            and current_close > level
        )

    return (
        previous_close >= level
        and current_close < level
    )
def candle_has_displacement(
    rates: Any,
    index: int,
    direction: str,
    minimum_body_ratio: float = 0.45,
    minimum_range_atr: float = 0.70,
    minimum_close_beyond_atr: float = 0.03,
    broken_level: float | None = None,
) -> bool:
    if direction not in VALID_BREAK_DIRECTIONS:
        return False

    if rates is None:
        return False

    if index <= 0 or index >= len(rates):
        return False

    candle = rates[index]

    open_price = float(candle["open"])
    close_price = float(candle["close"])
    total_range = candle_range(candle)

    if total_range <= 0:
        return False

    body_ratio = candle_body_ratio(candle)

    if body_ratio < float(minimum_body_ratio):
        return False

    if direction == "UP":
        if close_price <= open_price:
            return False
    else:
        if close_price >= open_price:
            return False

    local_atr = calculate_atr(
        rates=rates,
        end_index=index - 1,
        period=14,
    )

    if local_atr <= 0:
        return True

    if total_range < (
        local_atr * float(minimum_range_atr)
    ):
        return False

    if broken_level is not None:
        if direction == "UP":
            close_beyond = (
                close_price - float(broken_level)
            )
        else:
            close_beyond = (
                float(broken_level) - close_price
            )

        minimum_close_beyond = (
            local_atr
            * float(minimum_close_beyond_atr)
        )

        if close_beyond < minimum_close_beyond:
            return False

    return True


def create_structure_event(
    rates: Any,
    index: int,
    direction: str,
    broken_point: StructurePoint,
    previous_trend: str,
) -> StructureEvent:
    if direction == "UP":
        event_direction = "BULLISH"
        trend_after = "BULLISH"

        if previous_trend == "BEARISH":
            event_type = "CHOCH"
            event_name = "CHOCH_UP"
        else:
            event_type = "BOS"
            event_name = "BOS_UP"

    elif direction == "DOWN":
        event_direction = "BEARISH"
        trend_after = "BEARISH"

        if previous_trend == "BULLISH":
            event_type = "CHOCH"
            event_name = "CHOCH_DOWN"
        else:
            event_type = "BOS"
            event_name = "BOS_DOWN"

    else:
        raise ValueError(
            f"Неизвестное направление пробоя: {direction}"
        )

    candle = rates[index]

    close_price = float(candle["close"])
    broken_level = float(broken_point.price)

    local_atr = calculate_atr(
        rates=rates,
        end_index=max(0, index - 1),
        period=14,
    )

    break_distance = abs(
        close_price - broken_level
    )

    break_distance_atr = (
        break_distance / local_atr
        if local_atr > 0
        else 0.0
    )

    event_time = int(candle["time"])

    event_id = (
        f"{event_name}_"
        f"{event_time}_"
        f"{broken_level:.10f}"
    )

    return StructureEvent(
        event_id=event_id,
        event=event_name,
        event_type=event_type,
        direction=event_direction,
        trend_before=previous_trend,
        trend_after=trend_after,
        index=index,
        time=event_time,
        close=close_price,
        broken_level=broken_level,
        broken_swing=broken_point,
        body_ratio=candle_body_ratio(candle),
        break_distance=break_distance,
        break_distance_atr=break_distance_atr,
        confirmed=True,
    )


def update_high_point(
    state: StructureState,
    point: StructurePoint,
) -> None:
    previous = state.last_high

    point.label = classify_high(
        current=point,
        previous=previous,
    )

    state.previous_high = previous
    state.last_high = point
    state.active_high = point
    state.high_broken = False

    if point.label == "HH":
        state.last_hh = point

    elif point.label == "LH":
        state.last_lh = point


def update_low_point(
    state: StructureState,
    point: StructurePoint,
) -> None:
    previous = state.last_low

    point.label = classify_low(
        current=point,
        previous=previous,
    )

    state.previous_low = previous
    state.last_low = point
    state.active_low = point
    state.low_broken = False

    if point.label == "HL":
        state.last_hl = point

    elif point.label == "LL":
        state.last_ll = point


def reset_structure_state(
    state: StructureState,
) -> None:
    state.trend = "RANGE"

    state.last_high = None
    state.previous_high = None

    state.last_low = None
    state.previous_low = None

    state.last_hh = None
    state.last_hl = None
    state.last_lh = None
    state.last_ll = None

    state.active_high = None
    state.active_low = None

    state.high_broken = False
    state.low_broken = False

    state.last_bos_event = None
    state.last_choch_event = None
    state.last_event = None

    state.last_processed_index = -1
    state.events.clear()


class StructureEngine:
    """
    Движок рыночной структуры.

    Он последовательно обрабатывает закрытые свечи,
    подтверждает swing high / swing low и фиксирует:

    - HH;
    - HL;
    - LH;
    - LL;
    - BOS;
    - CHOCH;
    - текущее направление структуры.

    Поиск Order Block, FVG, sweep и входов
    в этом модуле не выполняется.
    """

    def __init__(
        self,
        swing_length: int = 2,
        minimum_distance_atr: float = 0.10,
        minimum_body_ratio: float = 0.45,
        minimum_range_atr: float = 0.70,
        minimum_close_beyond_atr: float = 0.03,
    ) -> None:
        self.swing_length = validate_swing_length(
            swing_length
        )

        self.minimum_distance_atr = float(
            minimum_distance_atr
        )

        self.minimum_body_ratio = float(
            minimum_body_ratio
        )

        self.minimum_range_atr = float(
            minimum_range_atr
        )

        self.minimum_close_beyond_atr = float(
            minimum_close_beyond_atr
        )

        self.state = StructureState()

    def reset(self) -> None:
        reset_structure_state(self.state)

    def _candidate_swing_index(
        self,
        current_index: int,
    ) -> int:
        return (
            int(current_index)
            - self.swing_length
        )

    def _register_swing_high(
        self,
        rates: Any,
        candidate_index: int,
        local_atr: float,
    ) -> None:
        point = StructurePoint(
            index=candidate_index,
            time=int(
                rates[candidate_index]["time"]
            ),
            price=float(
                rates[candidate_index]["high"]
            ),
            kind="HIGH",
            atr=local_atr,
        )

        previous_high = self.state.last_high

        minimum_distance = (
            local_atr
            * self.minimum_distance_atr
        )

        if (
            previous_high is not None
            and swings_are_too_close(
                first_price=point.price,
                second_price=previous_high.price,
                minimum_distance=minimum_distance,
            )
        ):
            return

        update_high_point(
            state=self.state,
            point=point,
        )

    def _register_swing_low(
        self,
        rates: Any,
        candidate_index: int,
        local_atr: float,
    ) -> None:
        point = StructurePoint(
            index=candidate_index,
            time=int(
                rates[candidate_index]["time"]
            ),
            price=float(
                rates[candidate_index]["low"]
            ),
            kind="LOW",
            atr=local_atr,
        )

        previous_low = self.state.last_low

        minimum_distance = (
            local_atr
            * self.minimum_distance_atr
        )

        if (
            previous_low is not None
            and swings_are_too_close(
                first_price=point.price,
                second_price=previous_low.price,
                minimum_distance=minimum_distance,
            )
        ):
            return

        update_low_point(
            state=self.state,
            point=point,
        )

    def _try_register_swing(
        self,
        rates: Any,
        current_index: int,
    ) -> None:
        candidate_index = (
            self._candidate_swing_index(
                current_index
            )
        )

        if candidate_index < self.swing_length:
            return

        if (
            candidate_index
            + self.swing_length
            >= len(rates)
        ):
            return

        local_atr = calculate_atr(
            rates=rates,
            end_index=candidate_index,
            period=14,
        )

        if is_swing_high(
            rates=rates,
            index=candidate_index,
            swing_length=self.swing_length,
        ):
            self._register_swing_high(
                rates=rates,
                candidate_index=candidate_index,
                local_atr=local_atr,
            )

        if is_swing_low(
            rates=rates,
            index=candidate_index,
            swing_length=self.swing_length,
        ):
            self._register_swing_low(
                rates=rates,
                candidate_index=candidate_index,
                local_atr=local_atr,
            )

    def _bullish_break_is_valid(
        self,
        rates: Any,
        index: int,
    ) -> bool:
        active_high = self.state.active_high

        if active_high is None:
            return False

        if self.state.high_broken:
            return False

        if index <= active_high.index:
            return False

        if not close_crossed_level(
            rates=rates,
            index=index,
            level=active_high.price,
            direction="UP",
        ):
            return False

        return candle_has_displacement(
            rates=rates,
            index=index,
            direction="UP",
            minimum_body_ratio=(
                self.minimum_body_ratio
            ),
            minimum_range_atr=(
                self.minimum_range_atr
            ),
            minimum_close_beyond_atr=(
                self.minimum_close_beyond_atr
            ),
            broken_level=active_high.price,
        )

    def _bearish_break_is_valid(
        self,
        rates: Any,
        index: int,
    ) -> bool:
        active_low = self.state.active_low

        if active_low is None:
            return False

        if self.state.low_broken:
            return False

        if index <= active_low.index:
            return False

        if not close_crossed_level(
            rates=rates,
            index=index,
            level=active_low.price,
            direction="DOWN",
        ):
            return False

        return candle_has_displacement(
            rates=rates,
            index=index,
            direction="DOWN",
            minimum_body_ratio=(
                self.minimum_body_ratio
            ),
            minimum_range_atr=(
                self.minimum_range_atr
            ),
            minimum_close_beyond_atr=(
                self.minimum_close_beyond_atr
            ),
            broken_level=active_low.price,
        )

    def _apply_event(
        self,
        event: StructureEvent,
    ) -> None:
        self.state.trend = event.trend_after

        if event.direction == "BULLISH":
            self.state.high_broken = True
        else:
            self.state.low_broken = True

        self.state.add_event(event)

    def _detect_break(
        self,
        rates: Any,
        index: int,
    ) -> StructureEvent | None:
        bullish_valid = (
            self._bullish_break_is_valid(
                rates=rates,
                index=index,
            )
        )

        bearish_valid = (
            self._bearish_break_is_valid(
                rates=rates,
                index=index,
            )
        )

        if bullish_valid and bearish_valid:
            candle = rates[index]

            bullish_distance = abs(
                float(candle["close"])
                - float(
                    self.state.active_high.price
                )
            )

            bearish_distance = abs(
                float(candle["close"])
                - float(
                    self.state.active_low.price
                )
            )

            if bullish_distance >= bearish_distance:
                bearish_valid = False
            else:
                bullish_valid = False

        if bullish_valid:
            active_high = self.state.active_high

            if active_high is None:
                return None

            event = create_structure_event(
                rates=rates,
                index=index,
                direction="UP",
                broken_point=active_high,
                previous_trend=self.state.trend,
            )

            self._apply_event(event)
            return event

        if bearish_valid:
            active_low = self.state.active_low

            if active_low is None:
                return None

            event = create_structure_event(
                rates=rates,
                index=index,
                direction="DOWN",
                broken_point=active_low,
                previous_trend=self.state.trend,
            )

            self._apply_event(event)
            return event

        return None

    def process(
        self,
        rates: Any,
        use_last_closed_candle: bool = True,
    ) -> list[dict[str, Any]]:
        if rates is None:
            return []

        minimum_bars = (
            self.swing_length * 2 + 2
        )

        if len(rates) < minimum_bars:
            return []

        if use_last_closed_candle:
            last_index = len(rates) - 2
        else:
            last_index = len(rates) - 1

        if last_index < 0:
            return []

        start_index = max(
            self.state.last_processed_index + 1,
            self.swing_length * 2,
        )

        if start_index > last_index:
            return []

        events: list[dict[str, Any]] = []

        for index in range(
            start_index,
            last_index + 1,
        ):
            self._try_register_swing(
                rates=rates,
                current_index=index,
            )

            event = self._detect_break(
                rates=rates,
                index=index,
            )

            if event is not None:
                events.append(event.to_dict())

            self.state.last_processed_index = index

        return events
    def snapshot(
        self,
    ) -> dict[str, Any]:
        state = self.state

        return {
            "trend": state.trend,
            "direction": state.trend,

            "last_high": (
                state.last_high.to_dict()
                if state.last_high is not None
                else None
            ),
            "previous_high": (
                state.previous_high.to_dict()
                if state.previous_high is not None
                else None
            ),

            "last_low": (
                state.last_low.to_dict()
                if state.last_low is not None
                else None
            ),
            "previous_low": (
                state.previous_low.to_dict()
                if state.previous_low is not None
                else None
            ),

            "last_hh": (
                state.last_hh.to_dict()
                if state.last_hh is not None
                else None
            ),
            "last_hl": (
                state.last_hl.to_dict()
                if state.last_hl is not None
                else None
            ),
            "last_lh": (
                state.last_lh.to_dict()
                if state.last_lh is not None
                else None
            ),
            "last_ll": (
                state.last_ll.to_dict()
                if state.last_ll is not None
                else None
            ),

            "active_high": (
                state.active_high.to_dict()
                if state.active_high is not None
                else None
            ),
            "active_low": (
                state.active_low.to_dict()
                if state.active_low is not None
                else None
            ),

            "high_broken": state.high_broken,
            "low_broken": state.low_broken,

            "last_event": (
                state.last_event.to_dict()
                if state.last_event is not None
                else None
            ),
            "last_bos": (
                state.last_bos_event.to_dict()
                if state.last_bos_event is not None
                else None
            ),
            "last_choch": (
                state.last_choch_event.to_dict()
                if state.last_choch_event is not None
                else None
            ),

            "last_processed_index": (
                state.last_processed_index
            ),

            "events_count": len(state.events),
            "events": list(state.events),
        }

    def get_last_event(
        self,
    ) -> dict[str, Any] | None:
        event = self.state.last_event

        if event is None:
            return None

        return event.to_dict()

    def get_last_bos(
        self,
    ) -> dict[str, Any] | None:
        event = self.state.last_bos_event

        if event is None:
            return None

        return event.to_dict()

    def get_last_choch(
        self,
    ) -> dict[str, Any] | None:
        event = self.state.last_choch_event

        if event is None:
            return None

        return event.to_dict()

    def get_events(
        self,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        events = self.state.events

        if limit is None:
            return list(events)

        limit = max(0, int(limit))

        if limit == 0:
            return []

        return list(events[-limit:])

    def get_structure_confirmation(
        self,
        direction: str | None = None,
        require_bos: bool = False,
        require_choch: bool = False,
    ) -> dict[str, Any]:
        requested_direction = (
            direction.upper()
            if direction is not None
            else None
        )

        if requested_direction in {"BUY", "LONG", "UP"}:
            requested_direction = "BULLISH"

        elif requested_direction in {
            "SELL",
            "SHORT",
            "DOWN",
        }:
            requested_direction = "BEARISH"

        if (
            requested_direction is not None
            and requested_direction
            not in {"BULLISH", "BEARISH"}
        ):
            return {
                "confirmed": False,
                "reason": (
                    "INVALID_DIRECTION"
                ),
                "trend": self.state.trend,
                "direction": requested_direction,
                "event": None,
            }

        trend_matches = (
            requested_direction is None
            or self.state.trend
            == requested_direction
        )

        if not trend_matches:
            return {
                "confirmed": False,
                "reason": "TREND_MISMATCH",
                "trend": self.state.trend,
                "direction": requested_direction,
                "event": self.get_last_event(),
            }

        selected_event: StructureEvent | None

        if require_choch:
            selected_event = (
                self.state.last_choch_event
            )

        elif require_bos:
            selected_event = (
                self.state.last_bos_event
            )

        else:
            selected_event = (
                self.state.last_event
            )

        if selected_event is None:
            return {
                "confirmed": False,
                "reason": (
                    "NO_STRUCTURE_EVENT"
                ),
                "trend": self.state.trend,
                "direction": requested_direction,
                "event": None,
            }

        if (
            requested_direction is not None
            and selected_event.direction
            != requested_direction
        ):
            return {
                "confirmed": False,
                "reason": (
                    "EVENT_DIRECTION_MISMATCH"
                ),
                "trend": self.state.trend,
                "direction": requested_direction,
                "event": selected_event.to_dict(),
            }

        return {
            "confirmed": True,
            "reason": "CONFIRMED",
            "trend": self.state.trend,
            "direction": (
                requested_direction
                or selected_event.direction
            ),
            "event": selected_event.to_dict(),
            "event_type": (
                selected_event.event_type
            ),
            "event_id": selected_event.event_id,
            "broken_level": (
                selected_event.broken_level
            ),
            "index": selected_event.index,
            "time": selected_event.time,
        }


def normalize_direction(
    direction: str | None,
) -> str | None:
    if direction is None:
        return None

    normalized = str(direction).upper()

    if normalized in {
        "BUY",
        "LONG",
        "BULL",
        "BULLISH",
        "UP",
    }:
        return "BULLISH"

    if normalized in {
        "SELL",
        "SHORT",
        "BEAR",
        "BEARISH",
        "DOWN",
    }:
        return "BEARISH"

    return None


def detect_structure_trend(
    swing_highs: list[dict[str, Any]],
    swing_lows: list[dict[str, Any]],
) -> str:
    if (
        len(swing_highs) < 2
        or len(swing_lows) < 2
    ):
        return "RANGE"

    previous_high = float(
        swing_highs[-2]["price"]
    )
    current_high = float(
        swing_highs[-1]["price"]
    )

    previous_low = float(
        swing_lows[-2]["price"]
    )
    current_low = float(
        swing_lows[-1]["price"]
    )

    higher_high = (
        current_high > previous_high
    )
    higher_low = (
        current_low > previous_low
    )

    lower_high = (
        current_high < previous_high
    )
    lower_low = (
        current_low < previous_low
    )

    if higher_high and higher_low:
        return "BULLISH"

    if lower_high and lower_low:
        return "BEARISH"

    return "RANGE"


def get_structure_confirmation(
    rates: Any,
    direction: str | None = None,
    swing_length: int = 2,
    minimum_distance_atr: float = 0.10,
    minimum_body_ratio: float = 0.45,
    minimum_range_atr: float = 0.70,
    minimum_close_beyond_atr: float = 0.03,
    use_last_closed_candle: bool = True,
) -> dict[str, Any]:
    """
    Одноразовая совместимая функция для модулей,
    которые пока не используют постоянный экземпляр
    StructureEngine.

    Для последовательного бэктеста лучше создавать
    один StructureEngine и вызывать process() по мере
    появления новых свечей.
    """

    normalized_direction = normalize_direction(
        direction
    )

    if (
        direction is not None
        and normalized_direction is None
    ):
        return {
            "confirmed": False,
            "reason": "INVALID_DIRECTION",
            "trend": "RANGE",
            "direction": direction,
            "event": None,
        }

    engine = StructureEngine(
        swing_length=swing_length,
        minimum_distance_atr=(
            minimum_distance_atr
        ),
        minimum_body_ratio=(
            minimum_body_ratio
        ),
        minimum_range_atr=(
            minimum_range_atr
        ),
        minimum_close_beyond_atr=(
            minimum_close_beyond_atr
        ),
    )

    engine.process(
        rates=rates,
        use_last_closed_candle=(
            use_last_closed_candle
        ),
    )

    return engine.get_structure_confirmation(
        direction=normalized_direction,
    )


def build_structure_snapshot(
    rates: Any,
    swing_length: int = 2,
    minimum_distance_atr: float = 0.10,
    minimum_body_ratio: float = 0.45,
    minimum_range_atr: float = 0.70,
    minimum_close_beyond_atr: float = 0.03,
    use_last_closed_candle: bool = True,
) -> dict[str, Any]:
    engine = StructureEngine(
        swing_length=swing_length,
        minimum_distance_atr=(
            minimum_distance_atr
        ),
        minimum_body_ratio=(
            minimum_body_ratio
        ),
        minimum_range_atr=(
            minimum_range_atr
        ),
        minimum_close_beyond_atr=(
            minimum_close_beyond_atr
        ),
    )

    engine.process(
        rates=rates,
        use_last_closed_candle=(
            use_last_closed_candle
        ),
    )

    return engine.snapshot()


__all__ = [
    "StructurePoint",
    "StructureEvent",
    "StructureState",
    "StructureEngine",
    "calculate_atr",
    "calculate_true_range",
    "candle_body",
    "candle_body_ratio",
    "candle_direction",
    "candle_has_displacement",
    "candle_range",
    "close_crossed_level",
    "detect_structure_trend",
    "find_swings",
    "get_structure_confirmation",
    "build_structure_snapshot",
    "is_swing_high",
    "is_swing_low",
    "normalize_direction",
]    