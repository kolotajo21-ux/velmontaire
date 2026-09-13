from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class LaunchCheck:
    name: str
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FinalPublicLaunchReadinessGate:
    """
    Day 130 final technical public-launch gate.

    This gate is intentionally fail-closed. It validates the release candidate,
    environment/configuration, security, customer journey, operational recovery,
    observability and launch-safety invariants through injected check runners.

    It never submits a broker order and cannot fabricate LIVE authorization.
    """

    REQUIRED_CHECKS = (
        "DAY129_RELEASE_CANDIDATE",
        "PRODUCTION_CONFIGURATION",
        "DATABASE_PERSISTENCE",
        "AUTH_SESSION_SECURITY",
        "MULTI_USER_ISOLATION",
        "AI_STRATEGY_FLOW",
        "HUMAN_REVIEW_APPROVAL",
        "BACKTEST_RELIABILITY",
        "MT5_CREDENTIAL_SECURITY",
        "PAPER_LIVE_SEPARATION",
        "RUNTIME_RECOVERY",
        "SUBSCRIPTION_ENTITLEMENTS",
        "ABUSE_PROTECTION",
        "OBSERVABILITY_SUPPORT",
        "PUBLIC_PRODUCT_SURFACE",
        "CUSTOMER_JOURNEY",
    )

    def __init__(self, *, runners: dict[str, Callable[[], Any]]) -> None:
        self.runners = dict(runners)

    def evaluate(self) -> dict[str, Any]:
        missing = [x for x in self.REQUIRED_CHECKS if x not in self.runners]
        if missing:
            return self._blocked(
                reason="required_launch_checks_missing",
                missing=missing,
                checks=[],
            )

        checks: list[LaunchCheck] = []

        for name in self.REQUIRED_CHECKS:
            try:
                raw = self.runners[name]()
                passed = raw is True or (
                    isinstance(raw, dict) and raw.get("passed") is True
                )
                detail = "PASS" if passed else "FAILED"
            except Exception as exc:
                passed = False
                detail = f"EXCEPTION:{type(exc).__name__}"

            checks.append(LaunchCheck(name=name, passed=passed, detail=detail))

            if not passed:
                return self._blocked(
                    reason=f"launch_check_failed:{name}",
                    missing=[],
                    checks=checks,
                )

        return {
            "technical_launch_readiness": "PASS",
            "system_status": "READY_FOR_PUBLIC_LAUNCH",
            "release_candidate": True,
            "public_launch_allowed": True,
            "real_broker_order_submitted": False,
            "live_authorization_fabricated": False,
            "missing_checks": [],
            "blocked_reason": None,
            "checks": [x.to_dict() for x in checks],
        }

    @staticmethod
    def _blocked(
        *,
        reason: str,
        missing: list[str],
        checks: list[LaunchCheck],
    ) -> dict[str, Any]:
        return {
            "technical_launch_readiness": "BLOCKED",
            "system_status": "NOT_READY",
            "release_candidate": False,
            "public_launch_allowed": False,
            "real_broker_order_submitted": False,
            "live_authorization_fabricated": False,
            "missing_checks": list(missing),
            "blocked_reason": reason,
            "checks": [x.to_dict() for x in checks],
        }
