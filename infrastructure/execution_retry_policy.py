from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from core.execution_adapter import (
    AdapterExecutionResult,
    AdapterExecutionStatus,
)


class ExecutionRetryAction(str, Enum):
    """
    Production-safe retry decision.

    NEVER_RETRY
        Permanent/configuration/account error. Do not retry blindly.

    REFRESH_AND_RETRY
        Broker explicitly rejected due to quote/price movement.
        Refresh market data / rebuild request before another attempt.

    BACKOFF_AND_RETRY
        Broker explicitly rejected because requests are too frequent.
        Retry only after backoff.

    RECONCILE_BEFORE_RETRY
        Delivery/result is uncertain. Broker state MUST be synchronized
        and reconciled before another submission is considered.

    STOP_MAX_ATTEMPTS
        Retry budget is exhausted.

    SUCCESS
        No retry is needed.
    """

    NEVER_RETRY = "NEVER_RETRY"
    REFRESH_AND_RETRY = "REFRESH_AND_RETRY"
    BACKOFF_AND_RETRY = "BACKOFF_AND_RETRY"
    RECONCILE_BEFORE_RETRY = "RECONCILE_BEFORE_RETRY"
    STOP_MAX_ATTEMPTS = "STOP_MAX_ATTEMPTS"
    SUCCESS = "SUCCESS"


@dataclass(slots=True)
class ExecutionRetryDecision:
    action: ExecutionRetryAction
    retry_allowed: bool
    requires_refresh: bool = False
    requires_backoff: bool = False
    requires_reconciliation: bool = False

    attempt: int = 1
    max_attempts: int = 3

    error_code: str | int | None = None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "retry_allowed": self.retry_allowed,
            "requires_refresh": self.requires_refresh,
            "requires_backoff": self.requires_backoff,
            "requires_reconciliation": (
                self.requires_reconciliation
            ),
            "attempt": int(self.attempt),
            "max_attempts": int(self.max_attempts),
            "error_code": self.error_code,
            "reason": self.reason,
        }


