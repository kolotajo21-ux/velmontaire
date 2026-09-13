from prop_rules.compliance_gate import PropComplianceGate
from prop_rules.news_models import EconomicEvent
from prop_rules.risk_models import PropAccountSnapshot

class WebPropComplianceApplication:
    def __init__(self, *, prop_rules_app):
        self.gate=PropComplianceGate(prop_rules_app=prop_rules_app)

    def check(self, *, user_id, body):
        try:
            events=[EconomicEvent(
                event_id=str(x["event_id"]),timestamp_utc=str(x["timestamp_utc"]),
                impact=str(x["impact"]),currencies=tuple(str(c).upper() for c in x.get("currencies",[])),
                title=str(x.get("title","")),source=str(x.get("source",""))
            ) for x in body.get("events",[])]
            raw=body.get("snapshot") or {}
            snap=PropAccountSnapshot(**{k:raw[k] for k in PropAccountSnapshot.__dataclass_fields__ if k in raw})
            result=self.gate.evaluate(
                user_id=user_id,strategy=body.get("strategy"),
                symbol=str(body.get("symbol","")),action=str(body.get("action","OPEN")),
                now_utc=str(body.get("now_utc","")),events=events,snapshot=snap,
                requested_risk_amount=float(body.get("requested_risk_amount",0) or 0),
                is_weekend=bool(body.get("is_weekend",False)))
        except (KeyError,TypeError,ValueError) as exc:
            return 400,{"ok":False,"allowed":False,"error":str(exc)}
        return (200 if result["allowed"] else 409),{"ok":result["allowed"],**result}
