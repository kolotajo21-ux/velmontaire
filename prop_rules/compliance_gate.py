from __future__ import annotations
from dataclasses import asdict
from prop_rules.news_engine import NewsComplianceEngine
from prop_rules.risk_engine import PropRiskComplianceEngine
from prop_rules.risk_models import PropAccountSnapshot

class PropComplianceGate:
    def __init__(self, *, prop_rules_app, news_engine=None, risk_engine=None):
        self.prop_rules_app=prop_rules_app
        self.news=news_engine or NewsComplianceEngine()
        self.risk=risk_engine or PropRiskComplianceEngine()

    def evaluate(self, *, user_id, strategy, symbol, action, now_utc, events,
                 snapshot, requested_risk_amount=0.0, is_weekend=False):
        _,selected=self.prop_rules_app.current(user_id)

        # Personal accounts bypass prop-specific rules only.
        if selected.get("mode")=="PERSONAL":
            return {"allowed":True,"status":"ALLOWED","reason":"personal_account_no_prop_policy",
                    "news":None,"risk":None}

        if selected.get("mode")!="PROP_FIRM" or selected.get("policy_status")!="VERIFIED":
            return {"allowed":False,"status":"BLOCKED","reason":"verified_prop_policy_required",
                    "news":None,"risk":None}

        # Strategy must be structured/approved upstream; browser text is never execution authority.
        if not isinstance(strategy,dict) or not strategy.get("strategy_id") or not strategy.get("version_id"):
            return {"allowed":False,"status":"BLOCKED","reason":"pinned_strategy_version_required",
                    "news":None,"risk":None}

        rules=selected["rules"]

        news=self.news.evaluate(rules=rules,symbol=symbol,action=action,now_utc=now_utc,events=events)
        if not news.allowed:
            return {"allowed":False,"status":"BLOCKED","reason":"news_compliance_blocked",
                    "news":news.to_dict(),"risk":None}

        risk=self.risk.evaluate(rules=rules,snapshot=snapshot,action=action,
                                requested_risk_amount=requested_risk_amount,is_weekend=is_weekend)
        if not risk.allowed:
            return {"allowed":False,"status":"BLOCKED","reason":"prop_risk_compliance_blocked",
                    "news":news.to_dict(),"risk":risk.to_dict()}

        return {"allowed":True,"status":"ALLOWED","reason":"prop_compliance_passed",
                "ruleset_id":selected.get("ruleset_id"),
                "strategy_id":strategy["strategy_id"],"version_id":strategy["version_id"],
                "news":news.to_dict(),"risk":risk.to_dict()}
