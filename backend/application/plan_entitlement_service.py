from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True, slots=True)
class PlanDefinition:
    code: str
    max_strategies: int
    max_backtests_per_month: int
    max_broker_connections: int
    max_active_bots: int
    live_trading: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PlanEntitlementService:
    """
    Central SaaS entitlement boundary.

    Limits are enforced server-side and never trusted from frontend input.
    This layer grants product capabilities only; it never talks to MT5/broker.
    """

    PLANS = {
        "STARTER": PlanDefinition(
            code="STARTER",
            max_strategies=3,
            max_backtests_per_month=30,
            max_broker_connections=1,
            max_active_bots=1,
            live_trading=False,
        ),
        "PRO": PlanDefinition(
            code="PRO",
            max_strategies=20,
            max_backtests_per_month=300,
            max_broker_connections=3,
            max_active_bots=3,
            live_trading=True,
        ),
        "SCALE": PlanDefinition(
            code="SCALE",
            max_strategies=100,
            max_backtests_per_month=2000,
            max_broker_connections=10,
            max_active_bots=10,
            live_trading=True,
        ),
    }

    def get_plan(self, plan_code: str) -> PlanDefinition:
        plan = self.PLANS.get(str(plan_code).strip().upper())
        if plan is None:
            raise ValueError("unknown_subscription_plan")
        return plan

    def authorize(
        self,
        *,
        plan_code: str,
        capability: str,
        usage: dict[str, int],
    ) -> dict[str, Any]:
        plan = self.get_plan(plan_code)
        capability = str(capability).strip().upper()

        mapping = {
            "CREATE_STRATEGY": ("strategies", plan.max_strategies),
            "RUN_BACKTEST": (
                "backtests_this_month",
                plan.max_backtests_per_month,
            ),
            "ADD_BROKER_CONNECTION": (
                "broker_connections",
                plan.max_broker_connections,
            ),
            "START_BOT": ("active_bots", plan.max_active_bots),
        }

        if capability == "LIVE_TRADING":
            if not plan.live_trading:
                return self._deny(plan, capability, "plan_live_trading_disabled")
            return self._allow(plan, capability)

        if capability not in mapping:
            return self._deny(plan, capability, "unknown_capability")

        usage_key, limit = mapping[capability]
        current = int(usage.get(usage_key, 0))

        if current < 0:
            return self._deny(plan, capability, "invalid_usage_state")

        if current >= limit:
            return {
                "allowed": False,
                "plan": plan.code,
                "capability": capability,
                "reason": "plan_limit_reached",
                "usage": current,
                "limit": limit,
            }

        return {
            "allowed": True,
            "plan": plan.code,
            "capability": capability,
            "reason": "entitlement_granted",
            "usage": current,
            "limit": limit,
            "remaining_after_action": limit - current - 1,
        }

    def public_plan_payload(self, plan_code: str) -> dict[str, Any]:
        plan = self.get_plan(plan_code)
        return plan.to_dict()

    @staticmethod
    def _allow(plan: PlanDefinition, capability: str) -> dict[str, Any]:
        return {
            "allowed": True,
            "plan": plan.code,
            "capability": capability,
            "reason": "entitlement_granted",
        }

    @staticmethod
    def _deny(
        plan: PlanDefinition,
        capability: str,
        reason: str,
    ) -> dict[str, Any]:
        return {
            "allowed": False,
            "plan": plan.code,
            "capability": capability,
            "reason": reason,
        }
