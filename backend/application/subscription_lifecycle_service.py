from __future__ import annotations

from dataclasses import dataclass, replace, asdict
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True, slots=True)
class SubscriptionState:
    user_id: str
    plan_code: str
    status: str
    current_period_start: str
    current_period_end: str
    cancel_at_period_end: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SubscriptionLifecycleService:
    """
    Server-side subscription lifecycle boundary.

    ACTIVE is the only state that grants paid entitlements.
    PAST_DUE/CANCELED/EXPIRED fail closed for new paid actions.
    A cancellation scheduled for period end remains ACTIVE until expiry.
    Billing state never directly talks to MT5/broker.
    """

    VALID_STATUSES = {"ACTIVE", "PAST_DUE", "CANCELED", "EXPIRED"}

    def __init__(self, *, runtime_gateway: Any | None = None) -> None:
        self.runtime_gateway = runtime_gateway
        self._subscriptions: dict[str, SubscriptionState] = {}

    def activate(
        self,
        *,
        user_id: str,
        plan_code: str,
        period_start: str,
        period_end: str,
    ) -> SubscriptionState:
        start = self._dt(period_start)
        end = self._dt(period_end)
        if end <= start:
            raise ValueError("subscription_period_invalid")

        state = SubscriptionState(
            user_id=user_id,
            plan_code=str(plan_code).upper(),
            status="ACTIVE",
            current_period_start=start.isoformat(),
            current_period_end=end.isoformat(),
            cancel_at_period_end=False,
        )
        self._subscriptions[user_id] = state
        return state

    def get(self, *, user_id: str) -> SubscriptionState:
        state = self._subscriptions.get(user_id)
        if state is None:
            raise LookupError("subscription_not_found")
        return state

    def change_plan(
        self,
        *,
        user_id: str,
        new_plan_code: str,
    ) -> SubscriptionState:
        state = self.get(user_id=user_id)
        if state.status != "ACTIVE":
            raise RuntimeError("inactive_subscription_plan_change_blocked")
        updated = replace(state, plan_code=str(new_plan_code).upper())
        self._subscriptions[user_id] = updated
        return updated

    def schedule_cancel(self, *, user_id: str) -> SubscriptionState:
        state = self.get(user_id=user_id)
        if state.status != "ACTIVE":
            raise RuntimeError("subscription_not_active")
        updated = replace(state, cancel_at_period_end=True)
        self._subscriptions[user_id] = updated
        return updated

    def apply_billing_status(
        self,
        *,
        user_id: str,
        status: str,
    ) -> SubscriptionState:
        state = self.get(user_id=user_id)
        normalized = str(status).upper()
        if normalized not in self.VALID_STATUSES:
            raise ValueError("subscription_status_invalid")

        updated = replace(state, status=normalized)
        self._subscriptions[user_id] = updated

        if normalized in {"PAST_DUE", "CANCELED", "EXPIRED"}:
            self._restrict_runtime(user_id=user_id, reason=normalized)

        return updated

    def evaluate_time(
        self,
        *,
        user_id: str,
        now: str,
    ) -> SubscriptionState:
        state = self.get(user_id=user_id)
        current = self._dt(now)
        end = self._dt(state.current_period_end)

        if current >= end and state.status == "ACTIVE":
            new_status = "CANCELED" if state.cancel_at_period_end else "EXPIRED"
            state = replace(state, status=new_status)
            self._subscriptions[user_id] = state
            self._restrict_runtime(user_id=user_id, reason=new_status)

        return state

    def entitlement_context(self, *, user_id: str) -> dict[str, Any]:
        state = self.get(user_id=user_id)
        return {
            "user_id": state.user_id,
            "plan_code": state.plan_code,
            "subscription_status": state.status,
            "paid_entitlements_allowed": state.status == "ACTIVE",
            "cancel_at_period_end": state.cancel_at_period_end,
            "current_period_end": state.current_period_end,
        }

    def _restrict_runtime(self, *, user_id: str, reason: str) -> None:
        if self.runtime_gateway is None:
            return
        self.runtime_gateway.restrict_user_runtime(
            user_id=user_id,
            reason=f"SUBSCRIPTION_{reason}",
            policy="BLOCK_NEW_STARTS_KEEP_EXISTING_POSITIONS_MANAGED",
        )

    @staticmethod
    def _dt(value: str) -> datetime:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("subscription_timestamp_invalid") from exc
        if dt.tzinfo is None:
            raise ValueError("subscription_timestamp_timezone_required")
        return dt.astimezone(timezone.utc)
