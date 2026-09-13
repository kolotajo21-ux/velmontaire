from dataclasses import dataclass,asdict
from typing import Any

@dataclass(frozen=True,slots=True)
class FuturesPropRuleSet:
    ruleset_id:str;firm:str;program:str;stage:str;account_size:int
    rules:dict[str,Any];source_urls:tuple[str,...];verified_at:str;status:str="VERIFIED"
    def validate(self):
        if not all((self.ruleset_id,self.firm,self.program,self.stage,self.account_size)):raise ValueError("futures_prop_identity_required")
        if self.status not in {"VERIFIED","STALE","UNRESOLVED"}:raise ValueError("invalid_futures_prop_status")
        if self.status=="VERIFIED" and (not self.source_urls or not self.verified_at):raise ValueError("verified_futures_rules_require_sources")
        if self.rules.get("market")!="FUTURES":raise ValueError("futures_ruleset_market_required")
    def to_dict(self):return asdict(self)

@dataclass(frozen=True,slots=True)
class FuturesAccountSnapshot:
    balance:float;equity:float;starting_balance:float
    eod_high_balance:float|None=None;equity_hwm:float|None=None
    daily_pnl:float=0.0;best_day_profit:float=0.0;total_profit:float=0.0
    trading_days:int=0

@dataclass(frozen=True,slots=True)
class FuturesOrderIntent:
    symbol:str;contracts:int;action:str="OPEN";is_tier1_news:bool=False
