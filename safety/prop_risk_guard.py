from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PropRiskDecision(str, Enum):
    ALLOWED = "ALLOWED"
    BLOCKED = "BLOCKED"


class PropRiskReason(str, Enum):
    ALLOWED = "ALLOWED"
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
    MAX_DRAWDOWN_LIMIT = "MAX_DRAWDOWN_LIMIT"
    MAX_RISK_PER_TRADE = "MAX_RISK_PER_TRADE"
    DAILY_RISK_LIMIT = "DAILY_RISK_LIMIT"
    MAX_TRADES_PER_DAY = "MAX_TRADES_PER_DAY"
    ACCOUNT_STATE_MISSING = "ACCOUNT_STATE_MISSING"
    RISK_PLAN_MISSING = "RISK_PLAN_MISSING"


@dataclass(slots=True)
class PropRiskConfig:
    daily_loss_limit_percent: float = 5.0
    max_drawdown_percent: float = 10.0
    max_risk_per_trade_percent: float = 1.0
    daily_risk_limit_percent: float = 3.0
    max_trades_per_day: int = 5


@dataclass(slots=True)
class PropRiskResult:
    decision: PropRiskDecision
    reasons: list[PropRiskReason] = field(
        default_factory=list
    )
    diagnostics: dict[str, Any] = field(
        default_factory=dict
    )

    @property
    def allowed(self) -> bool:
        return (
            self.decision
            == PropRiskDecision.ALLOWED
        )

    @property
    def blocked(self) -> bool:
        return not self.allowed

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "allowed": self.allowed,
            "blocked": self.blocked,
            "reasons": [
                reason.value
                for reason in self.reasons
            ],
            "diagnostics": dict(
                self.diagnostics
            ),
        }