class ExecutionRetryPolicy:
    """
    Classifies MT5 execution failures without blindly resubmitting.

    Critical safety rule:
    uncertain transport/server outcomes are NEVER immediately retried.
    They require fresh broker synchronization + reconciliation first.

    This keeps the Day 27-31 crash/duplicate guarantees intact.
    """

    # Broker explicitly rejected due to quote state.
    REFRESH_CODES = {
        10004,  # TRADE_RETCODE_REQUOTE
        10020,  # TRADE_RETCODE_PRICE_CHANGED
        10021,  # TRADE_RETCODE_PRICE_OFF
    }

    # Broker explicitly says requests are coming too fast.
    BACKOFF_CODES = {
        10024,  # TRADE_RETCODE_TOO_MANY_REQUESTS
    }

    # Outcome/delivery may be uncertain.
    RECONCILE_CODES = {
        10012,  # TRADE_RETCODE_TIMEOUT
        10028,  # TRADE_RETCODE_LOCKED
        10031,  # TRADE_RETCODE_CONNECTION
    }

    # Known permanent/configuration/account conditions.
    NEVER_RETRY_CODES = {
        10006,  # REJECT
        10007,  # CANCEL
        10011,  # ERROR
        10013,  # INVALID
        10014,  # INVALID_VOLUME
        10015,  # INVALID_PRICE
        10016,  # INVALID_STOPS
        10017,  # TRADE_DISABLED
        10018,  # MARKET_CLOSED
        10019,  # NO_MONEY
        10022,  # INVALID_EXPIRATION
        10025,  # NO_CHANGES
        10026,  # SERVER_DISABLES_AT
        10027,  # CLIENT_DISABLES_AT
        10029,  # FROZEN
        10030,  # INVALID_FILL
        10032,  # ONLY_REAL
        10033,  # LIMIT_ORDERS
        10034,  # LIMIT_VOLUME
        10035,  # INVALID_ORDER
        10036,  # POSITION_CLOSED
        10038,  # INVALID_CLOSE_VOLUME
        10039,  # CLOSE_ORDER_EXIST
        10040,  # LIMIT_POSITIONS
        10041,  # REJECT_CANCEL
        10042,  # LONG_ONLY
        10043,  # SHORT_ONLY
        10044,  # CLOSE_ONLY
        10045,  # FIFO_CLOSE
        10046,  # HEDGE_PROHIBITED
    }

    def __init__(
        self,
        *,
        max_attempts: int = 3,
    ) -> None:
        if int(max_attempts) < 1:
            raise ValueError(
                "max_attempts must be >= 1"
            )

        self.max_attempts = int(
            max_attempts
        )

    def evaluate(
        self,
        result: AdapterExecutionResult,
        *,
        attempt: int = 1,
    ) -> ExecutionRetryDecision:
        attempt = max(
            1,
            int(attempt),
        )

        if result.success:
            return self._decision(
                action=ExecutionRetryAction.SUCCESS,
                retry_allowed=False,
                attempt=attempt,
                result=result,
                reason="execution_succeeded",
            )

        if attempt >= self.max_attempts:
            return self._decision(
                action=(
                    ExecutionRetryAction
                    .STOP_MAX_ATTEMPTS
                ),
                retry_allowed=False,
                attempt=attempt,
                result=result,
                reason="retry_budget_exhausted",
            )

        code = self._normalize_error_code(
            result.error_code
        )

        # FAILED means adapter could not establish a definitive
        # broker rejection/acceptance. Never blind retry.
        if (
            result.status
            == AdapterExecutionStatus.FAILED
        ):
            return self._decision(
                action=(
                    ExecutionRetryAction
                    .RECONCILE_BEFORE_RETRY
                ),
                retry_allowed=True,
                requires_reconciliation=True,
                attempt=attempt,
                result=result,
                reason=(
                    "transport_or_adapter_failure_"
                    "requires_broker_reconciliation"
                ),
            )

        if code in self.RECONCILE_CODES:
            return self._decision(
                action=(
                    ExecutionRetryAction
                    .RECONCILE_BEFORE_RETRY
                ),
                retry_allowed=True,
                requires_reconciliation=True,
                attempt=attempt,
                result=result,
                reason=(
                    "uncertain_broker_outcome_"
                    "requires_reconciliation"
                ),
            )

        if code in self.REFRESH_CODES:
            return self._decision(
                action=(
                    ExecutionRetryAction
                    .REFRESH_AND_RETRY
                ),
                retry_allowed=True,
                requires_refresh=True,
                attempt=attempt,
                result=result,
                reason=(
                    "quote_or_price_state_changed"
                ),
            )

        if code in self.BACKOFF_CODES:
            return self._decision(
                action=(
                    ExecutionRetryAction
                    .BACKOFF_AND_RETRY
                ),
                retry_allowed=True,
                requires_backoff=True,
                attempt=attempt,
                result=result,
                reason="broker_rate_limited",
            )

        if code in self.NEVER_RETRY_CODES:
            return self._decision(
                action=(
                    ExecutionRetryAction
                    .NEVER_RETRY
                ),
                retry_allowed=False,
                attempt=attempt,
                result=result,
                reason=(
                    "permanent_or_configuration_error"
                ),
            )

        # Unknown rejection codes are conservative by default:
        # no automatic retry until explicitly classified.
        return self._decision(
            action=(
                ExecutionRetryAction
                .NEVER_RETRY
            ),
            retry_allowed=False,
            attempt=attempt,
            result=result,
            reason="unclassified_error_no_blind_retry",
        )

    def _decision(
        self,
        *,
        action: ExecutionRetryAction,
        retry_allowed: bool,
        attempt: int,
        result: AdapterExecutionResult,
        reason: str,
        requires_refresh: bool = False,
        requires_backoff: bool = False,
        requires_reconciliation: bool = False,
    ) -> ExecutionRetryDecision:
        return ExecutionRetryDecision(
            action=action,
            retry_allowed=retry_allowed,
            requires_refresh=requires_refresh,
            requires_backoff=requires_backoff,
            requires_reconciliation=(
                requires_reconciliation
            ),
            attempt=attempt,
            max_attempts=self.max_attempts,
            error_code=self._display_error_code(
                result.error_code
            ),
            reason=reason,
        )

    @staticmethod
    def _normalize_error_code(
        value: Any,
    ) -> int | None:
        if isinstance(value, bool):
            return None

        if isinstance(value, int):
            return value

        # mt5.last_error() often comes as (code, description).
        if (
            isinstance(value, (tuple, list))
            and value
        ):
            first = value[0]

            if isinstance(first, int):
                return first

        try:
            return int(value)
        except (
            TypeError,
            ValueError,
        ):
            return None

    @staticmethod
    def _display_error_code(
        value: Any,
    ) -> str | int | None:
        if value is None:
            return None

        if isinstance(
            value,
            (str, int),
        ):
            return value

        return str(value)