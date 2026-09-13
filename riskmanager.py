def calculate_position_size(
    balance,
    risk_percent,
    entry,
    stop_loss,
    pip_value_per_lot=10,
):
    risk_money = balance * (risk_percent / 100)

    stop_distance = abs(entry - stop_loss)

    if stop_distance == 0:
        return None

    stop_pips = stop_distance * 10000

    lot = risk_money / (stop_pips * pip_value_per_lot)

    return {
        "risk_money": round(risk_money, 2),
        "stop_pips": round(stop_pips, 1),
        "lot": round(lot, 2),
    }