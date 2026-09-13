from prop_rules.risk_engine import PropRiskComplianceEngine
from prop_rules.risk_models import PropAccountSnapshot

class WebPropRiskApplication:
    def __init__(self, *, prop_rules_app, engine=None):
        self.prop_rules_app=prop_rules_app;self.engine=engine or PropRiskComplianceEngine()
    def evaluate(self, *, user_id, body):
        _,selected=self.prop_rules_app.current(user_id)
        if selected.get("mode")!="PROP_FIRM" or selected.get("policy_status")!="VERIFIED":
            return 409,{"ok":False,"allowed":False,"error":"verified_prop_policy_required"}
        try:
            raw=body.get("snapshot") or {}
            snap=PropAccountSnapshot(**{k:raw[k] for k in PropAccountSnapshot.__dataclass_fields__ if k in raw})
            d=self.engine.evaluate(rules=selected["rules"],snapshot=snap,action=body.get("action",""),
                requested_risk_amount=float(body.get("requested_risk_amount",0) or 0),
                is_weekend=bool(body.get("is_weekend",False)))
        except (TypeError,ValueError,KeyError) as exc:
            return 400,{"ok":False,"allowed":False,"error":str(exc)}
        status=200 if d.policy_status=="VERIFIED" else 409
        return status,{"ok":status==200,**d.to_dict()}
