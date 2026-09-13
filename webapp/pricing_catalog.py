from __future__ import annotations
PLAN_ORDER=("CORE","PRO","ELITE")
PLANS={
"CORE":{"code":"CORE","name":"Core","monthly_usd":29,"annual_monthly_usd":23,"highlight":False,"limits":{"strategies":3,"backtests_monthly":30,"broker_connections":0,"active_live_bots":0},"features":{"AI_STRATEGY_BUILDER":True,"BACKTEST":True,"PAPER_TRADING":True,"PERSONAL_MARKETS":True,"CFD_PROP":False,"FUTURES_PROP":False,"LIVE_EXECUTION":False,"ADVANCED_ANALYTICS":False,"PRIORITY_SUPPORT":False}},
"PRO":{"code":"PRO","name":"Pro","monthly_usd":49,"annual_monthly_usd":39,"highlight":True,"limits":{"strategies":15,"backtests_monthly":150,"broker_connections":3,"active_live_bots":3},"features":{"AI_STRATEGY_BUILDER":True,"BACKTEST":True,"PAPER_TRADING":True,"PERSONAL_MARKETS":True,"CFD_PROP":True,"FUTURES_PROP":True,"LIVE_EXECUTION":True,"ADVANCED_ANALYTICS":True,"PRIORITY_SUPPORT":False}},
"ELITE":{"code":"ELITE","name":"Elite","monthly_usd":89,"annual_monthly_usd":71,"highlight":False,"limits":{"strategies":50,"backtests_monthly":500,"broker_connections":10,"active_live_bots":10},"features":{"AI_STRATEGY_BUILDER":True,"BACKTEST":True,"PAPER_TRADING":True,"PERSONAL_MARKETS":True,"CFD_PROP":True,"FUTURES_PROP":True,"LIVE_EXECUTION":True,"ADVANCED_ANALYTICS":True,"PRIORITY_SUPPORT":True}}}
def public_plans():return [PLANS[x] for x in PLAN_ORDER]
def entitlement(plan_code,feature):
 p=PLANS.get(str(plan_code or "").upper())
 if not p:return {"allowed":False,"reason":"unknown_plan"}
 a=p["features"].get(str(feature or "").upper())
 if a is None:return {"allowed":False,"reason":"unknown_feature"}
 return {"allowed":bool(a),"reason":"plan_allows" if a else "upgrade_required"}
