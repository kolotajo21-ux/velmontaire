from __future__ import annotations
import json, urllib.request
FOREX_FACTORY_WEEKLY_JSON="https://nfs.faireconomy.media/ff_calendar_thisweek.json"
class ForexFactoryCalendarAdapter:
    def __init__(self,url=FOREX_FACTORY_WEEKLY_JSON,timeout=4): self.url=url; self.timeout=timeout
    def fetch(self):
        req=urllib.request.Request(self.url,headers={"User-Agent":"VELMONTAIRE/1.0"})
        with urllib.request.urlopen(req,timeout=self.timeout) as r: raw=json.loads(r.read().decode("utf-8"))
        if not isinstance(raw,list): raise RuntimeError("invalid_calendar_payload")
        out=[]
        for x in raw:
            if not isinstance(x,dict) or str(x.get("impact") or "").strip().lower()!="high": continue
            out.append({"title":str(x.get("title") or "Economic event"),"currency":str(x.get("country") or "").upper(),"impact":"HIGH","time":str(x.get("date") or ""),"forecast":x.get("forecast"),"previous":x.get("previous"),"actual":x.get("actual"),"source":"Forex Factory Weekly Export"})
        out.sort(key=lambda e:e["time"]); return out
