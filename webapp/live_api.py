from __future__ import annotations
from typing import Any
from backend.application.execution_mode_guard import ExecutionModeGuard
from backend.application.production_observability_service import ProductionObservabilityService

class WebLiveMonitoringApplication:
    def __init__(self, *, connections: Any, mode_guard: ExecutionModeGuard, bot_core: Any, prerequisites: Any, observability: ProductionObservabilityService) -> None:
        self.connections=connections; self.guard=mode_guard; self.bot_core=bot_core; self.prerequisites=prerequisites; self.observability=observability

    def confirm_live(self, *, user_id: str, body: dict[str, Any]):
        bot_id=self._required(body,"bot_id"); version_id=self._required(body,"strategy_version_id"); connection_id=self._required(body,"broker_connection_id"); phrase=self._required(body,"confirmation_text")
        connection=self.connections.get(user_id=user_id,connection_id=connection_id)
        if str(connection.status).upper()!="VERIFIED": raise RuntimeError("live_broker_connection_not_verified")
        state=self.prerequisites.resolve(user_id=user_id,bot_id=bot_id,strategy_version_id=version_id)
        if state.get("strategy_human_approved") is not True: raise RuntimeError("live_strategy_not_human_approved")
        if state.get("production_safety_ready") is not True: raise RuntimeError("live_production_safety_not_ready")
        confirmation=self.guard.confirm_live(user_id=user_id,bot_id=bot_id,strategy_version_id=version_id,broker_connection_id=connection_id,confirmation_text=phrase)
        self._audit(user_id=user_id,action="LIVE_CONFIRMED",bot_id=bot_id,details={"strategy_version_id":version_id,"broker_connection_id":connection_id})
        return 200,{"ok":True,"confirmed":confirmation.confirmed,"bot_id":bot_id,"strategy_version_id":version_id,"broker_connection_id":connection_id}

    def start_live(self, *, user_id: str, body: dict[str, Any]):
        bot_id=self._required(body,"bot_id"); version_id=self._required(body,"strategy_version_id"); connection_id=self._required(body,"broker_connection_id")
        connection=self.connections.get(user_id=user_id,connection_id=connection_id)
        state=self.prerequisites.resolve(user_id=user_id,bot_id=bot_id,strategy_version_id=version_id)
        decision=self.guard.authorize_start(user_id=user_id,bot_id=bot_id,mode="LIVE",strategy_version_id=version_id,broker_connection_id=connection_id,broker_connection_status=connection.status,strategy_human_approved=bool(state.get("strategy_human_approved")),production_safety_ready=bool(state.get("production_safety_ready")))
        if not decision.get("allowed"): raise RuntimeError(str(decision.get("reason","live_start_blocked")))
        result=self._control(user_id=user_id,bot_id=bot_id,action="START",mode="LIVE",strategy_version_id=version_id,broker_connection_id=connection_id)
        if not self._success(result): raise RuntimeError("live_runtime_start_failed")
        self._audit(user_id=user_id,action="LIVE_STARTED",bot_id=bot_id,details={"strategy_version_id":version_id,"broker_connection_id":connection_id})
        return 200,{"ok":True,"mode":"LIVE","bot_id":bot_id,"strategy_version_id":version_id,"broker_connection_id":connection_id}

    def command(self, *, user_id: str, bot_id: str, action: str):
        action=str(action).strip().upper()
        if action not in {"START","PAUSE","STOP"}: raise ValueError("bot_action_invalid")
        result=self._control(user_id=user_id,bot_id=bot_id,action=action,mode="LIVE")
        if not self._success(result): raise RuntimeError("live_runtime_control_failed")
        self._audit(user_id=user_id,action=f"LIVE_{action}",bot_id=bot_id,details={"action":action})
        return 200,{"ok":True,"bot_id":bot_id,"action":action}

    def status(self, *, user_id: str, bot_id: str):
        fn=getattr(self.bot_core,"runtime_status",None)
        if fn is None: raise RuntimeError("runtime_status_gateway_missing")
        state=fn(user_id=user_id,bot_id=bot_id)
        if not isinstance(state,dict): raise RuntimeError("runtime_status_invalid")
        allowed={"status","balance","equity","daily_pnl","drawdown_percent","open_positions","connection_status","cycles","successful_cycles","failed_cycles","last_reason"}
        return 200,{"ok":True,"bot_id":bot_id,"runtime":{k:state[k] for k in allowed if k in state}}

    def revoke_live(self, *, user_id: str, bot_id: str):
        self.guard.revoke_live(user_id=user_id,bot_id=bot_id)
        self._audit(user_id=user_id,action="LIVE_REVOKED",bot_id=bot_id,details={})
        return 200,{"ok":True,"bot_id":bot_id,"live_authorized":False}

    def _control(self, **kwargs):
        fn=getattr(self.bot_core,"control_bot",None)
        if fn is None: raise RuntimeError("runtime_control_gateway_missing")
        try: return fn(**kwargs)
        except TypeError: return fn(user_id=kwargs["user_id"],bot_id=kwargs["bot_id"],action=kwargs["action"])

    def _audit(self, *, user_id: str, action: str, bot_id: str, details: dict[str, Any]):
        self.observability.record(user_id=user_id,category="RUNTIME",action=action,severity="INFO",correlation_id=f"stage9:{user_id}:{bot_id}:{action}",resource_type="bot",resource_id=bot_id,details=details)

    @staticmethod
    def _required(body: dict[str, Any], key: str) -> str:
        value=str(body.get(key,"")).strip()
        if not value: raise ValueError(f"{key}_required")
        return value

    @staticmethod
    def _success(value: Any) -> bool:
        if isinstance(value,dict): return bool(value.get("ok",value.get("success",False)))
        return bool(getattr(value,"success",False))

class FailClosedLivePrerequisites:
    def resolve(self, **kwargs) -> dict[str,bool]:
        return {"strategy_human_approved":False,"production_safety_ready":False}
