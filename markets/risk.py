import math
def futures_contracts_for_risk(*,entry,stop,risk_amount,spec):
    if spec.market_type!="FUTURE":raise ValueError("futures_instrument_required")
    if not spec.tick_size or not spec.tick_value:raise ValueError("futures_tick_spec_required")
    if risk_amount<=0:raise ValueError("risk_amount_invalid")
    distance=abs(float(entry)-float(stop))
    if distance<=0:raise ValueError("stop_distance_invalid")
    ticks=distance/spec.tick_size;risk_per_contract=ticks*spec.tick_value
    return {"contracts":max(0,math.floor(risk_amount/risk_per_contract)),"ticks_to_stop":ticks,"risk_per_contract":risk_per_contract}
