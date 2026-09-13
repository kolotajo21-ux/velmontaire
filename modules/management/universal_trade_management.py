from __future__ import annotations

from core.context import (
    ModuleExecutionResult,
    StrategyContext,
)
from core.interfaces import (
    ManagementModule,
)
from core.strategy import (
    ModuleRole,
    StrategyModuleDefinition,
)
from core.trade_management_plan import (
    StopManagementMode,
    TradeManagementPlan,
    TradeManagementStatus,
)


class UniversalTradeManagementModule(
    ManagementModule
):
    """
    Формирует единый план управления подготовленной сделкой.

    Источники:
    - context["entry_signal"]
    - context["risk_plan"]

    Поддерживает:
    - Break Even
    - Partial Close
    - Trailing Stop
    """

    provider = "universal_trade_management"
    role = ModuleRole.MANAGEMENT
    version = "1.0.1"

    capabilities = (
        "break_even",
        "partial_close",
        "trailing_stop",
        "trade_management_plan",
    )

    dependencies = (
        ModuleRole.RISK,
    )

    def __init__(
        self,
        definition: StrategyModuleDefinition | None = None,
    ) -> None:
        super().__init__(definition=definition)

        params = dict(
            self.definition.parameters
            or {}
        )

        self.break_even_enabled = bool(
            params.get("break_even_enabled", True)
        )
        self.break_even_trigger_r = float(
            params.get("break_even_trigger_r", 1.0)
        )
        self.break_even_offset = float(
            params.get("break_even_offset", 0.0)
        )

        self.partial_close_enabled = bool(
            params.get("partial_close_enabled", False)
        )
        self.partial_close_trigger_r = float(
            params.get("partial_close_trigger_r", 1.5)
        )
        self.partial_close_percent = float(
            params.get("partial_close_percent", 50.0)
        )

        self.trailing_enabled = bool(
            params.get("trailing_enabled", False)
        )
        self.trailing_trigger_r = float(
            params.get("trailing_trigger_r", 2.0)
        )
        self.trailing_distance_r = float(
            params.get("trailing_distance_r", 1.0)
        )

    def execute(
        self,
        context: StrategyContext,
    ) -> ModuleExecutionResult:
        entry_signal = context.get(
            "entry_signal"
        )
        if not isinstance(entry_signal, dict):
            return self.failure(
                error="entry_signal_missing"
            )

        risk_plan = context.get(
            "risk_plan"
        )
        if not isinstance(risk_plan, dict):
            return self.failure(
                error="risk_plan_missing"
            )

        try:
            entry_price = float(
                entry_signal["entry_price"]
            )
            stop_loss = float(
                entry_signal["stop_loss"]
            )
            take_profit = float(
                entry_signal["take_profit"]
            )
        except (
            KeyError,
            TypeError,
            ValueError,
        ):
            return self.failure(
                error="entry_signal_prices_invalid"
            )

        try:
            position_size = float(
                risk_plan["position_size"]
            )
        except (
            KeyError,
            TypeError,
            ValueError,
        ):
            return self.failure(
                error="risk_position_size_missing"
            )

        if position_size <= 0:
            return self.failure(
                error="risk_position_size_invalid"
            )

        plan = TradeManagementPlan(
            plan_id=(
                f"{self.provider}:"
                f"{context.symbol}:"
                f"{context.current_time}"
            ),
            symbol=context.symbol,
            entry_price=entry_price,
            initial_stop_loss=stop_loss,
            take_profit=take_profit,
            break_even_enabled=(
                self.break_even_enabled
            ),
            break_even_trigger_r=(
                self.break_even_trigger_r
            ),
            break_even_offset=(
                self.break_even_offset
            ),
            partial_close_enabled=(
                self.partial_close_enabled
            ),
            partial_close_trigger_r=(
                self.partial_close_trigger_r
            ),
            partial_close_percent=(
                self.partial_close_percent
            ),
            trailing_enabled=(
                self.trailing_enabled
            ),
            trailing_trigger_r=(
                self.trailing_trigger_r
            ),
            trailing_distance_r=(
                self.trailing_distance_r
            ),
            status=TradeManagementStatus.ACTIVE,
            stop_mode=StopManagementMode.NONE,
            provider=self.provider,
            created_time=int(
                context.current_time
            ),
            metadata={
                "entry_signal_id": (
                    entry_signal.get("signal_id")
                ),
                "risk_plan_id": (
                    risk_plan.get("plan_id")
                ),
                "position_size": position_size,
            },
        )

        valid, reason = plan.validate()

        if not valid:
            return self.failure(
                error=(
                    reason
                    or "trade_management_plan_invalid"
                ),
                data={
                    "management_ready": False,
                    "management_plan": (
                        plan.to_dict()
                    ),
                },
            )

        plan_dict = plan.to_dict()

        context.put(
            "trade_management_plan",
            plan_dict,
        )
        context.trade[
            "trade_management_plan"
        ] = plan_dict

        return self.success(
            passed=True,
            data={
                "management_ready": True,
                "management_plan": plan_dict,
            },
            diagnostics={
                "provider": self.provider,
                "break_even_enabled": (
                    self.break_even_enabled
                ),
                "partial_close_enabled": (
                    self.partial_close_enabled
                ),
                "trailing_enabled": (
                    self.trailing_enabled
                ),
            },
        )