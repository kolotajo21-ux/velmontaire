class WebPropRulesApplication:

    def __init__(self,registry):self.registry=registry;self.selected={}

    def catalog(self,user_id):return 200,{"ok":True,"mode_options":["PERSONAL","PROP_FIRM"],"catalog":self.registry.catalog(),"unified_catalog":self.registry.unified_catalog()}

    def current(self,user_id):return 200,{"ok":True,**self.selected.get(user_id,{"mode":"UNCONFIGURED","policy_status":"UNRESOLVED"})}

    def select(self,user_id,body):

        mode=str(body.get("mode","")).upper()

        if mode=="PERSONAL":

            v={"mode":"PERSONAL","policy_status":"NOT_APPLICABLE","rules":{}};self.selected[user_id]=v;return 200,{"ok":True,**v}

        if mode!="PROP_FIRM":return 400,{"ok":False,"error":"account_environment_required"}

        try:size=int(body.get("account_size"));x=self.registry.resolve(str(body.get("firm","")),str(body.get("program","")),str(body.get("phase","")),size)

        except (TypeError,ValueError):return 400,{"ok":False,"error":"valid_account_size_required"}

        except (LookupError,RuntimeError) as e:return 409,{"ok":False,"error":str(e),"policy_status":"UNRESOLVED"}

        v={"mode":"PROP_FIRM","firm":x.firm,"program":x.program,"phase":x.phase,"account_size":size,"ruleset_id":x.ruleset_id,"rules":dict(x.rules),"source_url":x.source_url,"verified_at":x.verified_at,"policy_status":"VERIFIED"};self.selected[user_id]=v;return 200,{"ok":True,**v}


    def details(self,user_id,firm,program,phase,account_size):
        try:x=self.registry.resolve(str(firm),str(program),str(phase),int(account_size))
        except (LookupError,RuntimeError,ValueError) as e:return 409,{"ok":False,"error":str(e),"policy_status":"UNRESOLVED"}
        return 200,{"ok":True,"market_type":"CFD_PROP","ruleset":x.to_dict(),"policy_status":"VERIFIED"}
