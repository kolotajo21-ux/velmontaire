import time

import MetaTrader5 as mt5

from config import (
    SYMBOL,
    H1_CANDLES,
    M5_CANDLES,
    SWING_LENGTH,
)

from market_data import connect_mt5, get_rates
from structure import StructureEngine
from concepts.liquidity import detect_liquidity_sweep
from choch import detect_choch
from bos import detect_bos_after_choch
from signal_engine import SignalState

from entry_calculator import (
    find_m5_order_block,
    calculate_trade_levels,
)

# У тебя файл называется riskmanager.py
from riskmanager import calculate_position_size

from execution.executor import (
    build_pending_request,
    send_pending_order_safely,
    cancel_expired_bot_orders,
    has_open_position,
    get_bot_pending_orders,
)

from position_manager import manage_break_even

from logs.logger import (
    info,
    success,
    warning,
    error,
)

from trade_journal import (
    add_trade,
    update_trade_status,
)


CHECK_INTERVAL_SECONDS = 5
RISK_PERCENT = 0.5
RR = 3.0
ORDER_EXPIRY_MINUTES = 30

# False — только анализ и сохранение сигналов.
# True — отправка ордеров на подключённый счёт.
AUTO_TRADE = False


def refresh_h1_structure(
    structure_engine,
    h1_rates,
    last_closed_h1_time,
):
    """
    Обновляет H1 StructureEngine только при появлении новой
    полностью закрытой H1-свечи.

    get_rates обычно возвращает скользящее окно одинаковой длины.
    Поэтому при новой H1-свече движок сбрасывается и заново
    прогоняет доступную закрытую историю, чтобы индексы структуры
    не смещались относительно состояния.
    """
    if h1_rates is None or len(h1_rates) < 10:
        return "RANGE", last_closed_h1_time, []

    closed_h1_time = int(h1_rates[-2]["time"])

    if closed_h1_time == last_closed_h1_time:
        snapshot = structure_engine.snapshot()
        return (
            str(snapshot.get("trend", "RANGE")),
            last_closed_h1_time,
            [],
        )

    structure_engine.reset()

    events = structure_engine.process(
        h1_rates,
        use_last_closed_candle=True,
    )
    snapshot = structure_engine.snapshot()

    return (
        str(snapshot.get("trend", "RANGE")),
        closed_h1_time,
        events,
    )


def log_status(
    account_balance,
    h1_trend,
    stage,
):
    info("=====================================")
    info("SMC BOT STATUS")
    info(f"Symbol: {SYMBOL}")
    info(f"H1 Trend: {h1_trend}")
    info(f"Stage: {stage}")
    info(f"Balance: ${account_balance}")
    info(f"Risk: {RISK_PERCENT}%")
    info(f"RR: 1:{RR}")
    info(f"AutoTrade: {AUTO_TRADE}")
    info("=====================================")


def log_trade_signal(trade, risk):
    success("========== ГОТОВЫЙ СИГНАЛ ==========")
    info(f"Тип ордера: {trade['order_type']}")
    info(f"Направление: {trade['direction']}")
    info(f"Entry: {trade['entry']}")
    info(f"Stop Loss: {trade['stop_loss']}")
    info(f"Take Profit: {trade['take_profit']}")
    info(f"RR: 1:{trade['rr']}")
    info(f"Lot: {risk['lot']}")
    info(f"Risk: ${risk['risk_money']}")
    info(f"Stop: {risk['stop_pips']} pips")
    success("=====================================")


def entry_is_valid_now(trade):
    tick = mt5.symbol_info_tick(SYMBOL)

    if tick is None:
        error("Не удалось получить текущую цену")
        return False

    if trade["order_type"] == "BUY_LIMIT":
        if float(trade["entry"]) >= float(tick.ask):
            warning(
                "BUY LIMIT невалиден: "
                "Entry должен быть ниже текущей Ask"
            )
            return False

    elif trade["order_type"] == "SELL_LIMIT":
        if float(trade["entry"]) <= float(tick.bid):
            warning(
                "SELL LIMIT невалиден: "
                "Entry должен быть выше текущей Bid"
            )
            return False

    else:
        error(
            f"Неизвестный тип ордера: "
            f"{trade['order_type']}"
        )
        return False

    return True


