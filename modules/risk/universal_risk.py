from __future__ import annotations

import math
from typing import Any

from core.context import (
    ModuleExecutionResult,
    StrategyContext,
)
from core.interfaces import (
    RiskModule,
)
from core.risk_plan import (
    RiskPlan,
    RiskPlanStatus,
)
from core.strategy import (
    ModuleRole,
    StrategyModuleDefinition,
)


class UniversalRiskModule(
    RiskModule
):
    """
    Универсальный Risk Engine.

    Источники:
    - context.state["entry_signal"]
    - context.state["account"]
    - context.state["symbol_spec"]

    Рассчитывает:
    - risk_amount
    - stop_distance
    - position_size
    - RiskPlan
    """

    provider = "universal_risk"
    role = ModuleRole.RISK
    version = "1.0.0"

    capabilities = (
        "risk_percent",
        "risk_amount",
        "position_sizing",
        "lot_normalization",
        "symbol_spec_validation",
    )

    dependencies = (
        ModuleRole.ENTRY,
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

        params = dict(
            self.definition.parameters
            or {}
        )

        self.risk_percent = float(
            params.get(
                "risk_percent",
                0.5,
            )
        )

        self.max_risk_percent = float(
            params.get(
                "max_risk_percent",
                2.0,
            )
        )

        self.use_equity = bool(
            params.get(
                "use_equity",
                True,
            )
        )

        self.reject_if_clamped = bool(
            params.get(
                "reject_if_clamped",
                False,
            )
        )

    def execute(
        self,
        context: StrategyContext,
    ) -> ModuleExecutionResult:
        entry_signal = context.get(
            "entry_signal"
        )

        if not isinstance(
            entry_signal,
            dict,
        ):
            return self.failure(
                error="entry_signal_missing",
            )

        account = context.get(
            "account"
        )

        if not isinstance(
            account,
            dict,
        ):
            return self.failure(
                error="account_context_missing",
            )

        symbol_spec = context.get(
            "symbol_spec"
        )

        if not isinstance(
            symbol_spec,
            dict,
        ):
            return self.failure(
                error="symbol_spec_missing",
            )

        balance = self._float_value(
            account,
            "balance",
        )

        equity = self._float_value(
            account,
            "equity",
        )

        if balance is None:
            return self.failure(
                error="balance_missing",
            )

        if equity is None:
            equity = balance

        if (
            self.risk_percent <= 0
            or self.risk_percent
            > self.max_risk_percent
        ):
            return self.success(
                passed=False,
                data={
                    "risk_ready": False,
                    "reason": (
                        "risk_percent_out_of_bounds"
                    ),
                },
            )

        entry_price = self._float_value(
            entry_signal,
            "entry_price",
        )

        stop_loss = self._float_value(
            entry_signal,
            "stop_loss",
        )

        if (
            entry_price is None
            or stop_loss is None
        ):
            return self.failure(
                error="entry_prices_missing",
            )

        stop_distance = abs(
            entry_price
            - stop_loss
        )

        if stop_distance <= 0:
            return self.success(
                passed=False,
                data={
                    "risk_ready": False,
                    "reason": (
                        "stop_distance_invalid"
                    ),
                },
            )

        tick_size = self._float_value(
            symbol_spec,
            "tick_size",
        )

        tick_value = self._float_value(
            symbol_spec,
            "tick_value",
        )

        min_lot = self._float_value(
            symbol_spec,
            "min_lot",
        )

        max_lot = self._float_value(
            symbol_spec,
            "max_lot",
        )

        lot_step = self._float_value(
            symbol_spec,
            "lot_step",
        )

        if (
            tick_size is None
            or tick_value is None
            or min_lot is None
            or max_lot is None
            or lot_step is None
        ):
            return self.failure(
                error="symbol_spec_incomplete",
            )

        if (
            tick_size <= 0
            or tick_value <= 0
            or min_lot <= 0
            or max_lot <= 0
            or lot_step <= 0
        ):
            return self.failure(
                error="symbol_spec_invalid",
            )

        capital_base = (
            equity
            if self.use_equity
            else balance
        )

        risk_amount = (
            capital_base
            * self.risk_percent
            / 100.0
        )

        ticks_to_stop = (
            stop_distance
            / tick_size
        )

        money_risk_per_lot = (
            ticks_to_stop
            * tick_value
        )

        if money_risk_per_lot <= 0:
            return self.failure(
                error="money_risk_per_lot_invalid",
            )

        raw_position_size = (
            risk_amount
            / money_risk_per_lot
        )

        normalized_size = (
            self._normalize_lot(
                value=raw_position_size,
                min_lot=min_lot,
                max_lot=max_lot,
                lot_step=lot_step,
            )
        )

        clamped = (
            normalized_size
            != self._floor_to_step(
                raw_position_size,
                lot_step,
            )
        )

        if (
            self.reject_if_clamped
            and clamped
        ):
            return self.success(
                passed=False,
                data={
                    "risk_ready": False,
                    "reason": (
                        "position_size_clamped"
                    ),
                    "raw_position_size": (
                        raw_position_size
                    ),
                    "normalized_position_size": (
                        normalized_size
                    ),
                },
            )

        plan = RiskPlan(
            plan_id=(
                f"{self.provider}:"
                f"{context.symbol}:"
                f"{context.current_time}"
            ),
            symbol=context.symbol,
            balance=float(
                balance
            ),
            equity=float(
                equity
            ),
            risk_percent=float(
                self.risk_percent
            ),
            risk_amount=float(
                risk_amount
            ),
            entry_price=float(
                entry_price
            ),
            stop_loss=float(
                stop_loss
            ),
            stop_distance=float(
                stop_distance
            ),
            position_size=float(
                normalized_size
            ),
            tick_size=float(
                tick_size
            ),
            tick_value=float(
                tick_value
            ),
            min_lot=float(
                min_lot
            ),
            max_lot=float(
                max_lot
            ),
            lot_step=float(
                lot_step
            ),
            status=(
                RiskPlanStatus.READY
            ),
            provider=self.provider,
            created_time=int(
                context.current_time
            ),
            metadata={
                "capital_base": (
                    "equity"
                    if self.use_equity
                    else "balance"
                ),
                "raw_position_size": (
                    raw_position_size
                ),
                "normalized_position_size": (
                    normalized_size
                ),
                "ticks_to_stop": (
                    ticks_to_stop
                ),
                "money_risk_per_lot": (
                    money_risk_per_lot
                ),
                "clamped": (
                    clamped
                ),
            },
        )

        valid, reason = (
            plan.validate()
        )

        if not valid:
            return self.failure(
                error=(
                    reason
                    or "risk_plan_invalid"
                ),
                data={
                    "risk_ready": False,
                    "risk_plan": (
                        plan.to_dict()
                    ),
                },
            )

        context.put(
            "risk_plan",
            plan.to_dict(),
        )

        context.trade[
            "risk_plan"
        ] = plan.to_dict()

        return self.success(
            passed=True,
            data={
                "risk_ready": True,
                "risk_plan": (
                    plan.to_dict()
                ),
            },
            diagnostics={
                "provider": (
                    self.provider
                ),
                "risk_percent": (
                    self.risk_percent
                ),
                "position_size": (
                    normalized_size
                ),
                "risk_amount": (
                    risk_amount
                ),
            },
        )

    @staticmethod
    def _normalize_lot(
        *,
        value: float,
        min_lot: float,
        max_lot: float,
        lot_step: float,
    ) -> float:
        floored = (
            UniversalRiskModule
            ._floor_to_step(
                value,
                lot_step,
            )
        )

        normalized = max(
            min_lot,
            min(
                floored,
                max_lot,
            ),
        )

        decimals = (
            UniversalRiskModule
            ._step_decimals(
                lot_step
            )
        )

        return round(
            normalized,
            decimals,
        )

    @staticmethod
    def _floor_to_step(
        value: float,
        step: float,
    ) -> float:
        if step <= 0:
            return value

        return (
            math.floor(
                value / step
                + 1e-12
            )
            * step
        )

    @staticmethod
    def _step_decimals(
        step: float,
    ) -> int:
        text = (
            f"{step:.10f}"
            .rstrip("0")
        )

        if "." not in text:
            return 0

        return len(
            text.split(
                "."
            )[1]
        )

    @staticmethod
    def _float_value(
        data: dict[str, Any],
        key: str,
    ) -> float | None:
        value = data.get(
            key
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
            return None