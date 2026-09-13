class FuturesPropRegistry:
    def __init__(self,items=()):
        self.items={}
        for x in items:self.register(x)
    def register(self,x):
        x.validate()
        if x.ruleset_id in self.items:raise ValueError("duplicate_futures_prop_ruleset")
        self.items[x.ruleset_id]=x
    def resolve(self,firm,program,stage,account_size):
        m=[x for x in self.items.values() if x.firm==firm and x.program==program and x.stage==stage and x.account_size==int(account_size)]
        if len(m)!=1:raise LookupError("futures_prop_ruleset_unresolved")
        if m[0].status!="VERIFIED":raise RuntimeError("futures_prop_ruleset_not_verified")
        return m[0]
    def catalog(self):
        out={}
        for x in self.items.values():
            out.setdefault(x.firm,{}).setdefault(x.program,{}).setdefault(x.stage,[]).append(x.account_size)
        return {f:{p:{s:sorted(set(v)) for s,v in stages.items()} for p,stages in programs.items()} for f,programs in out.items()}
