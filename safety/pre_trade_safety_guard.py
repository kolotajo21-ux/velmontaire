from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from safety.prop_risk_guard import (
    PropRiskConfig,
    PropRiskGuard,
    PropRiskResult,
)
from safety.trading_safety_gate import (
    TradingSafetyConfig,
    TradingSafetyGate,
    TradingSafetyResult,
)


@dataclass(slots=True)
class PreTradeSafetyResult:
    allowed: bool
    trading_safety: TradingSafetyResult
    prop_risk: PropRiskResult

    @property
    def blocked(self) -> bool:
        return not self.allowed

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "blocked": self.blocked,
            "trading_safety": (
                self.trading_safety.to_dict()
            ),
            "prop_risk": (
                self.prop_risk.to_dict()
            ),
        }


class PreTradeSafetyGuard:
    """
    Final combined pre-trade guard.

    Both layers must allow the trade:
    1. broker/execution safety;
    2. prop-account risk safety.
    """

    def __init__(
        self,
        *,
        trading_config: (
            TradingSafetyConfig | None
        ) = None,
        prop_config: (
            PropRiskConfig | None
        ) = None,
    ) -> None:
        self.trading_gate = (
            TradingSafetyGate(
                trading_config
            )
        )

        self.prop_guard = (
            PropRiskGuard(
                prop_config
            )
        )

    def evaluate(
        self,
        *,
        execution_snapshot: (
            dict[str, Any] | None
        ),
        recovery_plan: (
            dict[str, Any] | None
        ),
        new_entries_allowed: bool,
        account_state: (
            dict[str, Any] | None
        ),
        risk_plan: (
            dict[str, Any] | None
        ),
    ) -> PreTradeSafetyResult:
        trading_result = (
            self.trading_gate.evaluate(
                execution_snapshot=(
                    execution_snapshot
                ),
                recovery_plan=(
                    recovery_plan
                ),
                new_entries_allowed=(
                    new_entries_allowed
                ),
            )
        )

        prop_result = (
            self.prop_guard.evaluate(
                account_state=(
                    account_state
                ),
                risk_plan=risk_plan,
            )
        )

        allowed = (
            trading_result.allowed
            and prop_result.allowed
        )

        return PreTradeSafetyResult(
            allowed=allowed,
            trading_safety=(
                trading_result
            ),
            prop_risk=prop_result,
        )