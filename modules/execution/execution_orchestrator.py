from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.context import StrategyContext
from core.execution_order import ExecutionOrder
from infrastructure.execution_lock import (
    ExecutionLock,
    ExecutionLockHandle,
)
from infrastructure.journaled_execution_submitter import (
    JournaledExecutionSubmitter,
)
from infrastructure.runtime_execution_lifecycle import (
    RuntimeExecutionLifecycle,
)
from infrastructure.production_safety_gate import (
    ProductionSafetyGate,
)


@dataclass(slots=True)
class ExecutionOrchestratorResult:
    allowed: bool
    submitted: bool
    reason: str

    runtime_result: dict[str, Any] | None = None
    submission_result: dict[str, Any] | None = None
    lock_result: dict[str, Any] | None = None
    safety_gate_result: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "submitted": self.submitted,
            "reason": self.reason,
            "runtime_result": self.runtime_result,
            "submission_result": self.submission_result,
            "lock_result": self.lock_result,
            "safety_gate_result": self.safety_gate_result,
        }


class ExecutionOrchestrator:
    """
    Single execution gateway with race protection.

    Flow:
        acquire execution_id lock
            ->
        runtime prepare
            ->
        safety / broker / recovery gates
            ->
        crash-safe journal submit
            ->
        fresh broker synchronization
            ->
        persist post-submit runtime state
            ->
        release lock in finally

    Important:
    - successful submission is followed by a fresh broker sync;
    - persisted runtime state therefore contains the broker-side order/position;
    - the next cycle does not compare a stale pre-submit snapshot against
      a fresh post-submit broker snapshot;
    - the same execution_id cannot enter this flow concurrently.
    """

    def __init__(
        self,
        *,
        lifecycle: RuntimeExecutionLifecycle,
        submitter: JournaledExecutionSubmitter,
        execution_lock: ExecutionLock | None = None,
        safety_gate: ProductionSafetyGate | None = None,
    ) -> None:
        self.lifecycle = lifecycle
        self.submitter = submitter
        self.execution_lock = execution_lock
        self.safety_gate = (
            safety_gate
            if safety_gate is not None
            else ProductionSafetyGate()
        )

    def execute(
        self,
        *,
        context: StrategyContext,
        order: ExecutionOrder,
        strict_symbol: bool = True,
    ) -> ExecutionOrchestratorResult:
        lock_handle: ExecutionLockHandle | None = None

        if self.execution_lock is not None:
            lock_handle = self.execution_lock.acquire(
                order.execution_id
            )

            if not lock_handle.acquired:
                return ExecutionOrchestratorResult(
                    allowed=False,
                    submitted=False,
                    reason="EXECUTION_LOCKED",
                    lock_result=lock_handle.to_dict(),
                )

        try:
            return self._execute_locked(
                context=context,
                order=order,
                strict_symbol=strict_symbol,
                lock_handle=lock_handle,
            )
        finally:
            if (
                self.execution_lock is not None
                and lock_handle is not None
                and lock_handle.acquired
            ):
                self.execution_lock.release(
                    lock_handle
                )

    def _execute_locked(
        self,
        *,
        context: StrategyContext,
        order: ExecutionOrder,
        strict_symbol: bool,
        lock_handle: ExecutionLockHandle | None,
    ) -> ExecutionOrchestratorResult:
        order_data = order.to_dict()

        context.put(
            "execution_order",
            order_data,
        )
        context.trade[
            "execution_order"
        ] = order_data

        if lock_handle is not None:
            context.put(
                "execution_lock",
                lock_handle.to_dict(),
            )
            context.trade[
                "execution_lock"
            ] = lock_handle.to_dict()

        runtime = self.lifecycle.prepare_cycle(
            context,
            strict_symbol=strict_symbol,
        )

        runtime_data = runtime.to_dict()

        if runtime.error is not None:
            return self._result(
                allowed=False,
                submitted=False,
                reason=(
                    "RUNTIME_PREPARE_FAILED:"
                    f"{runtime.error}"
                ),
                runtime_result=runtime_data,
                lock_handle=lock_handle,
            )

        safety_gate = self.safety_gate.evaluate(
            context=context,
            runtime_result=runtime,
            lock_acquired=(
                lock_handle.acquired
                if lock_handle is not None
                else None
            ),
            lock_required=(
                self.execution_lock
                is not None
            ),
        )

        safety_gate_data = (
            safety_gate.to_dict()
        )

        context.put(
            "production_safety_gate",
            safety_gate_data,
        )
        context.trade[
            "production_safety_gate"
        ] = safety_gate_data

        if not safety_gate.allowed:
            return self._result(
                allowed=False,
                submitted=False,
                reason=(
                    "PRODUCTION_SAFETY_BLOCKED:"
                    + ",".join(
                        safety_gate.reasons
                    )
                ),
                runtime_result=runtime_data,
                lock_handle=lock_handle,
                safety_gate_result=(
                    safety_gate_data
                ),
            )

        submission = self.submitter.submit(
            order
        )

        submission_data = submission.to_dict()

        if submission.blocked_by_journal:
            self.lifecycle.finish_cycle(
                context
            )

            return self._result(
                allowed=False,
                submitted=False,
                reason="EXECUTION_JOURNAL_BLOCKED",
                runtime_result=runtime_data,
                submission_result=submission_data,
                lock_handle=lock_handle,
            )

        broker_result = submission.broker_result

        if (
            broker_result is None
            or not broker_result.success
        ):
            self.lifecycle.finish_cycle(
                context
            )

            return self._result(
                allowed=True,
                submitted=False,
                reason="BROKER_REJECTED",
                runtime_result=runtime_data,
                submission_result=submission_data,
                lock_handle=lock_handle,
            )

        context.put(
            "last_execution_submission",
            submission_data,
        )
        context.trade[
            "last_execution_submission"
        ] = submission_data

        # -------------------------------------------------
        # CRITICAL DAY 31 FIX
        # -------------------------------------------------
        # prepare_cycle() synchronized BEFORE broker submission.
        # After a successful submit the broker state has changed.
        # Refresh it before persist so runtime_state.json contains
        # the post-submit order/position instead of a stale snapshot.
        post_submit_sync = self.lifecycle.synchronize(
            context
        )

        if post_submit_sync.error is not None:
            # The broker already accepted the order, so submitted=True.
            # We still attempt persistence for diagnostics/recovery.
            finish = self.lifecycle.finish_cycle(
                context
            )

            reason = (
                "SUBMITTED_POST_SYNC_FAILED:"
                f"{post_submit_sync.error}"
            )

            if finish.error is not None:
                reason += (
                    "|RUNTIME_PERSIST_FAILED:"
                    f"{finish.error}"
                )

            return self._result(
                allowed=True,
                submitted=True,
                reason=reason,
                runtime_result=runtime_data,
                submission_result=submission_data,
                lock_handle=lock_handle,
            )

        finish = self.lifecycle.finish_cycle(
            context
        )

        if finish.error is not None:
            return self._result(
                allowed=True,
                submitted=True,
                reason=(
                    "SUBMITTED_RUNTIME_PERSIST_FAILED:"
                    f"{finish.error}"
                ),
                runtime_result=runtime_data,
                submission_result=submission_data,
                lock_handle=lock_handle,
            )

        return self._result(
            allowed=True,
            submitted=True,
            reason="SUBMITTED",
            runtime_result=runtime_data,
            submission_result=submission_data,
            lock_handle=lock_handle,
        )

    @staticmethod
    def _result(
        *,
        allowed: bool,
        submitted: bool,
        reason: str,
        runtime_result: dict[str, Any] | None = None,
        submission_result: dict[str, Any] | None = None,
        lock_handle: ExecutionLockHandle | None = None,
        safety_gate_result: dict[str, Any] | None = None,
    ) -> ExecutionOrchestratorResult:
        return ExecutionOrchestratorResult(
            allowed=allowed,
            submitted=submitted,
            reason=reason,
            runtime_result=runtime_result,
            submission_result=submission_result,
            lock_result=(
                lock_handle.to_dict()
                if lock_handle is not None
                else None
            ),
            safety_gate_result=(
                safety_gate_result
            ),
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
            value = context.get(key)

            if isinstance(value, bool):
                return value

        safety = context.get(
            "pre_trade_safety"
        )

        if isinstance(safety, dict):
            value = safety.get("allowed")

            if isinstance(value, bool):
                return value

        return None