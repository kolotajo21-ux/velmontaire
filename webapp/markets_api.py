from markets.catalog import build_default_instrument_registry
from markets.risk import futures_contracts_for_risk
class WebMarketsApplication:
    def __init__(self):self.registry=build_default_instrument_registry()
    def catalog(self):return 200,{"ok":True,"instruments":self.registry.catalog()}
    def normalize(self,body):return 200,{"ok":True,"symbols":self.registry.normalize_broker_symbols(body.get("symbols") or [])}
    def futures_risk(self,body):
        try:
            spec=self.registry.resolve(body.get("symbol",""))
            data=futures_contracts_for_risk(entry=float(body["entry"]),stop=float(body["stop"]),risk_amount=float(body["risk_amount"]),spec=spec)
        except (ValueError,KeyError,TypeError) as e:return 400,{"ok":False,"error":str(e)}
        return 200,{"ok":True,"instrument":spec.to_dict(),**data}
