import json,urllib.request
URL="https://biquote.io/api/calendar/upcoming?limit=10&importance=high"
class BiQuoteCalendarAdapter:
 def __init__(self,url=URL,timeout=4):self.url=url;self.timeout=timeout
 def fetch(self):
  req=urllib.request.Request(self.url,headers={"User-Agent":"VELMONTAIRE/1.0"})
  with urllib.request.urlopen(req,timeout=self.timeout) as r:raw=json.loads(r.read().decode("utf-8"))
  if isinstance(raw,dict):raw=raw.get("items") or raw.get("data") or raw.get("events") or []
  if not isinstance(raw,list):raise RuntimeError("invalid_calendar_payload")
  out=[]
  for x in raw:
   if not isinstance(x,dict) or str(x.get("importance") or "").lower()!="high":continue
   out.append({"title":str(x.get("name") or "Economic event"),"currency":str(x.get("currency") or "").upper(),"impact":"HIGH","time":str(x.get("time") or ""),"forecast":x.get("forecast"),"previous":x.get("previous"),"actual":x.get("actual"),"source":"BiQuote Economic Calendar","reaction":"Compliance check required for affected instruments"})
  return out