class PropRiskGuard:
    """
    Conservative prop-account risk gate.

    Expected account_state:
    {
        "starting_balance": 5000.0,
        "balance": 5000.0,
        "equity": 5000.0,
        "day_start_equity": 5000.0,
        "daily_closed_pnl": 0.0,
        "daily_floating_pnl": 0.0,
        "daily_risk_used_percent": 0.0,
        "trades_today": 0,
    }

    Expected risk_plan:
    {
        "risk_percent": 0.5,
        "risk_amount": 25.0,
    }
    """

    def __init__(
        self,
        config: PropRiskConfig | None = None,
    ) -> None:
        self.config = (
            config
            if config is not None
            else PropRiskConfig()
        )

        self._validate_config()

    def evaluate(
        self,
        *,
        account_state: dict[str, Any] | None,
        risk_plan: dict[str, Any] | None,
    ) -> PropRiskResult:
        reasons: list[
            PropRiskReason
        ] = []

        if not isinstance(
            account_state,
            dict,
        ):
            reasons.append(
                PropRiskReason
                .ACCOUNT_STATE_MISSING
            )

        if not isinstance(
            risk_plan,
            dict,
        ):
            reasons.append(
                PropRiskReason
                .RISK_PLAN_MISSING
            )

        if reasons:
            return PropRiskResult(
                decision=(
                    PropRiskDecision.BLOCKED
                ),
                reasons=reasons,
            )

        assert account_state is not None
        assert risk_plan is not None

        starting_balance = self._float(
            account_state,
            "starting_balance",
        )

        equity = self._float(
            account_state,
            "equity",
        )

        day_start_equity = self._float(
            account_state,
            "day_start_equity",
        )

        daily_closed_pnl = self._float(
            account_state,
            "daily_closed_pnl",
            default=0.0,
        )

        daily_floating_pnl = self._float(
            account_state,
            "daily_floating_pnl",
            default=0.0,
        )

        daily_risk_used_percent = self._float(
            account_state,
            "daily_risk_used_percent",
            default=0.0,
        )

        trades_today = self._int(
            account_state,
            "trades_today",
            default=0,
        )

        risk_percent = self._float(
            risk_plan,
            "risk_percent",
        )

        if (
            starting_balance is None
            or starting_balance <= 0
            or equity is None
            or equity <= 0
            or day_start_equity is None
            or day_start_equity <= 0
            or risk_percent is None
            or risk_percent <= 0
        ):
            return PropRiskResult(
                decision=(
                    PropRiskDecision.BLOCKED
                ),
                reasons=[
                    PropRiskReason
                    .ACCOUNT_STATE_MISSING
                ],
                diagnostics={
                    "reason": (
                        "invalid_account_or_risk_values"
                    ),
                },
            )

        daily_pnl = (
            daily_closed_pnl
            + daily_floating_pnl
        )

        daily_loss_percent = max(
            0.0,
            (
                -daily_pnl
                / day_start_equity
                * 100.0
            ),
        )

        total_drawdown_percent = max(
            0.0,
            (
                starting_balance
                - equity
            )
            / starting_balance
            * 100.0,
        )

        projected_daily_risk = (
            daily_risk_used_percent
            + risk_percent
        )

        if (
            daily_loss_percent
            >= self.config
            .daily_loss_limit_percent
        ):
            reasons.append(
                PropRiskReason
                .DAILY_LOSS_LIMIT
            )

        if (
            total_drawdown_percent
            >= self.config
            .max_drawdown_percent
        ):
            reasons.append(
                PropRiskReason
                .MAX_DRAWDOWN_LIMIT
            )

        if (
            risk_percent
            > self.config
            .max_risk_per_trade_percent
        ):
            reasons.append(
                PropRiskReason
                .MAX_RISK_PER_TRADE
            )

        if (
            projected_daily_risk
            > self.config
            .daily_risk_limit_percent
        ):
            reasons.append(
                PropRiskReason
                .DAILY_RISK_LIMIT
            )

        if (
            trades_today
            >= self.config
            .max_trades_per_day
        ):
            reasons.append(
                PropRiskReason
                .MAX_TRADES_PER_DAY
            )

        diagnostics = {
            "starting_balance": (
                starting_balance
            ),
            "equity": equity,
            "day_start_equity": (
                day_start_equity
            ),
            "daily_pnl": daily_pnl,
            "daily_loss_percent": (
                daily_loss_percent
            ),
            "total_drawdown_percent": (
                total_drawdown_percent
            ),
            "risk_percent": risk_percent,
            "daily_risk_used_percent": (
                daily_risk_used_percent
            ),
            "projected_daily_risk_percent": (
                projected_daily_risk
            ),
            "trades_today": trades_today,
        }

        if reasons:
            return PropRiskResult(
                decision=(
                    PropRiskDecision.BLOCKED
                ),
                reasons=self._unique(
                    reasons
                ),
                diagnostics=diagnostics,
            )

        return PropRiskResult(
            decision=(
                PropRiskDecision.ALLOWED
            ),
            reasons=[
                PropRiskReason.ALLOWED
            ],
            diagnostics=diagnostics,
        )

    def _validate_config(
        self,
    ) -> None:
        if (
            self.config
            .daily_loss_limit_percent
            <= 0
        ):
            raise ValueError(
                "daily_loss_limit_percent must be > 0"
            )

        if (
            self.config
            .max_drawdown_percent
            <= 0
        ):
            raise ValueError(
                "max_drawdown_percent must be > 0"
            )

        if (
            self.config
            .max_risk_per_trade_percent
            <= 0
        ):
            raise ValueError(
                "max_risk_per_trade_percent must be > 0"
            )

        if (
            self.config
            .daily_risk_limit_percent
            <= 0
        ):
            raise ValueError(
                "daily_risk_limit_percent must be > 0"
            )

        if (
            self.config
            .max_trades_per_day
            <= 0
        ):
            raise ValueError(
                "max_trades_per_day must be > 0"
            )

    @staticmethod
    def _float(
        data: dict[str, Any],
        key: str,
        default: float | None = None,
    ) -> float | None:
        value = data.get(
            key,
            default,
        )

        if value is None:
            return None

        try:
            return float(
                value
            )
        except (
            TypeError,
            ValueError,
        ):
            return default

    @staticmethod
    def _int(
        data: dict[str, Any],
        key: str,
        default: int = 0,
    ) -> int:
        value = data.get(
            key,
            default,
        )

        try:
            return int(
                value
            )
        except (
            TypeError,
            ValueError,
        ):
            return default

    @staticmethod
    def _unique(
        reasons: list[PropRiskReason],
    ) -> list[PropRiskReason]:
        result: list[
            PropRiskReason
        ] = []
        seen: set[
            PropRiskReason
        ] = set()

        for reason in reasons:
            if reason in seen:
                continue

            seen.add(
                reason
            )
            result.append(
                reason
            )

        return result