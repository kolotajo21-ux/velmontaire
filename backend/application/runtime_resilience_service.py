from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True, slots=True)
class ResilienceDecision:
    allowed: bool
    action: str
    reason: str
    requires_reconciliation: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RuntimeResilienceService:
    """
    Product-level reconnect/restart safety coordinator.

    The service never submits orders. It decides whether the runtime may
    continue after connection loss or process restart and requires broker /
    journal reconciliation before execution resumes.
    """

    def __init__(self, *, bot_core: Any) -> None:
        self.bot_core = bot_core
        self._blocked: set[tuple[str, str]] = set()

    def on_disconnect(self, *, user_id: str, bot_id: str) -> ResilienceDecision:
        self._blocked.add((user_id, bot_id))
        self.bot_core.block_new_entries(
            user_id=user_id,
            bot_id=bot_id,
            reason="BROKER_DISCONNECTED",
        )
        return ResilienceDecision(
            allowed=False,
            action="BLOCK_NEW_ENTRIES",
            reason="broker_disconnected",
            requires_reconciliation=True,
        )

    def recover(
        self,
        *,
        user_id: str,
        bot_id: str,
        connection_status: str,
    ) -> ResilienceDecision:
        if str(connection_status).upper() != "CONNECTED":
            return ResilienceDecision(
                allowed=False,
                action="WAIT",
                reason="broker_not_connected",
                requires_reconciliation=True,
            )

        result = self.bot_core.reconcile_runtime_state(
            user_id=user_id,
            bot_id=bot_id,
        )
        if not isinstance(result, dict) or not result.get("ok"):
            self._blocked.add((user_id, bot_id))
            return ResilienceDecision(
                allowed=False,
                action="KEEP_BLOCKED",
                reason="runtime_reconciliation_failed",
                requires_reconciliation=True,
            )

        if result.get("unresolved"):
            self._blocked.add((user_id, bot_id))
            return ResilienceDecision(
                allowed=False,
                action="KEEP_BLOCKED",
                reason="runtime_reconciliation_unresolved",
                requires_reconciliation=True,
            )

        self._blocked.discard((user_id, bot_id))
        self.bot_core.unblock_new_entries(
            user_id=user_id,
            bot_id=bot_id,
        )
        return ResilienceDecision(
            allowed=True,
            action="RESUME",
            reason="runtime_reconciled",
            requires_reconciliation=False,
        )

    def startup_recovery(self, *, user_id: str, bot_id: str) -> ResilienceDecision:
        self._blocked.add((user_id, bot_id))

        result = self.bot_core.recover_after_restart(
            user_id=user_id,
            bot_id=bot_id,
        )
        if not isinstance(result, dict) or not result.get("ok"):
            return ResilienceDecision(
                allowed=False,
                action="KEEP_BLOCKED",
                reason="restart_recovery_failed",
                requires_reconciliation=True,
            )

        if result.get("duplicate_execution_risk") or result.get("unresolved"):
            return ResilienceDecision(
                allowed=False,
                action="KEEP_BLOCKED",
                reason="restart_state_not_safe",
                requires_reconciliation=True,
            )

        self._blocked.discard((user_id, bot_id))
        self.bot_core.unblock_new_entries(
            user_id=user_id,
            bot_id=bot_id,
        )
        return ResilienceDecision(
            allowed=True,
            action="RESUME",
            reason="restart_recovery_complete",
            requires_reconciliation=False,
        )

    def may_submit_new_entry(self, *, user_id: str, bot_id: str) -> bool:
        return (user_id, bot_id) not in self._blocked
