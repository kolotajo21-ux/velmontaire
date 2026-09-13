from futures_prop.catalog import build_default_futures_prop_registry
from futures_prop.engine import FuturesPropComplianceEngine
from futures_prop.models import FuturesAccountSnapshot,FuturesOrderIntent
from markets.catalog import build_default_instrument_registry

class WebFuturesPropApplication:
    def __init__(self):
        self.registry=build_default_futures_prop_registry()
        self.engine=FuturesPropComplianceEngine(build_default_instrument_registry())
    def catalog(self):return 200,{"ok":True,"catalog":self.registry.catalog()}
    def details(self,firm,program,stage,account_size):
        try:rs=self.registry.resolve(str(firm),str(program),str(stage),int(account_size))
        except (LookupError,RuntimeError,ValueError) as e:return 404,{"ok":False,"error":str(e)}
        return 200,{"ok":True,"ruleset":rs.to_dict()}
    def check(self,body):
        try:
            rs=self.registry.resolve(str(body["firm"]),str(body["program"]),str(body["stage"]),int(body["account_size"]))
            s=FuturesAccountSnapshot(**body["snapshot"]);i=FuturesOrderIntent(**body["intent"])
            d=self.engine.evaluate(ruleset=rs,snapshot=s,intent=i,current_open_weighted_minis=float(body.get("current_open_weighted_minis",0)))
        except (KeyError,TypeError,ValueError) as e:return 400,{"ok":False,"error":str(e)}
        except (LookupError,RuntimeError) as e:return 409,{"ok":False,"error":str(e)}
        return (200 if d["allowed"] else 409),{"ok":d["allowed"],**d}
