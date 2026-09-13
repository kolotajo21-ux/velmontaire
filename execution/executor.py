import MetaTrader5 as mt5


BOT_MAGIC = 24072026
BOT_COMMENT = "SMC_BOT"


def get_pending_order_type(order_type):
    if order_type == "BUY_LIMIT":
        return mt5.ORDER_TYPE_BUY_LIMIT

    if order_type == "SELL_LIMIT":
        return mt5.ORDER_TYPE_SELL_LIMIT

    return None


def normalize_volume(symbol, volume):
    symbol_info = mt5.symbol_info(symbol)

    if symbol_info is None:
        print(f"❌ Не удалось получить данные символа {symbol}")
        return None

    volume = max(symbol_info.volume_min, volume)
    volume = min(symbol_info.volume_max, volume)

    steps = round(volume / symbol_info.volume_step)
    normalized_volume = steps * symbol_info.volume_step

    volume_digits = 2

    if symbol_info.volume_step == 0.001:
        volume_digits = 3

    return round(normalized_volume, volume_digits)


def build_pending_request(
    symbol,
    order_type,
    entry,
    stop_loss,
    take_profit,
    lot,
    comment=BOT_COMMENT,
):
    symbol_info = mt5.symbol_info(symbol)

    if symbol_info is None:
        print(f"❌ Символ {symbol} не найден")
        return None

    if not symbol_info.visible:
        if not mt5.symbol_select(symbol, True):
            print(f"❌ Не удалось включить символ {symbol}")
            return None

    mt5_order_type = get_pending_order_type(order_type)

    if mt5_order_type is None:
        print(f"❌ Неизвестный тип ордера: {order_type}")
        return None

    normalized_lot = normalize_volume(symbol, lot)

    if normalized_lot is None:
        return None

    return {
        "action": mt5.TRADE_ACTION_PENDING,
        "symbol": symbol,
        "volume": normalized_lot,
        "type": mt5_order_type,
        "price": round(float(entry), symbol_info.digits),
        "sl": round(float(stop_loss), symbol_info.digits),
        "tp": round(float(take_profit), symbol_info.digits),
        "deviation": 20,
        "magic": BOT_MAGIC,
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_RETURN,
    }


def check_pending_order(request):
    if request is None:
        return None

    result = mt5.order_check(request)

    if result is None:
        print("❌ MT5 не выполнил проверку")
        print("Ошибка:", mt5.last_error())
        return None

    print("\n===== ПРОВЕРКА ОРДЕРА =====")
    print(f"Retcode: {result.retcode}")
    print(f"Комментарий: {result.comment}")
    print(f"Баланс: {result.balance}")
    print(f"Средства: {result.equity}")
    print(f"Маржа: {result.margin}")
    print(f"Свободная маржа: {result.margin_free}")

    return result


def get_bot_pending_orders(symbol=None):
    if symbol is None:
        orders = mt5.orders_get()
    else:
        orders = mt5.orders_get(symbol=symbol)

    if orders is None:
        print("❌ Не удалось получить активные ордера")
        print("Ошибка:", mt5.last_error())
        return []

    return [
        order
        for order in orders
        if order.magic == BOT_MAGIC
    ]


def get_open_positions(symbol=None):
    if symbol is None:
        positions = mt5.positions_get()
    else:
        positions = mt5.positions_get(symbol=symbol)

    if positions is None:
        print("❌ Не удалось получить открытые позиции")
        print("Ошибка:", mt5.last_error())
        return []

    return list(positions)


def has_open_position(symbol):
    positions = get_open_positions(symbol)
    return len(positions) > 0


def has_duplicate_pending_order(request):
    if request is None:
        return True

    symbol = request["symbol"]
    existing_orders = get_bot_pending_orders(symbol)

    symbol_info = mt5.symbol_info(symbol)

    if symbol_info is None:
        return True

    price_tolerance = symbol_info.point * 2

    for order in existing_orders:
        same_type = order.type == request["type"]

        same_price = (
            abs(order.price_open - request["price"])
            <= price_tolerance
        )

        if same_type and same_price:
            return True

    return False


def send_pending_order(request):
    if request is None:
        return None

    result = mt5.order_send(request)

    if result is None:
        print("❌ MT5 не отправил ордер")
        print("Ошибка:", mt5.last_error())
        return None

    print("\n===== ОТПРАВКА ОРДЕРА =====")
    print(f"Retcode: {result.retcode}")
    print(f"Комментарий: {result.comment}")
    print(f"Ticket: {result.order}")

    return result


def send_pending_order_safely(request):
    if request is None:
        print("❌ Запрос ордера отсутствует")
        return None

    symbol = request["symbol"]

    if has_open_position(symbol):
        print(f"⛔ По {symbol} уже есть открытая позиция")
        return None

    if has_duplicate_pending_order(request):
        print("⛔ Такая лимитка уже существует")
        return None

    check_result = check_pending_order(request)

    if check_result is None:
        print("❌ Проверка ордера не выполнена")
        return None

    if check_result.retcode != 0:
        print(
            "❌ MT5 отклонил параметры: "
            f"{check_result.comment}"
        )
        return None

    result = send_pending_order(request)

    if result is None:
        return None

    success_codes = (
        mt5.TRADE_RETCODE_DONE,
        mt5.TRADE_RETCODE_PLACED,
    )

    if result.retcode not in success_codes:
        print("❌ Торговый сервер отклонил ордер")
        return None

    print("✅ Лимитный ордер успешно установлен")

    return result


def cancel_pending_order(ticket):
    request = {
        "action": mt5.TRADE_ACTION_REMOVE,
        "order": int(ticket),
        "magic": BOT_MAGIC,
        "comment": f"{BOT_COMMENT}_CANCEL",
    }

    result = mt5.order_send(request)

    if result is None:
        print("❌ MT5 не выполнил отмену")
        print("Ошибка:", mt5.last_error())
        return False

    print("\n===== ОТМЕНА ОРДЕРА =====")
    print(f"Ticket: {ticket}")
    print(f"Retcode: {result.retcode}")
    print(f"Комментарий: {result.comment}")

    return result.retcode == mt5.TRADE_RETCODE_DONE


def cancel_all_bot_orders(symbol=None):
    orders = get_bot_pending_orders(symbol)

    if not orders:
        print("Активных ордеров бота нет")
        return 0

    cancelled = 0

    for order in orders:
        if cancel_pending_order(order.ticket):
            cancelled += 1

    print(
        f"Отменено ордеров: {cancelled}"
        f" из {len(orders)}"
    )
import time


def cancel_expired_bot_orders(
    symbol=None,
    max_age_minutes=30,
):
    orders = get_bot_pending_orders(symbol)

    if not orders:
        return 0

    current_time = int(time.time())
    max_age_seconds = max_age_minutes * 60
    cancelled = 0

    for order in orders:
        order_age = current_time - int(order.time_setup)

        if order_age < max_age_seconds:
            continue

        print(
            f"\n⏳ Ордер {order.ticket} просрочен"
            f" | Возраст: {order_age // 60} мин."
        )

        if cancel_pending_order(order.ticket):
            cancelled += 1

    return cancelled
    