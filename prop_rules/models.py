from dataclasses import dataclass,asdict
from typing import Any
@dataclass(frozen=True,slots=True)
class PropRuleSet:
    ruleset_id:str;firm:str;program:str;phase:str;account_sizes:tuple[int,...];rules:dict[str,Any];source_url:str;verified_at:str;status:str="VERIFIED";ruleset_version:int=1
    def validate(self):
        if not all((self.ruleset_id,self.firm,self.program,self.phase,self.account_sizes)):raise ValueError("prop_ruleset_identity_required")
        if self.status not in {"VERIFIED","STALE","UNRESOLVED"}:raise ValueError("invalid_prop_ruleset_status")
        if self.status=="VERIFIED" and (not self.source_url or not self.verified_at):raise ValueError("verified_ruleset_requires_source_and_timestamp")
    def to_dict(self):return asdict(self)
