import MetaTrader5 as mt5


BOT_MAGIC = 24072026


def get_bot_positions(symbol=None):
    if symbol is None:
        positions = mt5.positions_get()
    else:
        positions = mt5.positions_get(symbol=symbol)

    if positions is None:
        print("❌ Не удалось получить позиции")
        print("Ошибка:", mt5.last_error())
        return []

    return [
        position
        for position in positions
        if position.magic == BOT_MAGIC
    ]


def move_stop_to_break_even(position):
    symbol_info = mt5.symbol_info(position.symbol)

    if symbol_info is None:
        print("❌ Не удалось получить данные символа")
        return False

    entry = float(position.price_open)
    current_sl = float(position.sl)

    new_sl = round(entry, symbol_info.digits)

    # Стоп уже в безубытке или лучше
    if position.type == mt5.POSITION_TYPE_BUY:
        if current_sl >= new_sl:
            return False

    if position.type == mt5.POSITION_TYPE_SELL:
        if current_sl != 0 and current_sl <= new_sl:
            return False

    request = {
        "action": mt5.TRADE_ACTION_SLTP,
        "position": int(position.ticket),
        "symbol": position.symbol,
        "sl": new_sl,
        "tp": float(position.tp),
        "magic": BOT_MAGIC,
        "comment": "SMC_BOT_BE",
    }

    result = mt5.order_send(request)

    if result is None:
        print("❌ MT5 не перенёс стоп")
        print("Ошибка:", mt5.last_error())
        return False

    print("\n===== BREAK EVEN =====")
    print(f"Ticket: {position.ticket}")
    print(f"Retcode: {result.retcode}")
    print(f"Комментарий: {result.comment}")

    return result.retcode == mt5.TRADE_RETCODE_DONE


def check_break_even(position, trigger_r=1.0):
    tick = mt5.symbol_info_tick(position.symbol)

    if tick is None:
        return False

    entry = float(position.price_open)
    stop_loss = float(position.sl)

    if stop_loss == 0:
        return False

    if position.type == mt5.POSITION_TYPE_BUY:
        initial_risk = entry - stop_loss

        if initial_risk <= 0:
            return False

        trigger_price = entry + initial_risk * trigger_r

        if tick.bid >= trigger_price:
            return move_stop_to_break_even(position)

    if position.type == mt5.POSITION_TYPE_SELL:
        initial_risk = stop_loss - entry

        if initial_risk <= 0:
            return False

        trigger_price = entry - initial_risk * trigger_r

        if tick.ask <= trigger_price:
            return move_stop_to_break_even(position)

    return False


def manage_break_even(symbol=None, trigger_r=1.0):
    positions = get_bot_positions(symbol)

    moved = 0

    for position in positions:
        if check_break_even(position, trigger_r):
            moved += 1

    return moved