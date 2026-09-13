from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True, slots=True)
class EntitlementDecision:
    allowed: bool
    capability: str
    reason: str
    plan_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ServerSideEntitlementGate:
    """
    Final server-side licensing boundary before product actions reach Bot Core.

    The client cannot grant itself capabilities. Subscription state and plan
    limits are resolved on the server. START/LIVE actions fail closed before
    Bot Core invocation when billing or entitlement state is invalid.
    """

    def __init__(
        self,
        *,
        subscription_service: Any,
        plan_entitlement_service: Any,
        usage_provider: Any,
        bot_core: Any,
    ) -> None:
        self.subscription_service = subscription_service
        self.plan_entitlement_service = plan_entitlement_service
        self.usage_provider = usage_provider
        self.bot_core = bot_core

    def authorize(
        self,
        *,
        user_id: str,
        capability: str,
    ) -> EntitlementDecision:
        capability = str(capability).strip().upper()

        try:
            context = self.subscription_service.entitlement_context(
                user_id=user_id
            )
        except (LookupError, KeyError, PermissionError):
            return EntitlementDecision(
                allowed=False,
                capability=capability,
                reason="subscription_required",
            )

        if context.get("subscription_status") != "ACTIVE":
            return EntitlementDecision(
                allowed=False,
                capability=capability,
                reason="subscription_inactive",
                plan_code=context.get("plan_code"),
            )

        if context.get("paid_entitlements_allowed") is not True:
            return EntitlementDecision(
                allowed=False,
                capability=capability,
                reason="paid_entitlements_blocked",
                plan_code=context.get("plan_code"),
            )

        usage = self.usage_provider.usage_for(user_id=user_id)
        if not isinstance(usage, dict):
            return EntitlementDecision(
                allowed=False,
                capability=capability,
                reason="usage_state_invalid",
                plan_code=context.get("plan_code"),
            )

        decision = self.plan_entitlement_service.authorize(
            plan_code=context["plan_code"],
            capability=capability,
            usage=usage,
        )

        if decision.get("allowed") is not True:
            return EntitlementDecision(
                allowed=False,
                capability=capability,
                reason=str(decision.get("reason", "entitlement_denied")),
                plan_code=context.get("plan_code"),
            )

        return EntitlementDecision(
            allowed=True,
            capability=capability,
            reason="server_entitlement_granted",
            plan_code=context.get("plan_code"),
        )

    def start_bot(
        self,
        *,
        user_id: str,
        bot_id: str,
    ) -> dict[str, Any]:
        decision = self.authorize(
            user_id=user_id,
            capability="START_BOT",
        )
        if not decision.allowed:
            return {
                "ok": False,
                "reason": decision.reason,
                "bot_core_invoked": False,
            }

        result = self.bot_core.start_bot(
            user_id=user_id,
            bot_id=bot_id,
        )
        return {
            "ok": bool(result.get("ok")),
            "reason": (
                "bot_started"
                if result.get("ok")
                else "bot_core_start_failed"
            ),
            "bot_core_invoked": True,
        }

    def authorize_live(
        self,
        *,
        user_id: str,
    ) -> EntitlementDecision:
        return self.authorize(
            user_id=user_id,
            capability="LIVE_TRADING",
        )
