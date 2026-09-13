from __future__ import annotations

from typing import Any

from core.context import (
    ModuleExecutionResult,
    StrategyContext,
)
from core.interfaces import (
    FilterModule,
)
from core.strategy import (
    ModuleRole,
    StrategyModuleDefinition,
)


class SessionFilterModule(
    FilterModule
):
    """
    Universal session filter.

    Использует данные, которые заранее положил
    SessionContextModule в StrategyContext.

    Поддерживает:
    - allowed_sessions;
    - blocked_sessions;
    - require_discount_for_buy;
    - require_premium_for_sell.
    """

    provider = "session_filter"
    role = ModuleRole.FILTER
    version = "1.0.0"

    capabilities = (
        "session_filtering",
        "allowed_sessions",
        "blocked_sessions",
        "premium_discount_filter",
    )

    dependencies = (
        ModuleRole.MARKET,
    )

    def __init__(
        self,
        definition: (
            StrategyModuleDefinition
            | None
        ) = None,
    ) -> None:
        super().__init__(
            definition=definition
        )

        parameters = dict(
            self.definition.parameters
            or {}
        )

        allowed = parameters.get(
            "allowed_sessions",
            [],
        )

        blocked = parameters.get(
            "blocked_sessions",
            [],
        )

        self.allowed_sessions = {
            str(value).upper()
            for value in (
                allowed or []
            )
        }

        self.blocked_sessions = {
            str(value).upper()
            for value in (
                blocked or []
            )
        }

        self.require_discount_for_buy = bool(
            parameters.get(
                "require_discount_for_buy",
                False,
            )
        )

        self.require_premium_for_sell = bool(
            parameters.get(
                "require_premium_for_sell",
                False,
            )
        )

    def execute(
        self,
        context: StrategyContext,
    ) -> ModuleExecutionResult:
        session_context = context.get(
            "session_context"
        )

        if not isinstance(
            session_context,
            dict,
        ):
            return self.failure(
                error="session_context_missing",
            )

        active_session = str(
            session_context.get(
                "active_session",
                "",
            )
            or ""
        ).upper()

        reasons: list[str] = []

        if (
            self.allowed_sessions
            and active_session
            not in self.allowed_sessions
        ):
            reasons.append(
                "session_not_allowed"
            )

        if (
            active_session
            and active_session
            in self.blocked_sessions
        ):
            reasons.append(
                "session_blocked"
            )

        trend_direction = (
            self._trend_direction(
                context
            )
        )

        pd = session_context.get(
            "premium_discount"
        )

        current_price = (
            self._current_price(
                context
            )
        )

        if (
            self.require_discount_for_buy
            and trend_direction
            == "BULLISH"
        ):
            if not self._in_discount(
                current_price=current_price,
                premium_discount=pd,
            ):
                reasons.append(
                    "buy_not_in_discount"
                )

        if (
            self.require_premium_for_sell
            and trend_direction
            == "BEARISH"
        ):
            if not self._in_premium(
                current_price=current_price,
                premium_discount=pd,
            ):
                reasons.append(
                    "sell_not_in_premium"
                )

        passed = not reasons

        data = {
            "passed": passed,
            "active_session": (
                active_session
                or None
            ),
            "trend_direction": (
                trend_direction
            ),
            "current_price": (
                current_price
            ),
            "allowed_sessions": sorted(
                self.allowed_sessions
            ),
            "blocked_sessions": sorted(
                self.blocked_sessions
            ),
            "reasons": list(
                reasons
            ),
        }

        context.put(
            "session_filter",
            data,
        )

        return self.success(
            passed=passed,
            data=data,
            diagnostics={
                "adapter": (
                    "SessionFilterModule"
                ),
                "provider": (
                    self.provider
                ),
                "reason_count": len(
                    reasons
                ),
            },
        )

    @staticmethod
    def _trend_direction(
        context: StrategyContext,
    ) -> str:
        trend = context.get_result(
            role=ModuleRole.TREND
        )

        if trend is None:
            return "NEUTRAL"

        direction = str(
            trend.data.get(
                "direction",
                "NEUTRAL",
            )
        ).upper()

        if direction in {
            "BULLISH",
            "BEARISH",
        }:
            return direction

        return "NEUTRAL"

    @staticmethod
    def _current_price(
        context: StrategyContext,
    ) -> float | None:
        candidates = (
            "M1",
            "M5",
            "M15",
            "H1",
            "H4",
        )

        for timeframe in candidates:
            rates = context.get_rates(
                timeframe
            )

            try:
                if not rates:
                    continue

                last = rates[-1]

                if isinstance(
                    last,
                    dict,
                ):
                    value = last.get(
                        "close"
                    )
                else:
                    value = getattr(
                        last,
                        "close",
                        None,
                    )

                if value is not None:
                    return float(
                        value
                    )
            except Exception:
                continue

        return None

    @staticmethod
    def _in_discount(
        *,
        current_price: float | None,
        premium_discount: Any,
    ) -> bool:
        if (
            current_price is None
            or not isinstance(
                premium_discount,
                dict,
            )
        ):
            return False

        low = premium_discount.get(
            "discount_low"
        )

        high = premium_discount.get(
            "discount_high"
        )

        if (
            low is None
            or high is None
        ):
            return False

        return (
            float(low)
            <= current_price
            <= float(high)
        )

    @staticmethod
    def _in_premium(
        *,
        current_price: float | None,
        premium_discount: Any,
    ) -> bool:
        if (
            current_price is None
            or not isinstance(
                premium_discount,
                dict,
            )
        ):
            return False

        low = premium_discount.get(
            "premium_low"
        )

        high = premium_discount.get(
            "premium_high"
        )

        if (
            low is None
            or high is None
        ):
            return False

        return (
            float(low)
            <= current_price
            <= float(high)
        )