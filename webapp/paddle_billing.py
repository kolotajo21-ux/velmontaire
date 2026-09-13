from __future__ import annotations
import hashlib,hmac,json,os,time
from pathlib import Path
PLANS=("CORE","PRO","ELITE")
class PaddleSandbox:
 def __init__(self,data_dir:Path):
  self.path=data_dir/"paddle_subscriptions.json";self.path.parent.mkdir(parents=True,exist_ok=True)
 def config(self):
  token=os.getenv("PADDLE_CLIENT_TOKEN","").strip();prices={x:os.getenv("PADDLE_PRICE_"+x,"").strip() for x in PLANS}
  ok=token.startswith("test_") and all(v.startswith("pri_") for v in prices.values())
  return {"environment":"sandbox","client_token":token if ok else "","prices":prices if ok else {},"configured":ok}
 def _load(self):
  try:return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {"users":{},"events":[]}
  except Exception:return {"users":{},"events":[]}
 def _save(self,x):
  q=self.path.with_suffix(".tmp");q.write_text(json.dumps(x,indent=2,sort_keys=True),encoding="utf-8");q.replace(self.path)
 def subscription_for(self,user_id):return self._load().get("users",{}).get(str(user_id))
 def verify(self,raw,signature):
  secret=os.getenv("PADDLE_WEBHOOK_SECRET","").strip()
  if not secret or not signature:return False,"webhook_not_configured"
  parts={}
  for piece in signature.split(";"):
   if "=" in piece:
    k,v=piece.split("=",1);parts.setdefault(k,[]).append(v)
  try:ts=int(parts.get("ts",[""])[0])
  except ValueError:return False,"invalid_signature_timestamp"
  if abs(int(time.time())-ts)>int(os.getenv("PADDLE_WEBHOOK_TOLERANCE_SECONDS","5")):return False,"webhook_timestamp_outside_tolerance"
  expected=hmac.new(secret.encode(),str(ts).encode()+b":"+raw,hashlib.sha256).hexdigest()
  return ((True,"verified") if any(hmac.compare_digest(expected,x) for x in parts.get("h1",[])) else (False,"invalid_webhook_signature"))
 def ingest(self,raw,signature):
  ok,reason=self.verify(raw,signature)
  print("[PADDLE WEBHOOK]", "ok=", ok, "reason=", reason)
  if not ok:return 401,{"ok":False,"error":reason}
  try:e=json.loads(raw.decode("utf-8"))
  except Exception:return 400,{"ok":False,"error":"invalid_json"}
  eid=str(e.get("event_id") or "");typ=str(e.get("event_type") or "");d=e.get("data") or {};store=self._load()
  if eid and eid in store.get("events",[]):return 200,{"ok":True,"duplicate":True}
  custom=d.get("custom_data") or {};uid=str(custom.get("user_id") or "");plan=str(custom.get("plan_code") or "").upper()
  if not uid:return 202,{"ok":True,"applied":False,"reason":"missing_user_binding"}
  if typ in {"subscription.created","subscription.updated"}:
   if plan not in PLANS:return 202,{"ok":True,"applied":False,"reason":"unknown_plan"}
   active=str(d.get("status") or "").lower() in {"active","trialing"}
   store.setdefault("users",{})[uid]={"plan_code":plan,"subscription_status":"ACTIVE" if active else str(d.get("status") or "").upper(),"paid_entitlements_allowed":active,"provider":"PADDLE","provider_subscription_id":d.get("id"),"provider_customer_id":d.get("customer_id"),"last_event_id":eid}
  elif typ=="subscription.canceled":
   old=store.setdefault("users",{}).get(uid,{});old.update({"subscription_status":"CANCELED","paid_entitlements_allowed":False,"provider":"PADDLE","last_event_id":eid});store["users"][uid]=old
  elif typ!="transaction.completed":return 202,{"ok":True,"applied":False,"reason":"event_not_used"}
  if eid:store.setdefault("events",[]).append(eid)
  self._save(store);return 200,{"ok":True,"applied":True,"event_type":typ}
