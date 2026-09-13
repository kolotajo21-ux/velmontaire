from __future__ import annotations

from dataclasses import dataclass, asdict
from collections import defaultdict, deque
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class SecurityDecision:
    allowed: bool
    reason: str
    retry_after_seconds: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SecurityAbuseGuard:
    """
    Day 124 product/API abuse boundary.

    Enforces:
    - authenticated principal binding;
    - strict resource ownership;
    - request/body size limits;
    - identifier/action validation;
    - per-user + per-action rate limiting;
    - server-side entitlement callback;
    - fail-closed behavior before protected downstream invocation.

    This layer performs no direct MT5/broker operations.
    """

    MAX_BODY_BYTES = 64 * 1024
    MAX_ID_LENGTH = 128
    ALLOWED_ACTIONS = {
        "CREATE_STRATEGY",
        "RUN_BACKTEST",
        "START_BOT",
        "PAUSE_BOT",
        "STOP_BOT",
        "LIVE_TRADING",
    }

    def __init__(
        self,
        *,
        now_provider: Callable[[], float],
        window_seconds: int = 60,
        max_requests_per_window: int = 20,
    ) -> None:
        if window_seconds <= 0 or max_requests_per_window <= 0:
            raise ValueError("rate_limit_configuration_invalid")
        self.now_provider = now_provider
        self.window_seconds = int(window_seconds)
        self.max_requests_per_window = int(max_requests_per_window)
        self._requests: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def authorize_request(
        self,
        *,
        authenticated_user_id: str | None,
        claimed_user_id: str | None,
        action: str,
        body_size_bytes: int,
        resource_owner_id: str | None = None,
        resource_id: str | None = None,
        entitlement_check: Callable[[], bool] | None = None,
    ) -> SecurityDecision:
        if not authenticated_user_id:
            return SecurityDecision(False, "authentication_required")

        if claimed_user_id and claimed_user_id != authenticated_user_id:
            return SecurityDecision(False, "principal_spoofing_blocked")

        normalized_action = str(action).strip().upper()
        if normalized_action not in self.ALLOWED_ACTIONS:
            return SecurityDecision(False, "action_not_allowed")

        if body_size_bytes < 0 or body_size_bytes > self.MAX_BODY_BYTES:
            return SecurityDecision(False, "request_body_size_invalid")

        if resource_id is not None:
            if not self._valid_identifier(resource_id):
                return SecurityDecision(False, "resource_identifier_invalid")

        if resource_owner_id is not None:
            if resource_owner_id != authenticated_user_id:
                return SecurityDecision(False, "resource_not_found")

        rate = self._consume_rate_limit(
            user_id=authenticated_user_id,
            action=normalized_action,
        )
        if not rate.allowed:
            return rate

        if entitlement_check is not None:
            try:
                entitled = entitlement_check()
            except Exception:
                return SecurityDecision(False, "entitlement_check_failed")
            if entitled is not True:
                return SecurityDecision(False, "entitlement_denied")

        return SecurityDecision(True, "security_gate_passed")

    def _consume_rate_limit(self, *, user_id: str, action: str) -> SecurityDecision:
        now = float(self.now_provider())
        key = (user_id, action)
        bucket = self._requests[key]
        cutoff = now - self.window_seconds

        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

        if len(bucket) >= self.max_requests_per_window:
            oldest = bucket[0]
            retry = max(1, int(self.window_seconds - (now - oldest)))
            return SecurityDecision(
                False,
                "rate_limit_exceeded",
                retry_after_seconds=retry,
            )

        bucket.append(now)
        return SecurityDecision(True, "rate_limit_ok")

    @classmethod
    def _valid_identifier(cls, value: str) -> bool:
        value = str(value)
        if not value or len(value) > cls.MAX_ID_LENGTH:
            return False
        allowed = set(
            "abcdefghijklmnopqrstuvwxyz"
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            "0123456789-_"
        )
        return all(ch in allowed for ch in value)


class ProtectedActionExecutor:
    """Invokes a downstream action only after SecurityAbuseGuard allows it."""

    def __init__(self, *, guard: SecurityAbuseGuard) -> None:
        self.guard = guard

    def execute(
        self,
        *,
        downstream: Callable[[], Any],
        **security_context: Any,
    ) -> Any:
        decision = self.guard.authorize_request(**security_context)
        if not decision.allowed:
            return {
                "ok": False,
                "reason": decision.reason,
                "retry_after_seconds": decision.retry_after_seconds,
                "downstream_invoked": False,
            }

        result = downstream()
        return {
            "ok": True,
            "reason": "protected_action_completed",
            "result": result,
            "downstream_invoked": True,
        }
