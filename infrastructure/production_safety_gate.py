from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.context import StrategyContext


@dataclass(slots=True)
class ProductionSafetyGateResult:
    allowed: bool
    reasons: list[str] = field(
        default_factory=list
    )
    diagnostics: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": bool(self.allowed),
            "reasons": list(self.reasons),
            "diagnostics": dict(
                self.diagnostics
            ),
        }


class ProductionSafetyGate:
    """
    Final fail-closed safety gate before broker submission.

    It never submits, modifies, or cancels broker orders.

    Required runtime guarantees:
    - fresh broker synchronization completed;
    - broker reconciliation completed;
    - recovery evaluation completed;
    - refreshed runtime state persisted;
    - broker submission is allowed;
    - new entries are allowed;
    - no manual review is required;
    - no duplicate execution was detected;
    - pre-trade safety must explicitly approve execution.

    Optional strategy/symbol flags are honored when present:
    - strategy_execution_allowed
    - symbol_execution_allowed
    """

    def evaluate(
        self,
        *,
        context: StrategyContext,
        runtime_result: Any,
        lock_acquired: bool | None = None,
        lock_required: bool = False,
    ) -> ProductionSafetyGateResult:
        reasons: list[str] = []

        runtime_error = getattr(
            runtime_result,
            "error",
            None,
        )

        synchronized = bool(
            getattr(
                runtime_result,
                "synchronized",
                False,
            )
        )
        reconciled = bool(
            getattr(
                runtime_result,
                "reconciled",
                False,
            )
        )
        recovered = bool(
            getattr(
                runtime_result,
                "recovered",
                False,
            )
        )
        persisted = bool(
            getattr(
                runtime_result,
                "persisted",
                False,
            )
        )
        submission_allowed = bool(
            getattr(
                runtime_result,
                "submission_allowed",
                False,
            )
        )
        new_entries_allowed = bool(
            getattr(
                runtime_result,
                "new_entries_allowed",
                False,
            )
        )

        if runtime_error is not None:
            reasons.append(
                "RUNTIME_ERROR"
            )

        if not synchronized:
            reasons.append(
                "BROKER_STATE_NOT_SYNCHRONIZED"
            )

        if not reconciled:
            reasons.append(
                "BROKER_NOT_RECONCILED"
            )

        if not recovered:
            reasons.append(
                "RECOVERY_NOT_EVALUATED"
            )

        if not persisted:
            reasons.append(
                "RUNTIME_STATE_NOT_PERSISTED"
            )

        if not submission_allowed:
            reasons.append(
                "BROKER_SUBMISSION_DISABLED"
            )

        if not new_entries_allowed:
            reasons.append(
                "NEW_ENTRIES_DISABLED"
            )

        if (
            context.get(
                "manual_review_required"
            )
            is True
        ):
            reasons.append(
                "MANUAL_REVIEW_REQUIRED"
            )

        if (
            context.get(
                "duplicate_execution_detected"
            )
            is True
        ):
            reasons.append(
                "DUPLICATE_EXECUTION"
            )

        recovery_plan = context.get(
            "execution_recovery_plan"
        )

        if isinstance(
            recovery_plan,
            dict,
        ):
            if (
                recovery_plan.get(
                    "requires_manual_review"
                )
                is True
                or recovery_plan.get(
                    "manual_review_required"
                )
                is True
            ):
                reasons.append(
                    "RECOVERY_MANUAL_REVIEW_REQUIRED"
                )

            if (
                recovery_plan.get(
                    "pause_new_entries"
                )
                is True
            ):
                reasons.append(
                    "RECOVERY_PAUSED"
                )

        safety_allowed = (
            self._read_safety_allowed(
                context
            )
        )

        # Critical Day 39 behavior:
        # missing safety approval is not treated as approval.
        if safety_allowed is not True:
            reasons.append(
                "PRE_TRADE_SAFETY_NOT_APPROVED"
            )

        strategy_allowed = context.get(
            "strategy_execution_allowed"
        )

        if strategy_allowed is False:
            reasons.append(
                "STRATEGY_EXECUTION_DISABLED"
            )

        symbol_allowed = context.get(
            "symbol_execution_allowed"
        )

        if symbol_allowed is False:
            reasons.append(
                "SYMBOL_EXECUTION_DISABLED"
            )

        if lock_required:
            if lock_acquired is not True:
                reasons.append(
                    "EXECUTION_LOCK_NOT_ACQUIRED"
                )

        # Preserve order while removing duplicates.
        unique_reasons: list[str] = []

        for reason in reasons:
            if reason not in unique_reasons:
                unique_reasons.append(
                    reason
                )

        diagnostics = {
            "runtime_error": runtime_error,
            "synchronized": synchronized,
            "reconciled": reconciled,
            "recovered": recovered,
            "persisted": persisted,
            "submission_allowed": (
                submission_allowed
            ),
            "new_entries_allowed": (
                new_entries_allowed
            ),
            "pre_trade_safety_allowed": (
                safety_allowed
            ),
            "lock_required": bool(
                lock_required
            ),
            "lock_acquired": (
                lock_acquired
            ),
            "strategy_execution_allowed": (
                strategy_allowed
            ),
            "symbol_execution_allowed": (
                symbol_allowed
            ),
        }

        return ProductionSafetyGateResult(
            allowed=not unique_reasons,
            reasons=unique_reasons,
            diagnostics=diagnostics,
        )

    @staticmethod
    def _read_safety_allowed(
        context: StrategyContext,
    ) -> bool | None:
        for key in (
            "pre_trade_safety_allowed",
            "safety_allowed",
            "execution_safety_allowed",
        ):
            value = context.get(
                key
            )

            if isinstance(
                value,
                bool,
            ):
                return value

        safety = context.get(
            "pre_trade_safety"
        )

        if isinstance(
            safety,
            dict,
        ):
            value = safety.get(
                "allowed"
            )

            if isinstance(
                value,
                bool,
            ):
                return value

        return None