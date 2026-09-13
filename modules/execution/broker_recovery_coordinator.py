from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from execution_state.recovery_policy import (
    RecoveryPlan,
    RecoveryPolicy,
)
from modules.execution.broker_reconciler import (
    BrokerReconciliationReport,
)


@dataclass(slots=True)
class BrokerRecoveryDecision:
    report: BrokerReconciliationReport
    recovery_plan: RecoveryPlan

    submission_allowed: bool
    new_entries_allowed: bool

    @property
    def requires_manual_review(self) -> bool:
        return (
            self.recovery_plan
            .requires_manual_review
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "submission_allowed": (
                self.submission_allowed
            ),
            "new_entries_allowed": (
                self.new_entries_allowed
            ),
            "requires_manual_review": (
                self.requires_manual_review
            ),
            "broker_reconciliation": (
                self.report.to_dict()
            ),
            "recovery_plan": (
                self.recovery_plan.to_dict()
            ),
        }


class BrokerRecoveryCoordinator:
    """
    Converts BrokerReconciler output into final runtime safety decisions.

    Rules:
    - duplicate candidate execution -> submission blocked;
    - RecoveryPolicy can pause all new entries;
    - manual-review conditions block new entries;
    - missing local references can be cleaned without necessarily pausing;
    - no broker mutation is performed here.
    """

    def __init__(
        self,
        policy: RecoveryPolicy | None = None,
    ) -> None:
        self.policy = (
            policy
            if policy is not None
            else RecoveryPolicy()
        )

    def evaluate(
        self,
        report: BrokerReconciliationReport,
    ) -> BrokerRecoveryDecision:
        recovery_plan = (
            self.policy.build_plan(
                report.reconciliation
            )
        )

        submission_allowed = bool(
            report.can_submit_candidate
            and recovery_plan.safe_to_continue
            and not recovery_plan.pause_new_entries
        )

        new_entries_allowed = bool(
            recovery_plan.safe_to_continue
            and not recovery_plan.pause_new_entries
            and not report.broker_duplicate_detected
        )

        # A duplicate candidate may be blocked locally while the
        # broader account state remains safe. In that case we do not
        # globally disable every future entry.
        if (
            report.duplicate_execution
            and report.reconciliation.clean
        ):
            new_entries_allowed = True
            submission_allowed = False

        return BrokerRecoveryDecision(
            report=report,
            recovery_plan=recovery_plan,
            submission_allowed=(
                submission_allowed
            ),
            new_entries_allowed=(
                new_entries_allowed
            ),
        )