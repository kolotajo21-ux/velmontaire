from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Iterable, Optional


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class TradeOutcome(str, Enum):
    WIN = "WIN"
    LOSS = "LOSS"
    BREAK_EVEN = "BREAK_EVEN"
    OPEN = "OPEN"
    NOT_TRIGGERED = "NOT_TRIGGERED"


@dataclass
class SimulationConfig:
    break_even_trigger_r: Optional[float] = 1.0
    pending_expiry_bars: Optional[int] = 24
    intrabar_priority: str = "STOP_FIRST"

    def __post_init__(self) -> None:
        if self.intrabar_priority not in {"STOP_FIRST", "TARGET_FIRST"}:
            raise ValueError("intrabar_priority должен быть STOP_FIRST или TARGET_FIRST")
        if self.break_even_trigger_r is not None and self.break_even_trigger_r <= 0:
            raise ValueError("break_even_trigger_r должен быть больше 0 или None")
        if self.pending_expiry_bars is not None and self.pending_expiry_bars < 1:
            raise ValueError("pending_expiry_bars должен быть не меньше 1 или None")


@dataclass
class SimulatedTrade:
    direction: str
    order_type: str
    entry: float
    stop_loss: float
    take_profit: float
    initial_stop_loss: float
    initial_risk: float
    rr: float
    break_even_trigger_r: Optional[float] = None
    status: OrderStatus = OrderStatus.PENDING
    outcome: TradeOutcome = TradeOutcome.NOT_TRIGGERED
    signal_time: Optional[int] = None
    open_time: Optional[int] = None
    pending_end_time: Optional[int] = None
    close_time: Optional[int] = None
    open_bar_index: Optional[int] = None
    close_bar_index: Optional[int] = None
    close_price: Optional[float] = None
    result_r: float = 0.0
    bars_waited: int = 0
    bars_in_trade: int = 0
    break_even_armed: bool = False
    break_even_moved: bool = False

    # Диагностика отложенного ордера
    closest_distance_to_entry: Optional[float] = None
    closest_distance_r: Optional[float] = None
    closest_price: Optional[float] = None
    closest_bar_index: Optional[int] = None
    closest_time: Optional[int] = None
    max_favorable_price: Optional[float] = None
    max_adverse_price: Optional[float] = None
    bars_until_touch: Optional[int] = None
    touched_after_expiry: bool = False
    bars_after_expiry_until_touch: Optional[int] = None
    touch_time_after_expiry: Optional[int] = None
    expired_reason: str = ""

    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["status"] = self.status.value
        result["outcome"] = self.outcome.value
        return result


