from __future__ import annotations
from typing import Any

from backend.application.runtime_resilience_service import RuntimeResilienceService
from backend.application.production_observability_service import ProductionObservabilityService


class WebRuntimeFailureApplication:
    def __init__(self, *, resilience: RuntimeResilienceService, bot_core: Any, observability: ProductionObservabilityService) -> None:
        self.resilience = resilience
        self.bot_core = bot_core
        self.observability = observability
        self._last: dict[tuple[str, str], dict[str, Any]] = {}

    def disconnect(self, *, user_id: str, bot_id: str):
        bot_id = self._id(bot_id)
        decision = self.resilience.on_disconnect(user_id=user_id, bot_id=bot_id)
        payload = self._payload(user_id, bot_id, decision)
        self._audit(user_id, bot_id, "RUNTIME_DISCONNECTED", "WARNING", payload)
        return 200, {"ok": True, **payload}

    def recover(self, *, user_id: str, bot_id: str, connection_status: str):
        bot_id = self._id(bot_id)
        decision = self.resilience.recover(
            user_id=user_id,
            bot_id=bot_id,
            connection_status=str(connection_status).strip().upper(),
        )
        payload = self._payload(user_id, bot_id, decision)
        self._audit(
            user_id, bot_id,
            "RUNTIME_RECOVERY_ALLOWED" if decision.allowed else "RUNTIME_RECOVERY_BLOCKED",
            "INFO" if decision.allowed else "WARNING",
            payload,
        )
        return 200, {"ok": True, **payload}

    def restart_recovery(self, *, user_id: str, bot_id: str):
        bot_id = self._id(bot_id)
        decision = self.resilience.startup_recovery(user_id=user_id, bot_id=bot_id)
        payload = self._payload(user_id, bot_id, decision)
        self._audit(
            user_id, bot_id,
            "RUNTIME_RESTART_RECOVERED" if decision.allowed else "RUNTIME_RESTART_BLOCKED",
            "INFO" if decision.allowed else "ERROR",
            payload,
        )
        return 200, {"ok": True, **payload}

    def status(self, *, user_id: str, bot_id: str):
        bot_id = self._id(bot_id)
        may_submit = self.resilience.may_submit_new_entry(user_id=user_id, bot_id=bot_id)
        runtime = {}
        fn = getattr(self.bot_core, "runtime_status", None)
        if fn is not None:
            value = fn(user_id=user_id, bot_id=bot_id)
            if isinstance(value, dict):
                allowed = {
                    "status", "connection_status", "balance", "equity",
                    "daily_pnl", "drawdown_percent", "open_positions",
                    "cycles", "successful_cycles", "failed_cycles", "last_reason",
                }
                runtime = {k: value[k] for k in allowed if k in value}
        return 200, {
            "ok": True,
            "bot_id": bot_id,
            "entries_allowed": bool(may_submit),
            "fail_closed": not bool(may_submit),
            "last_recovery": dict(self._last.get((user_id, bot_id), {})),
            "runtime": runtime,
        }

    def _payload(self, user_id: str, bot_id: str, decision: Any):
        payload = {
            "bot_id": bot_id,
            "entries_allowed": bool(decision.allowed),
            "fail_closed": not bool(decision.allowed),
            "action": decision.action,
            "reason": decision.reason,
            "requires_reconciliation": bool(decision.requires_reconciliation),
        }
        self._last[(user_id, bot_id)] = dict(payload)
        return payload

    def _audit(self, user_id: str, bot_id: str, action: str, severity: str, details: dict[str, Any]):
        self.observability.record(
            user_id=user_id,
            category="RUNTIME",
            action=action,
            severity=severity,
            correlation_id=f"stage10:{user_id}:{bot_id}:{action}",
            resource_type="bot",
            resource_id=bot_id,
            details=details,
        )

    @staticmethod
    def _id(value: str) -> str:
        value = str(value).strip()
        if not value:
            raise ValueError("bot_id_required")
        return value
