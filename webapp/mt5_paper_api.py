from __future__ import annotations
from typing import Any
from backend.application.broker_connection_service import BrokerConnectionService
from backend.application.execution_mode_guard import ExecutionModeGuard

class WebMT5PaperApplication:
    def __init__(self, *, connections: BrokerConnectionService, mode_guard: ExecutionModeGuard, bot_core: Any):
        self.connections=connections; self.mode_guard=mode_guard; self.bot_core=bot_core

    def create_connection(self, *, user_id, body):
        v=self.connections.create_mt5(user_id=user_id,login=str(body.get("login","")),password=str(body.get("password","")),server=str(body.get("server","")))
        return 201, {"ok":True, **v.to_dict()}

    def test_connection(self, *, user_id, connection_id):
        v=self.connections.test_connection(user_id=user_id,connection_id=connection_id)
        return 200, {"ok":True, **v.to_dict()}

    def start_paper(self, *, user_id, body):
        bot_id=str(body.get("bot_id","")).strip()
        version=str(body.get("strategy_version_id","")).strip()
        if not bot_id: raise ValueError("bot_id_required")
        if not version: raise ValueError("strategy_version_id_required")
        d=self.mode_guard.authorize_start(user_id=user_id,bot_id=bot_id,mode="PAPER",strategy_version_id=version,broker_connection_id=None,broker_connection_status=None,strategy_human_approved=bool(body.get("strategy_human_approved",False)),production_safety_ready=bool(body.get("production_safety_ready",False)))
        if not d.get("allowed"): raise RuntimeError(d.get("reason","paper_start_blocked"))
        fn=getattr(self.bot_core,"start_paper",None)
        if fn is None: raise RuntimeError("paper_runtime_gateway_missing")
        r=fn(user_id=user_id,bot_id=bot_id,strategy_version_id=version)
        ok=bool(r.get("ok",r.get("success",False))) if isinstance(r,dict) else bool(getattr(r,"success",False))
        if not ok: raise RuntimeError("paper_runtime_start_failed")
        return 200,{"ok":True,"mode":"PAPER","bot_id":bot_id,"strategy_version_id":version,"live_authorized":False}