class TradeSimulator:
    VALID_DIRECTIONS = {"BULLISH", "BEARISH"}
    VALID_ORDER_TYPES = {"BUY", "SELL", "BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP"}

    def __init__(self, config: Optional[SimulationConfig] = None) -> None:
        self.config = config or SimulationConfig()

    @staticmethod
    def _get_float(mapping: dict[str, Any], key: str) -> float:
        if key not in mapping:
            raise KeyError(f"В данных отсутствует поле: {key}")
        return float(mapping[key])

    def create_trade(self, trade: dict[str, Any], signal_time: Optional[int] = None) -> SimulatedTrade:
        direction = str(trade.get("direction", "")).upper()
        order_type = str(trade.get("order_type", "")).upper()
        if direction not in self.VALID_DIRECTIONS:
            raise ValueError("direction должен быть BULLISH или BEARISH")
        if order_type not in self.VALID_ORDER_TYPES:
            raise ValueError(f"Неподдерживаемый order_type: {order_type}")

        entry = self._get_float(trade, "entry")
        stop_loss = self._get_float(trade, "stop_loss")
        take_profit = self._get_float(trade, "take_profit")
        initial_risk = entry - stop_loss if direction == "BULLISH" else stop_loss - entry
        if initial_risk <= 0:
            raise ValueError("Некорректное положение Stop Loss относительно Entry")
        if direction == "BULLISH" and take_profit <= entry:
            raise ValueError("Для BULLISH Take Profit должен быть выше Entry")
        if direction == "BEARISH" and take_profit >= entry:
            raise ValueError("Для BEARISH Take Profit должен быть ниже Entry")

        calculated_rr = abs(take_profit - entry) / initial_risk
        rr = float(trade.get("rr", calculated_rr))

        # Восстановлено: BE берётся как есть. Принудительного max(2.0, ...) нет.
        if trade.get("break_even_trigger_r") is not None:
            be_trigger = float(trade["break_even_trigger_r"])
        elif self.config.break_even_trigger_r is not None:
            be_trigger = float(self.config.break_even_trigger_r)
        else:
            be_trigger = None

        return SimulatedTrade(
            direction=direction,
            order_type=order_type,
            entry=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
            initial_stop_loss=stop_loss,
            initial_risk=initial_risk,
            rr=rr,
            break_even_trigger_r=be_trigger,
            signal_time=signal_time,
        )

    @staticmethod
    def _candle_time(candle: Any) -> int:
        return int(candle["time"])

    @staticmethod
    def _ohlc(candle: Any) -> tuple[float, float, float, float]:
        return float(candle["open"]), float(candle["high"]), float(candle["low"]), float(candle["close"])

    @staticmethod
    def _is_buy(trade: SimulatedTrade) -> bool:
        return trade.direction == "BULLISH"

    def _entry_triggered(self, trade: SimulatedTrade, candle: Any) -> bool:
        _, high, low, _ = self._ohlc(candle)
        if trade.order_type == "BUY_LIMIT": return low <= trade.entry
        if trade.order_type == "SELL_LIMIT": return high >= trade.entry
        if trade.order_type == "BUY_STOP": return high >= trade.entry
        if trade.order_type == "SELL_STOP": return low <= trade.entry
        return trade.order_type in {"BUY", "SELL"}

    def _execution_price(
        self,
        trade: SimulatedTrade,
        candle: Any,
    ) -> float:
        open_price, _, _, _ = self._ohlc(
            candle
        )

        # Рыночный ордер исполняется по Open.
        if trade.order_type in {
            "BUY",
            "SELL",
        }:
            return open_price

        # Лимитные ордера в тестере исполняем
        # строго по заявленной Entry.
        # Это не позволяет сломать SL и фактический риск
        # при гэпе через лимитную цену.
        if trade.order_type in {
            "BUY_LIMIT",
            "SELL_LIMIT",
        }:
            return trade.entry

        # Стоп-ордера могут получить худшее исполнение
        # при открытии свечи за уровнем.
        if (
            trade.order_type == "BUY_STOP"
            and open_price > trade.entry
        ):
            return open_price

        if (
            trade.order_type == "SELL_STOP"
            and open_price < trade.entry
        ):
            return open_price

        return trade.entry
    def _pending_distance_to_entry(self, trade: SimulatedTrade, candle: Any) -> tuple[float, float]:
        """
        Возвращает:
        - абсолютное минимальное расстояние свечи до Entry;
        - ближайшую к Entry цену свечи.

        Для BUY_LIMIT рынок должен снизиться до Entry, поэтому используется Low.
        Для SELL_LIMIT рынок должен вырасти до Entry, поэтому используется High.
        Для стоп-ордеров логика зеркальная.
        """
        _, high, low, _ = self._ohlc(candle)

        if trade.order_type == "BUY_LIMIT":
            nearest_price = low
            distance = max(0.0, low - trade.entry)
        elif trade.order_type == "SELL_LIMIT":
            nearest_price = high
            distance = max(0.0, trade.entry - high)
        elif trade.order_type == "BUY_STOP":
            nearest_price = high
            distance = max(0.0, trade.entry - high)
        elif trade.order_type == "SELL_STOP":
            nearest_price = low
            distance = max(0.0, low - trade.entry)
        else:
            nearest_price = trade.entry
            distance = 0.0

        return float(distance), float(nearest_price)

    def _update_pending_diagnostics(
        self,
        trade: SimulatedTrade,
        candle: Any,
        bar_index: int,
    ) -> None:
        _, high, low, _ = self._ohlc(candle)

        # Экстремумы, достигнутые рынком во время ожидания ордера.
        if trade.max_favorable_price is None:
            trade.max_favorable_price = low if trade.order_type in {"BUY_LIMIT", "SELL_STOP"} else high
        else:
            if trade.order_type in {"BUY_LIMIT", "SELL_STOP"}:
                trade.max_favorable_price = min(trade.max_favorable_price, low)
            else:
                trade.max_favorable_price = max(trade.max_favorable_price, high)

        if trade.max_adverse_price is None:
            trade.max_adverse_price = high if trade.order_type in {"BUY_LIMIT", "SELL_STOP"} else low
        else:
            if trade.order_type in {"BUY_LIMIT", "SELL_STOP"}:
                trade.max_adverse_price = max(trade.max_adverse_price, high)
            else:
                trade.max_adverse_price = min(trade.max_adverse_price, low)

        distance, nearest_price = self._pending_distance_to_entry(trade, candle)

        if (
            trade.closest_distance_to_entry is None
            or distance < trade.closest_distance_to_entry
        ):
            trade.closest_distance_to_entry = distance
            trade.closest_distance_r = (
                distance / trade.initial_risk if trade.initial_risk > 0 else None
            )
            trade.closest_price = nearest_price
            trade.closest_bar_index = bar_index
            trade.closest_time = self._candle_time(candle)

    @staticmethod
    def _classify_expired_reason(trade: SimulatedTrade) -> str:
        distance_r = trade.closest_distance_r

        if distance_r is None:
            return "NO_DIAGNOSTIC_DATA"
        if distance_r <= 0.10:
            return "TOO_DEEP_ENTRY"
        if distance_r <= 0.50:
            return "PRICE_CAME_CLOSE"
        if distance_r <= 1.00:
            return "TIME_EXPIRED"
        return "NEVER_CAME_CLOSE"

    def _scan_touch_after_expiry(
        self,
        trade: SimulatedTrade,
        candles: list[Any],
        expiry_index: int,
    ) -> None:
        """
        После истечения ордера смотрим оставшуюся историю и отмечаем,
        коснулась ли цена Entry позднее. Это не активирует сделку и
        используется только для диагностики.
        """
        for future_index in range(expiry_index + 1, len(candles)):
            candle = candles[future_index]
            if self._entry_triggered(trade, candle):
                trade.touched_after_expiry = True
                trade.bars_after_expiry_until_touch = future_index - expiry_index
                trade.touch_time_after_expiry = self._candle_time(candle)
                trade.expired_reason = "TOUCHED_AFTER_EXPIRY"
                return

    def _activate_trade(self, trade: SimulatedTrade, candle: Any, bar_index: int) -> None:
        trade.bars_until_touch = trade.bars_waited
        trade.closest_distance_to_entry = 0.0
        trade.closest_distance_r = 0.0
        trade.closest_price = trade.entry
        trade.closest_bar_index = bar_index
        trade.closest_time = self._candle_time(candle)

        trade.entry = self._execution_price(trade, candle)
        trade.status = OrderStatus.OPEN
        trade.outcome = TradeOutcome.OPEN
        trade.open_time = self._candle_time(candle)
        trade.pending_end_time = trade.open_time
        trade.open_bar_index = bar_index
        trade.reason = "Ордер активирован"

    def _target_hit(self, trade: SimulatedTrade, candle: Any) -> bool:
        _, high, low, _ = self._ohlc(candle)
        return high >= trade.take_profit if self._is_buy(trade) else low <= trade.take_profit

    def _stop_hit(self, trade: SimulatedTrade, candle: Any) -> bool:
        _, high, low, _ = self._ohlc(candle)
        return low <= trade.stop_loss if self._is_buy(trade) else high >= trade.stop_loss

    def _break_even_triggered(self, trade: SimulatedTrade, candle: Any) -> bool:
        if trade.break_even_trigger_r is None:
            return False
        _, high, low, _ = self._ohlc(candle)
        trigger = trade.initial_risk * trade.break_even_trigger_r
        return high >= trade.entry + trigger if self._is_buy(trade) else low <= trade.entry - trigger

    @staticmethod
    def _move_to_break_even(trade: SimulatedTrade) -> None:
        trade.stop_loss = trade.entry
        trade.break_even_armed = True
        trade.break_even_moved = True

    def _close_trade(self, trade: SimulatedTrade, candle: Any, bar_index: int,
                     close_price: float, outcome: TradeOutcome, reason: str) -> None:
        trade.status = OrderStatus.CLOSED
        trade.outcome = outcome
        trade.close_time = self._candle_time(candle)
        trade.close_bar_index = bar_index
        trade.close_price = float(close_price)
        trade.reason = reason
        if outcome == TradeOutcome.WIN:
            trade.result_r = round(abs(trade.take_profit - trade.entry) / trade.initial_risk, 4)
        elif outcome == TradeOutcome.LOSS:
            trade.result_r = round(-abs(trade.entry - trade.initial_stop_loss) / trade.initial_risk, 4)
        else:
            trade.result_r = 0.0

    def _resolve_exit(self, trade: SimulatedTrade, candle: Any, bar_index: int) -> bool:
        stop_hit = self._stop_hit(trade, candle)
        target_hit = self._target_hit(trade, candle)
        if stop_hit and target_hit:
            if self.config.intrabar_priority == "STOP_FIRST":
                outcome = TradeOutcome.BREAK_EVEN if trade.stop_loss == trade.entry else TradeOutcome.LOSS
                self._close_trade(trade, candle, bar_index, trade.stop_loss, outcome,
                                  "SL и TP задеты в одной свече; применён STOP_FIRST")
            else:
                self._close_trade(trade, candle, bar_index, trade.take_profit, TradeOutcome.WIN,
                                  "SL и TP задеты в одной свече; применён TARGET_FIRST")
            return True
        if stop_hit:
            outcome = TradeOutcome.BREAK_EVEN if trade.stop_loss == trade.entry else TradeOutcome.LOSS
            self._close_trade(trade, candle, bar_index, trade.stop_loss, outcome,
                              "Закрыто в безубыток" if outcome == TradeOutcome.BREAK_EVEN else "Закрыто по Stop Loss")
            return True
        if target_hit:
            self._close_trade(trade, candle, bar_index, trade.take_profit, TradeOutcome.WIN, "Закрыто по Take Profit")
            return True
        return False

    def _process_open_candle(self, trade: SimulatedTrade, candle: Any, bar_index: int) -> None:
        trade.bars_in_trade += 1
        if self._resolve_exit(trade, candle, bar_index):
            return
        if not trade.break_even_moved and self._break_even_triggered(trade, candle):
            self._move_to_break_even(trade)

    def simulate(self, trade_data: dict[str, Any], candles: Iterable[Any],
                 signal_time: Optional[int] = None) -> SimulatedTrade:
        trade = self.create_trade(trade_data, signal_time)
        candle_list = list(candles)
        expiry_bar_index: Optional[int] = None

        for bar_index, candle in enumerate(candle_list):
            if trade.status == OrderStatus.PENDING:
                trade.bars_waited += 1
                self._update_pending_diagnostics(trade, candle, bar_index)

                if self._entry_triggered(trade, candle):
                    self._activate_trade(trade, candle, bar_index)
                    self._process_open_candle(trade, candle, bar_index)
                    if trade.status == OrderStatus.CLOSED:
                        break

                elif (
                    self.config.pending_expiry_bars is not None
                    and trade.bars_waited >= self.config.pending_expiry_bars
                ):
                    trade.status = OrderStatus.EXPIRED
                    trade.outcome = TradeOutcome.NOT_TRIGGERED
                    trade.pending_end_time = self._candle_time(candle)
                    trade.expired_reason = self._classify_expired_reason(trade)
                    trade.reason = (
                        "Срок действия отложенного ордера истёк; "
                        f"причина: {trade.expired_reason}"
                    )
                    expiry_bar_index = bar_index
                    break

            elif trade.status == OrderStatus.OPEN:
                self._process_open_candle(trade, candle, bar_index)
                if trade.status == OrderStatus.CLOSED:
                    break

        if trade.status == OrderStatus.EXPIRED and expiry_bar_index is not None:
            self._scan_touch_after_expiry(trade, candle_list, expiry_bar_index)
            if trade.touched_after_expiry:
                trade.reason = (
                    "Ордер истёк, но Entry был достигнут позже; "
                    f"через {trade.bars_after_expiry_until_touch} баров"
                )

        elif trade.status == OrderStatus.PENDING:
            trade.outcome = TradeOutcome.NOT_TRIGGERED
            if candle_list:
                trade.pending_end_time = self._candle_time(candle_list[-1])
            trade.expired_reason = self._classify_expired_reason(trade)
            trade.reason = (
                "Ордер не активирован до конца истории; "
                f"диагностика: {trade.expired_reason}"
            )

        elif trade.status == OrderStatus.OPEN:
            trade.outcome = TradeOutcome.OPEN
            trade.reason = "Сделка осталась открытой до конца истории"

        return trade