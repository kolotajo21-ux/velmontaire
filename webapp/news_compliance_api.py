from __future__ import annotations
from prop_rules.news_engine import NewsComplianceEngine
from prop_rules.news_models import EconomicEvent

class WebNewsComplianceApplication:
    def __init__(self, *, prop_rules_app, engine=None):
        self.prop_rules_app=prop_rules_app
        self.engine=engine or NewsComplianceEngine()

    def evaluate(self, *, user_id: str, body: dict):
        _, selected=self.prop_rules_app.current(user_id)
        if selected.get("mode")!="PROP_FIRM" or selected.get("policy_status")!="VERIFIED":
            return 409,{"ok":False,"error":"verified_prop_policy_required","allowed":False}
        raw_events=body.get("events")
        if not isinstance(raw_events,list):
            return 400,{"ok":False,"error":"economic_events_required","allowed":False}
        events=[]
        try:
            for item in raw_events:
                events.append(EconomicEvent(
                    event_id=str(item["event_id"]),
                    timestamp_utc=str(item["timestamp_utc"]),
                    impact=str(item["impact"]),
                    currencies=tuple(str(x).upper() for x in item.get("currencies",[])),
                    title=str(item.get("title","")),
                    source=str(item.get("source","")),
                ))
            decision=self.engine.evaluate(
                rules=selected["rules"],
                symbol=str(body.get("symbol","")),
                action=str(body.get("action","")),
                now_utc=str(body.get("now_utc","")),
                events=events,
            )
        except (KeyError,ValueError) as exc:
            return 400,{"ok":False,"error":str(exc),"allowed":False}
        status=200 if decision.policy_status=="VERIFIED" else 409
        return status,{"ok":status==200,**decision.to_dict()}
