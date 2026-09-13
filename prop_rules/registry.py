class PropRulesRegistry:
    def __init__(self,items=()):
        self.items={}
        for x in items:self.register(x)
    def register(self,x):
        x.validate()
        if x.ruleset_id in self.items:raise ValueError("duplicate_prop_ruleset")
        self.items[x.ruleset_id]=x
    def firms(self):return sorted({x.firm for x in self.items.values()})
    def catalog(self):
        out={}
        for x in self.items.values():out.setdefault(x.firm,{}).setdefault(x.program,{}).setdefault(x.phase,set()).update(x.account_sizes)
        return {f:{p:{ph:sorted(v) for ph,v in phases.items()} for p,phases in programs.items()} for f,programs in out.items()}
    def resolve(self,firm,program,phase,account_size):
        m=[x for x in self.items.values() if x.firm==firm and x.program==program and x.phase==phase and account_size in x.account_sizes]
        if len(m)!=1:raise LookupError("prop_ruleset_unresolved")
        if m[0].status!="VERIFIED":raise RuntimeError("prop_ruleset_not_verified")
        return m[0]

    def unified_catalog(self):
        out=[]
        for x in sorted(self.items.values(),key=lambda y:(y.firm,y.program,y.phase,y.account_sizes)):
            out.append({"market_type":"CFD_PROP","firm":x.firm,"program":x.program,"stage":x.phase,
                        "account_sizes":list(x.account_sizes),"ruleset_id":x.ruleset_id,
                        "ruleset_version":x.ruleset_version,"status":x.status,
                        "verified_at":x.verified_at,"source_url":x.source_url})
        return out
