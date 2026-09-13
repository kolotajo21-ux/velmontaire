from dataclasses import asdict
class FuturesPropComplianceEngine:
    def __init__(self,instruments):self.instruments=instruments
    def _weighted_minis(self,spec,contracts,rules):
        overrides=rules.get("product_weights",{})
        if spec.canonical_id in overrides:return contracts*float(overrides[spec.canonical_id])
        if spec.size_class=="MICRO":return contracts/float(rules.get("micro_to_mini_ratio",10))
        return float(contracts)
    def _floor(self,rules,s):
        d=float(rules["max_loss_distance"]);t=rules["drawdown_type"]
        if t=="EOD_TRAILING_BALANCE":
            high=max(float(s.starting_balance),float(s.eod_high_balance if s.eod_high_balance is not None else s.starting_balance))
            floor=high-d
            if rules.get("drawdown_lock")=="STARTING_BALANCE":floor=min(float(s.starting_balance),floor)
            return floor
        if t=="INTRADAY_TRAILING_EQUITY_HWM":
            h=float(s.equity_hwm if s.equity_hwm is not None else s.equity)
            floor=h-d
            lock=rules.get("drawdown_lock_value")
            if lock is not None:floor=min(float(lock),floor)
            return floor
        raise ValueError("unknown_futures_drawdown_type")
    def evaluate(self,*,ruleset,snapshot,intent,current_open_weighted_minis=0.0):
        if ruleset.status!="VERIFIED":return {"allowed":False,"reason":"ruleset_not_verified"}
        r=ruleset.rules
        if r.get("market")!="FUTURES":return {"allowed":False,"reason":"futures_rules_required"}
        try:spec=self.instruments.resolve(intent.symbol)
        except ValueError:return {"allowed":False,"reason":"instrument_unresolved"}
        if spec.market_type!="FUTURE":return {"allowed":False,"reason":"futures_instrument_required"}
        if intent.contracts<=0:return {"allowed":False,"reason":"contracts_invalid"}
        floor=self._floor(r,snapshot)
        breach_value=snapshot.equity if r.get("drawdown_breach_basis") in {"INTRADAY_EQUITY","EOD_EQUITY"} else snapshot.balance
        if float(breach_value)<=floor:return {"allowed":False,"reason":"maximum_loss_limit_breached","floor":floor}
        dll=r.get("daily_loss_limit")
        if dll is not None and float(snapshot.daily_pnl)<=-float(dll):return {"allowed":False,"reason":"daily_loss_limit_reached"}
        if intent.is_tier1_news and r.get("news_policy")=="BLOCK_T1":return {"allowed":False,"reason":"tier1_news_restricted"}
        weight=self._weighted_minis(spec,intent.contracts,r)
        if float(current_open_weighted_minis)+weight>float(r["max_minis"]):return {"allowed":False,"reason":"maximum_contracts_exceeded","weighted_minis":weight}
        c=r.get("consistency_percent")
        if c is not None and snapshot.total_profit>0 and (snapshot.best_day_profit/snapshot.total_profit*100)>float(c):
            return {"allowed":False,"reason":"consistency_target_not_met"}
        md=r.get("minimum_trading_days")
        if md is not None and snapshot.trading_days<int(md) and intent.action=="COMPLETE":
            return {"allowed":False,"reason":"minimum_trading_days_not_met"}
        return {"allowed":True,"reason":"futures_prop_compliance_pass","ruleset_id":ruleset.ruleset_id,"instrument":spec.canonical_id,"floor":floor,"weighted_minis":weight}
