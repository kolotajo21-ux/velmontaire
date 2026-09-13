from __future__ import annotations
from typing import Any
from webapp.pricing_catalog import public_plans, entitlement, PLANS


class WebBillingApplication:
    def __init__(
        self,
        *,
        subscription_service: Any,
        usage_provider: Any,
        plans=None,
        paddle=None,
    ):
        self.subscriptions = subscription_service
        self.usage = usage_provider
        self.plans = plans
        self.paddle = paddle

    def plans_public(self):
        return 200, {
            "ok": True,
            "currency": "USD",
            "plans": public_plans(),
            "checkout_enabled": False,
        }

    def checkout_config(self):
        cfg = self.paddle.config() if self.paddle else {"configured": False}
        if not cfg.get("configured"):
            return 503, {"ok": False, "error": "paddle_sandbox_not_configured"}
        return 200, {"ok": True, **cfg}

    def me(self, *, user_id: str):
        c = None

        if self.paddle is not None:
            paddle_subscription = self.paddle.subscription_for(user_id)
            if paddle_subscription:
                c = paddle_subscription

        if c is None:
            try:
                c = self.subscriptions.entitlement_context(user_id=user_id)
            except (LookupError, KeyError, PermissionError):
                return 200, {
                    "ok": True,
                    "subscription": None,
                    "usage": {},
                    "plan": None,
                    "entitlements": {},
                    "checkout_enabled": False,
                }

        u = self.usage.usage_for(user_id=user_id)
        if not isinstance(u, dict):
            raise RuntimeError("usage_state_invalid")

        code = str(c.get("plan_code") or "").upper()
        p = PLANS.get(code)

        if not p:
            return 200, {
                "ok": True,
                "subscription": dict(c),
                "usage": u,
                "plan": None,
                "entitlements": {},
                "checkout_enabled": False,
            }

        active = (
            c.get("subscription_status") == "ACTIVE"
            and c.get("paid_entitlements_allowed") is True
        )

        e = {
            f: (
                entitlement(code, f)
                if active
                else {"allowed": False, "reason": "subscription_inactive"}
            )
            for f in p["features"]
        }

        return 200, {
            "ok": True,
            "subscription": dict(c),
            "usage": dict(u),
            "plan": p,
            "entitlements": e,
            "checkout_enabled": False,
        }

    def authorize(self, *, user_id: str, capability: str):
        c = None

        if self.paddle is not None:
            paddle_subscription = self.paddle.subscription_for(user_id)
            if paddle_subscription:
                c = paddle_subscription

        if c is None:
            try:
                c = self.subscriptions.entitlement_context(user_id=user_id)
            except (LookupError, KeyError, PermissionError):
                return {
                    "allowed": False,
                    "capability": capability,
                    "reason": "subscription_required",
                }

        if (
            c.get("subscription_status") != "ACTIVE"
            or c.get("paid_entitlements_allowed") is not True
        ):
            return {
                "allowed": False,
                "capability": capability,
                "reason": "subscription_inactive",
            }

        r = entitlement(c.get("plan_code"), capability)
        r["capability"] = capability
        r["plan_code"] = str(c.get("plan_code") or "").upper()
        return r