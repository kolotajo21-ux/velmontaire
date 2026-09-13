from __future__ import annotations

from core.context import (
    ModuleExecutionResult,
    StrategyContext,
)
from core.execution_order import (
    ExecutionDirection,
    ExecutionOrder,
    ExecutionOrderType,
    ExecutionStatus,
)
from core.interfaces import (
    ExecutionModule,
)
from core.strategy import (
    ModuleRole,
    StrategyModuleDefinition,
)
from safety.pre_trade_safety_guard import (
    PreTradeSafetyGuard,
)
from safety.prop_account_state_context import (
    PropAccountStateContextBuilder,
)
from safety.prop_risk_guard import (
    PropRiskConfig,
)
from safety.trading_safety_gate import (
    TradingSafetyConfig,
)


class UniversalExecutionModule(
    ExecutionModule
):
    provider = "universal_execution"
    role = ModuleRole.EXECUTION
    version = "1.4.0"

    capabilities = (
        "execution_order",
        "pending_order",
        "market_order",
        "mt5_ready_order",
        "pre_trade_safety_guard",
        "prop_risk_guard",
        "automatic_prop_account_state",
    )

    dependencies = (
        ModuleRole.RISK,
    )

    def __init__(
        self,
        definition: StrategyModuleDefinition | None = None,
    ) -> None:
        super().__init__(
            definition=definition
        )

        params = dict(
            self.definition.parameters
            or {}
        )

        self.deviation = int(
            params.get(
                "deviation",
                20,
            )
        )

        self.magic = int(
            params.get(
                "magic",
                0,
            )
        )

        self.comment = str(
            params.get(
                "comment",
                "UniversalExecution",
            )
        )

        self.expiration_seconds = int(
            params.get(
                "expiration_seconds",
                0,
            )
        )

        self.safety_enabled = bool(
            params.get(
                "safety_enabled",
                True,
            )
        )

        self.auto_build_prop_state = bool(
            params.get(
                "auto_build_prop_state",
                True,
            )
        )

        self.prop_state_builder = (
            PropAccountStateContextBuilder()
        )

        self.pre_trade_guard = (
            PreTradeSafetyGuard(
                trading_config=(
                    TradingSafetyConfig(
                        max_open_positions=int(
                            params.get(
                                "max_open_positions",
                                1,
                            )
                        ),
                        max_active_orders=int(
                            params.get(
                                "max_active_orders",
                                1,
                            )
                        ),
                        require_execution_snapshot=bool(
                            params.get(
                                "require_execution_snapshot",
                                True,
                            )
                        ),
                        block_on_manual_review=bool(
                            params.get(
                                "block_on_manual_review",
                                True,
                            )
                        ),
                    )
                ),
                prop_config=(
                    PropRiskConfig(
                        daily_loss_limit_percent=float(
                            params.get(
                                "daily_loss_limit_percent",
                                5.0,
                            )
                        ),
                        max_drawdown_percent=float(
                            params.get(
                                "max_drawdown_percent",
                                10.0,
                            )
                        ),
                        max_risk_per_trade_percent=float(
                            params.get(
                                "max_risk_per_trade_percent",
                                1.0,
                            )
                        ),
                        daily_risk_limit_percent=float(
                            params.get(
                                "daily_risk_limit_percent",
                                3.0,
                            )
                        ),
                        max_trades_per_day=int(
                            params.get(
                                "max_trades_per_day",
                                5,
                            )
                        ),
                    )
                ),
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
                error="entry_signal_missing"
            )

        risk_plan = context.get(
            "risk_plan"
        )

        if not isinstance(
            risk_plan,
            dict,
        ):
            return self.failure(
                error="risk_plan_missing"
            )

        if self.safety_enabled:
            if self.auto_build_prop_state:
                try:
                    self.prop_state_builder.build(
                        context
                    )
                except ValueError as exc:
                    return self.success(
                        passed=False,
                        data={
                            "execution_ready": False,
                            "reason": (
                                "prop_account_state_build_failed"
                            ),
                        },
                        diagnostics={
                            "provider": self.provider,
                            "safety_enabled": True,
                            "auto_build_prop_state": True,
                            "prop_state_error": str(
                                exc
                            ),
                        },
                    )

            prop_account_state = context.get(
                "prop_account_state"
            )

            safety = (
                self.pre_trade_guard.evaluate(
                    execution_snapshot=(
                        context.get(
                            "execution_snapshot"
                        )
                    ),
                    recovery_plan=(
                        context.get(
                            "execution_recovery_plan"
                        )
                    ),
                    new_entries_allowed=bool(
                        context.get(
                            "new_entries_allowed",
                            True,
                        )
                    ),
                    account_state=(
                        prop_account_state
                    ),
                    risk_plan=risk_plan,
                )
            )

            safety_data = (
                safety.to_dict()
            )

            context.put(
                "pre_trade_safety_result",
                safety_data,
            )

            context.trade[
                "pre_trade_safety_result"
            ] = safety_data

            if safety.blocked:
                return self.success(
                    passed=False,
                    data={
                        "execution_ready": False,
                        "safety": safety_data,
                        "reason": (
                            "pre_trade_safety_blocked"
                        ),
                    },
                    diagnostics={
                        "provider": self.provider,
                        "safety_enabled": True,
                        "trading_safety_allowed": (
                            safety
                            .trading_safety
                            .allowed
                        ),
                        "prop_risk_allowed": (
                            safety
                            .prop_risk
                            .allowed
                        ),
                    },
                )

        management_plan = context.get(
            "trade_management_plan"
        )

        direction = self._direction(
            entry_signal.get(
                "direction"
            )
        )

        if direction is None:
            return self.failure(
                error="execution_direction_invalid"
            )

        order_type = self._order_type(
            entry_signal.get(
                "order_type"
            )
        )

        if order_type is None:
            return self.failure(
                error="execution_order_type_invalid"
            )

        try:
            volume = float(
                risk_plan[
                    "position_size"
                ]
            )

            entry_price = float(
                entry_signal[
                    "entry_price"
                ]
            )

            stop_loss = float(
                entry_signal[
                    "stop_loss"
                ]
            )

            take_profit = float(
                entry_signal[
                    "take_profit"
                ]
            )

        except (
            KeyError,
            TypeError,
            ValueError,
        ):
            return self.failure(
                error="execution_order_data_invalid"
            )

        expiration_time = None

        if (
            self.expiration_seconds
            > 0
        ):
            expiration_time = (
                int(
                    context.current_time
                )
                + self.expiration_seconds
            )

        order = ExecutionOrder(
            execution_id=(
                f"{self.provider}:"
                f"{context.symbol}:"
                f"{context.current_time}"
            ),
            symbol=context.symbol,
            direction=direction,
            order_type=order_type,
            volume=volume,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            status=(
                ExecutionStatus.READY
            ),
            provider=self.provider,
            created_time=int(
                context.current_time
            ),
            deviation=self.deviation,
            magic=self.magic,
            comment=self.comment,
            expiration_time=(
                expiration_time
            ),
            metadata={
                "entry_signal_id": (
                    entry_signal.get(
                        "signal_id"
                    )
                ),
                "risk_plan_id": (
                    risk_plan.get(
                        "plan_id"
                    )
                ),
                "management_plan_id": (
                    management_plan.get(
                        "plan_id"
                    )
                    if isinstance(
                        management_plan,
                        dict,
                    )
                    else None
                ),
                "risk_percent": (
                    risk_plan.get(
                        "risk_percent"
                    )
                ),
                "risk_amount": (
                    risk_plan.get(
                        "risk_amount"
                    )
                ),
                "poi_provider": (
                    entry_signal.get(
                        "poi_provider"
                    )
                ),
                "poi_type": (
                    entry_signal.get(
                        "poi_type"
                    )
                ),
            },
        )

        valid, reason = (
            order.validate()
        )

        if not valid:
            return self.failure(
                error=(
                    reason
                    or "execution_order_invalid"
                ),
                data={
                    "execution_ready": False,
                    "execution_order": (
                        order.to_dict()
                    ),
                },
            )

        order_dict = (
            order.to_dict()
        )

        context.put(
            "execution_order",
            order_dict,
        )

        context.trade[
            "execution_order"
        ] = order_dict

        return self.success(
            passed=True,
            data={
                "execution_ready": True,
                "execution_order": (
                    order_dict
                ),
            },
            diagnostics={
                "provider": (
                    self.provider
                ),
                "direction": (
                    order.direction.value
                ),
                "order_type": (
                    order.order_type.value
                ),
                "volume": (
                    order.volume
                ),
                "expiration_time": (
                    expiration_time
                ),
                "safety_enabled": (
                    self.safety_enabled
                ),
                "auto_build_prop_state": (
                    self.auto_build_prop_state
                ),
            },
        )

    @staticmethod
    def _direction(
        value: object,
    ) -> ExecutionDirection | None:
        if value is None:
            return None

        normalized = str(
            value
        ).upper()

        if normalized == "BUY":
            return ExecutionDirection.BUY

        if normalized == "SELL":
            return ExecutionDirection.SELL

        return None

    @staticmethod
    def _order_type(
        value: object,
    ) -> ExecutionOrderType | None:
        if value is None:
            return None

        normalized = str(
            value
        ).upper()

        mapping = {
            "MARKET": (
                ExecutionOrderType.MARKET
            ),
            "BUY_LIMIT": (
                ExecutionOrderType.BUY_LIMIT
            ),
            "SELL_LIMIT": (
                ExecutionOrderType.SELL_LIMIT
            ),
            "BUY_STOP": (
                ExecutionOrderType.BUY_STOP
            ),
            "SELL_STOP": (
                ExecutionOrderType.SELL_STOP
            ),
        }

        return mapping.get(
            normalized
        )