def reset_setup(state, reason):
    warning(f"Сетап сброшен. Причина: {reason}")
    state.reset()


def save_signal_to_journal(trade, risk):
    trade_id = add_trade(
        symbol=SYMBOL,
        direction=trade["direction"],
        order_type=trade["order_type"],
        entry=trade["entry"],
        stop_loss=trade["stop_loss"],
        take_profit=trade["take_profit"],
        lot=risk["lot"],
        risk_percent=RISK_PERCENT,
        risk_money=risk["risk_money"],
        rr=trade["rr"],
        status="SIGNAL",
        comment="Сигнал рассчитан ботом",
    )

    success(
        f"Сигнал сохранён в журнале"
        f" | ID: {trade_id}"
    )

    return trade_id


def main():
    if not connect_mt5():
        error("Не удалось подключиться к MT5")
        raise SystemExit

    account = mt5.account_info()

    if account is None:
        error("Не удалось получить данные торгового счёта")
        mt5.shutdown()
        raise SystemExit

    state = SignalState()
    structure_engine = StructureEngine(
        swing_length=SWING_LENGTH,
        minimum_distance_atr=0.10,
        minimum_body_ratio=0.45,
        minimum_range_atr=0.70,
    )

    active_direction = None
    last_closed_m5_time = None
    last_closed_h1_time = None

    info("========== SMC BOT ЗАПУЩЕН ==========")
    info(f"Символ: {SYMBOL}")
    info(f"Баланс: ${account.balance}")
    info(f"Риск: {RISK_PERCENT}%")
    info(f"RR: 1:{RR}")
    info(f"Автоторговля: {AUTO_TRADE}")
    info("Остановка: Ctrl + C")
    info("=====================================")

    try:
        while True:
            # Сопровождение открытых позиций
            try:
                moved_to_be = manage_break_even(
                    symbol=SYMBOL,
                    trigger_r=1.0,
                )

                if moved_to_be > 0:
                    success(
                        f"Перенесено позиций в безубыток: "
                        f"{moved_to_be}"
                    )

            except Exception as exc:
                error(
                    f"Ошибка сопровождения позиций: {exc}"
                )

            # Удаление просроченных лимиток
            try:
                cancelled = cancel_expired_bot_orders(
                    symbol=SYMBOL,
                    max_age_minutes=ORDER_EXPIRY_MINUTES,
                )

                if cancelled > 0:
                    warning(
                        f"Удалено просроченных ордеров: "
                        f"{cancelled}"
                    )

            except Exception as exc:
                error(
                    f"Ошибка проверки старых ордеров: {exc}"
                )

            h1_rates = get_rates(
                SYMBOL,
                mt5.TIMEFRAME_H1,
                H1_CANDLES,
            )

            m5_rates = get_rates(
                SYMBOL,
                mt5.TIMEFRAME_M5,
                M5_CANDLES,
            )

            if h1_rates is None or m5_rates is None:
                error("Не удалось получить рыночные данные")
                time.sleep(CHECK_INTERVAL_SECONDS)
                continue

            if len(h1_rates) < 10 or len(m5_rates) < 10:
                warning("Недостаточно свечей для анализа")
                time.sleep(CHECK_INTERVAL_SECONDS)
                continue

            # Последняя полностью закрытая свеча M5
            closed_m5_time = int(m5_rates[-2]["time"])

            # Одну свечу не обрабатываем повторно
            if closed_m5_time == last_closed_m5_time:
                time.sleep(CHECK_INTERVAL_SECONDS)
                continue

            last_closed_m5_time = closed_m5_time

            (
                h1_trend,
                last_closed_h1_time,
                new_structure_events,
            ) = refresh_h1_structure(
                structure_engine=structure_engine,
                h1_rates=h1_rates,
                last_closed_h1_time=last_closed_h1_time,
            )

            for structure_event in new_structure_events:
                event_name = str(
                    structure_event.get("event", "UNKNOWN")
                )
                event_time = int(
                    structure_event.get("time", 0)
                )
                broken_level = structure_event.get(
                    "broken_level"
                )

                success(
                    f"H1 Structure: {event_name}"
                    f" | Time: {event_time}"
                    f" | Level: {broken_level}"
                )

            account = mt5.account_info()

            if account is None:
                error("Не удалось обновить данные счёта")
                time.sleep(CHECK_INTERVAL_SECONDS)
                continue

            info(
                f"Новая M5 свеча: {closed_m5_time}"
                f" | H1: {h1_trend}"
                f" | Stage: {state.stage}"
            )

            log_status(
                account_balance=account.balance,
                h1_trend=h1_trend,
                stage=state.stage,
            )

            if h1_trend not in ("BULLISH", "BEARISH"):
                warning("H1 находится в RANGE")

                if state.stage != "WAIT_SWEEP":
                    reset_setup(
                        state,
                        "H1 перешёл в RANGE",
                    )

                active_direction = None
                time.sleep(CHECK_INTERVAL_SECONDS)
                continue

            # Сброс сетапа при изменении H1-направления
            if (
                active_direction is not None
                and active_direction != h1_trend
            ):
                reset_setup(
                    state,
                    (
                        f"направление H1 изменилось "
                        f"с {active_direction} "
                        f"на {h1_trend}"
                    ),
                )

            active_direction = h1_trend

            # 1. Liquidity Sweep
            if state.stage == "WAIT_SWEEP":
                sweep = detect_liquidity_sweep(
                    m5_rates,
                    active_direction,
                    SWING_LENGTH,
                )

                if sweep is None:
                    info("Liquidity Sweep пока не найден")

                else:
                    state.register_sweep(sweep)

                    success(
                        f"Найден Liquidity Sweep"
                        f" | Type: {sweep['type']}"
                        f" | Time: {sweep['time']}"
                    )

                    info(
                        f"Следующая стадия: {state.stage}"
                    )

            # 2. CHOCH
            elif state.stage == "WAIT_CHOCH":
                choch = detect_choch(
                    m5_rates,
                    active_direction,
                    SWING_LENGTH,
                )

                if choch is None:
                    info("CHOCH пока не найден")

                else:
                    registered = state.register_choch(
                        choch
                    )

                    if registered:
                        success(
                            f"Найден CHOCH"
                            f" | Type: {choch['type']}"
                            f" | Time: {choch['time']}"
                        )

                        info(
                            f"Следующая стадия: "
                            f"{state.stage}"
                        )

            # 3. BOS
            elif state.stage == "WAIT_BOS":
                if state.choch is None:
                    reset_setup(
                        state,
                        "нет сохранённого CHOCH",
                    )
                    time.sleep(CHECK_INTERVAL_SECONDS)
                    continue

                bos = detect_bos_after_choch(
                    m5_rates,
                    active_direction,
                    state.choch["time"],
                    SWING_LENGTH,
                )

                if bos is None:
                    info("BOS после CHOCH пока не найден")

                else:
                    registered = state.register_bos(bos)

                    if registered:
                        success(
                            f"Найден BOS"
                            f" | Type: {bos['type']}"
                            f" | Time: {bos['time']}"
                        )

                        info(
                            f"Следующая стадия: "
                            f"{state.stage}"
                        )

            if not state.is_ready():
                time.sleep(CHECK_INTERVAL_SECONDS)
                continue

            success("Полное M5-подтверждение найдено")

            if (
                state.sweep is None
                or state.choch is None
                or state.bos is None
                or state.direction is None
            ):
                reset_setup(
                    state,
                    "неполные данные State Machine",
                )
                time.sleep(CHECK_INTERVAL_SECONDS)
                continue

            m5_order_block = find_m5_order_block(
                rates=m5_rates,
                direction=state.direction,
                choch_time=state.choch["time"],
                bos_time=state.bos["time"],
            )

            if m5_order_block is None:
                reset_setup(
                    state,
                    "M5 Order Block не найден",
                )
                time.sleep(CHECK_INTERVAL_SECONDS)
                continue

            success(
                f"M5 Order Block найден"
                f" | High: {m5_order_block['high']}"
                f" | Low: {m5_order_block['low']}"
            )

            trade = calculate_trade_levels(
                direction=state.direction,
                order_block=m5_order_block,
                sweep=state.sweep,
                rr=RR,
            )

            if trade is None:
                reset_setup(
                    state,
                    "не удалось рассчитать Entry, SL и TP",
                )
                time.sleep(CHECK_INTERVAL_SECONDS)
                continue

            risk = calculate_position_size(
                balance=float(account.balance),
                risk_percent=RISK_PERCENT,
                entry=trade["entry"],
                stop_loss=trade["stop_loss"],
            )

            if risk is None:
                reset_setup(
                    state,
                    "Risk Manager вернул пустой результат",
                )
                time.sleep(CHECK_INTERVAL_SECONDS)
                continue

            if risk["lot"] <= 0:
                reset_setup(
                    state,
                    "размер лота меньше или равен нулю",
                )
                time.sleep(CHECK_INTERVAL_SECONDS)
                continue

            log_trade_signal(trade, risk)

            # Сохраняем рассчитанный сигнал в базу данных
            trade_id = save_signal_to_journal(
                trade,
                risk,
            )

            if not entry_is_valid_now(trade):
                update_trade_status(
                    trade_id=trade_id,
                    status="REJECTED",
                    comment="Цена Entry уже невалидна",
                )

                reset_setup(
                    state,
                    "цена Entry уже невалидна",
                )
                time.sleep(CHECK_INTERVAL_SECONDS)
                continue

            if has_open_position(SYMBOL):
                update_trade_status(
                    trade_id=trade_id,
                    status="REJECTED",
                    comment="Уже существует открытая позиция",
                )

                reset_setup(
                    state,
                    f"по {SYMBOL} уже есть позиция",
                )
                time.sleep(CHECK_INTERVAL_SECONDS)
                continue

            existing_orders = get_bot_pending_orders(
                SYMBOL
            )

            if existing_orders:
                update_trade_status(
                    trade_id=trade_id,
                    status="REJECTED",
                    comment="Уже существует лимитный ордер",
                )

                reset_setup(
                    state,
                    f"по {SYMBOL} уже есть лимитка бота",
                )
                time.sleep(CHECK_INTERVAL_SECONDS)
                continue

            request = build_pending_request(
                symbol=SYMBOL,
                order_type=trade["order_type"],
                entry=trade["entry"],
                stop_loss=trade["stop_loss"],
                take_profit=trade["take_profit"],
                lot=risk["lot"],
            )

            if request is None:
                update_trade_status(
                    trade_id=trade_id,
                    status="ERROR",
                    comment=(
                        "Не удалось создать "
                        "торговый запрос"
                    ),
                )

                reset_setup(
                    state,
                    "не удалось создать торговый запрос",
                )
                time.sleep(CHECK_INTERVAL_SECONDS)
                continue

            if AUTO_TRADE:
                result = send_pending_order_safely(
                    request
                )

                if result is not None:
                    update_trade_status(
                        trade_id=trade_id,
                        status="PENDING",
                        ticket=int(result.order),
                        comment=(
                            "Лимитный ордер "
                            "успешно установлен"
                        ),
                    )

                    success(
                        f"Ордер отправлен"
                        f" | Ticket: {result.order}"
                    )

                else:
                    update_trade_status(
                        trade_id=trade_id,
                        status="ERROR",
                        comment="Ордер не был отправлен",
                    )

                    error("Ордер не был отправлен")

            else:
                update_trade_status(
                    trade_id=trade_id,
                    status="SIMULATION",
                    comment="AUTO_TRADE=False",
                )

                warning(
                    "ТЕСТОВЫЙ РЕЖИМ: "
                    "сигнал сохранён, "
                    "ордер не отправлен"
                )

            state.reset()

            info(
                "State Machine сброшена. "
                "Ищем новый сетап."
            )

            time.sleep(CHECK_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        warning("Бот остановлен вручную")

    except Exception as exc:
        error(f"Критическая ошибка бота: {exc}")

    finally:
        mt5.shutdown()
        info("MT5 отключён")


if __name__ == "__main__":
    main()