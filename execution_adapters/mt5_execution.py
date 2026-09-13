from __future__ import annotations

from typing import Any

from core.execution_adapter import (
    AdapterExecutionResult,
    AdapterExecutionStatus,
    ExecutionAdapter,
)
from core.execution_order import (
    ExecutionDirection,
    ExecutionOrder,
    ExecutionOrderType,
)


class MT5ExecutionAdapter(ExecutionAdapter):
    name = "mt5"

    def __init__(
        self,
        *,
        mt5: Any | None = None,
        default_filling: int | None = None,
        default_time_type: int | None = None,
    ) -> None:
        if mt5 is None:
            try:
                import MetaTrader5 as mt5_module
            except ImportError as exc:
                raise RuntimeError(
                    "MetaTrader5 package is not installed"
                ) from exc

            mt5 = mt5_module

        self.mt5 = mt5
        self.default_filling = default_filling
        self.default_time_type = default_time_type

    def build_request(
        self,
        order: ExecutionOrder,
    ) -> dict[str, Any]:
        valid, reason = self.validate_order(
            order
        )

        if not valid:
            raise ValueError(
                reason
                or "execution_order_invalid"
            )

        mt5 = self.mt5

        is_market = (
            order.order_type
            == ExecutionOrderType.MARKET
        )

        request: dict[str, Any] = {
            "action": (
                mt5.TRADE_ACTION_DEAL
                if is_market
                else mt5.TRADE_ACTION_PENDING
            ),
            "symbol": order.symbol,
            "volume": float(order.volume),
            "type": self._map_order_type(
                order
            ),
            "price": float(
                order.entry_price
            ),
            "sl": float(
                order.stop_loss
            ),
            "tp": float(
                order.take_profit
            ),
            "deviation": int(
                order.deviation
            ),
            "magic": int(
                order.magic
            ),
            "comment": str(
                order.comment
            ),
        }

        if self.default_filling is not None:
            request["type_filling"] = int(
                self.default_filling
            )

        if is_market:
            if self.default_time_type is not None:
                request["type_time"] = int(
                    self.default_time_type
                )
        else:
            if order.expiration_time is not None:
                request["type_time"] = (
                    mt5.ORDER_TIME_SPECIFIED
                )
                request["expiration"] = int(
                    order.expiration_time
                )
            elif self.default_time_type is not None:
                request["type_time"] = int(
                    self.default_time_type
                )
            else:
                request["type_time"] = (
                    mt5.ORDER_TIME_GTC
                )

        return request

    def submit(
        self,
        order: ExecutionOrder,
    ) -> AdapterExecutionResult:
        try:
            request = self.build_request(
                order
            )
        except Exception as exc:
            return self.rejected(
                order=order,
                message=str(exc),
            )

        try:
            result = self.mt5.order_send(
                request
            )
        except Exception as exc:
            return AdapterExecutionResult(
                execution_id=(
                    order.execution_id
                ),
                adapter=self.name,
                success=False,
                status=(
                    AdapterExecutionStatus.FAILED
                ),
                requested_volume=float(
                    order.volume
                ),
                requested_price=float(
                    order.entry_price
                ),
                message=str(exc),
                diagnostics={
                    "request": dict(
                        request
                    ),
                },
            )

        if result is None:
            return AdapterExecutionResult(
                execution_id=(
                    order.execution_id
                ),
                adapter=self.name,
                success=False,
                status=(
                    AdapterExecutionStatus.FAILED
                ),
                requested_volume=float(
                    order.volume
                ),
                requested_price=float(
                    order.entry_price
                ),
                message=(
                    "mt5_order_send_returned_none"
                ),
                error_code=(
                    self._last_error()
                ),
                diagnostics={
                    "request": dict(
                        request
                    ),
                },
            )

        retcode = getattr(
            result,
            "retcode",
            None,
        )

        if retcode == getattr(
            self.mt5,
            "TRADE_RETCODE_DONE",
            object(),
        ):
            status = (
                AdapterExecutionStatus.FILLED
            )
            success = True
        elif retcode == getattr(
            self.mt5,
            "TRADE_RETCODE_DONE_PARTIAL",
            object(),
        ):
            status = (
                AdapterExecutionStatus
                .PARTIALLY_FILLED
            )
            success = True
        elif retcode == getattr(
            self.mt5,
            "TRADE_RETCODE_PLACED",
            object(),
        ):
            status = (
                AdapterExecutionStatus.SUBMITTED
            )
            success = True
        else:
            status = (
                AdapterExecutionStatus.REJECTED
            )
            success = False

        return AdapterExecutionResult(
            execution_id=(
                order.execution_id
            ),
            adapter=self.name,
            success=success,
            status=status,
            broker_order_id=(
                self._id_or_none(
                    getattr(
                        result,
                        "order",
                        None,
                    )
                )
            ),
            broker_position_id=(
                self._id_or_none(
                    getattr(
                        result,
                        "deal",
                        None,
                    )
                )
            ),
            requested_volume=float(
                order.volume
            ),
            filled_volume=float(
                getattr(
                    result,
                    "volume",
                    0.0,
                )
                or 0.0
            ),
            requested_price=float(
                order.entry_price
            ),
            filled_price=(
                self._float_or_none(
                    getattr(
                        result,
                        "price",
                        None,
                    )
                )
            ),
            message=str(
                getattr(
                    result,
                    "comment",
                    "",
                )
                or ""
            ),
            error_code=retcode,
            raw=self._result_to_dict(
                result
            ),
            diagnostics={
                "request": dict(
                    request
                ),
            },
        )

    def cancel(
        self,
        *,
        execution_id: str,
        broker_order_id: str | None = None,
    ) -> AdapterExecutionResult:
        if not broker_order_id:
            return self._simple_failure(
                execution_id=(
                    execution_id
                ),
                message=(
                    "broker_order_id_missing"
                ),
            )

        try:
            ticket = int(
                broker_order_id
            )
        except (
            TypeError,
            ValueError,
        ):
            return self._simple_failure(
                execution_id=(
                    execution_id
                ),
                message=(
                    "broker_order_id_invalid"
                ),
            )

        request = {
            "action": (
                self.mt5.TRADE_ACTION_REMOVE
            ),
            "order": ticket,
        }

        return self._send_control_request(
            execution_id=execution_id,
            request=request,
            success_status=(
                AdapterExecutionStatus.CANCELLED
            ),
            broker_order_id=str(
                ticket
            ),
        )

    def modify(
        self,
        *,
        execution_id: str,
        broker_order_id: str | None = None,
        broker_position_id: str | None = None,
        stop_loss: float | None = None,
        take_profit: float | None = None,
    ) -> AdapterExecutionResult:
        if (
            not broker_order_id
            and not broker_position_id
        ):
            return self._simple_failure(
                execution_id=(
                    execution_id
                ),
                message=(
                    "broker_order_or_position_id_missing"
                ),
            )

        if (
            stop_loss is None
            and take_profit is None
        ):
            return self._simple_failure(
                execution_id=(
                    execution_id
                ),
                message=(
                    "no_modification_requested"
                ),
            )

        if broker_position_id:
            try:
                ticket = int(
                    broker_position_id
                )
            except (
                TypeError,
                ValueError,
            ):
                return self._simple_failure(
                    execution_id=(
                        execution_id
                    ),
                    message=(
                        "broker_position_id_invalid"
                    ),
                )

            request: dict[
                str,
                Any,
            ] = {
                "action": (
                    self.mt5
                    .TRADE_ACTION_SLTP
                ),
                "position": ticket,
            }

            if stop_loss is not None:
                request["sl"] = float(
                    stop_loss
                )

            if take_profit is not None:
                request["tp"] = float(
                    take_profit
                )

            return self._send_control_request(
                execution_id=execution_id,
                request=request,
                success_status=(
                    AdapterExecutionStatus.ACCEPTED
                ),
                broker_position_id=str(
                    ticket
                ),
            )

        try:
            ticket = int(
                broker_order_id
            )
        except (
            TypeError,
            ValueError,
        ):
            return self._simple_failure(
                execution_id=(
                    execution_id
                ),
                message=(
                    "broker_order_id_invalid"
                ),
            )

        request = {
            "action": (
                self.mt5.TRADE_ACTION_MODIFY
            ),
            "order": ticket,
        }

        if stop_loss is not None:
            request["sl"] = float(
                stop_loss
            )

        if take_profit is not None:
            request["tp"] = float(
                take_profit
            )

        return self._send_control_request(
            execution_id=execution_id,
            request=request,
            success_status=(
                AdapterExecutionStatus.ACCEPTED
            ),
            broker_order_id=str(
                ticket
            ),
        )


    def close_position(
        self,
        *,
        execution_id: str,
        broker_position_id: str,
        symbol: str | None = None,
        volume: float | None = None,
        deviation: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AdapterExecutionResult:
        """
        Day 62: close an existing MT5 position with an opposite DEAL.

        Safety:
        - position ticket must exist;
        - optional symbol must match broker position;
        - close volume must be positive and cannot exceed live volume;
        - BUY positions are closed with SELL at BID;
        - SELL positions are closed with BUY at ASK;
        - no blind assumptions when broker data is unavailable.
        """
        if not broker_position_id:
            return self._simple_failure(
                execution_id=execution_id,
                message="broker_position_id_missing",
            )

        try:
            ticket = int(broker_position_id)
        except (TypeError, ValueError):
            return self._simple_failure(
                execution_id=execution_id,
                message="broker_position_id_invalid",
            )

        try:
            positions = self.mt5.positions_get(
                ticket=ticket
            )
        except Exception as exc:
            return self._simple_failure(
                execution_id=execution_id,
                message=(
                    f"mt5_positions_get_exception:"
                    f"{type(exc).__name__}:{exc}"
                ),
            )

        if positions is None:
            return self._simple_failure(
                execution_id=execution_id,
                message="mt5_positions_get_returned_none",
                error_code=self._last_error(),
            )

        if len(positions) != 1:
            return self._simple_failure(
                execution_id=execution_id,
                message=(
                    "broker_position_not_found"
                    if len(positions) == 0
                    else "broker_position_not_unique"
                ),
            )

        position = positions[0]

        broker_symbol = str(
            getattr(position, "symbol", "") or ""
        ).strip()

        if not broker_symbol:
            return self._simple_failure(
                execution_id=execution_id,
                message="broker_position_symbol_missing",
            )

        if (
            symbol is not None
            and str(symbol).strip().upper()
            != broker_symbol.upper()
        ):
            return self._simple_failure(
                execution_id=execution_id,
                message="broker_position_symbol_mismatch",
            )

        try:
            live_volume = float(
                getattr(position, "volume")
            )
        except (TypeError, ValueError):
            return self._simple_failure(
                execution_id=execution_id,
                message="broker_position_volume_invalid",
            )

        if live_volume <= 0:
            return self._simple_failure(
                execution_id=execution_id,
                message="broker_position_volume_invalid",
            )

        close_volume = live_volume

        if volume is not None:
            try:
                close_volume = float(volume)
            except (TypeError, ValueError):
                return self._simple_failure(
                    execution_id=execution_id,
                    message="close_volume_invalid",
                )

            if (
                close_volume <= 0
                or close_volume > live_volume
            ):
                return self._simple_failure(
                    execution_id=execution_id,
                    message="close_volume_invalid",
                )

        position_type = getattr(
            position,
            "type",
            None,
        )

        buy_type = getattr(
            self.mt5,
            "POSITION_TYPE_BUY",
            None,
        )
        sell_type = getattr(
            self.mt5,
            "POSITION_TYPE_SELL",
            None,
        )

        if position_type == buy_type:
            close_type = self.mt5.ORDER_TYPE_SELL
            price_side = "bid"
        elif position_type == sell_type:
            close_type = self.mt5.ORDER_TYPE_BUY
            price_side = "ask"
        else:
            return self._simple_failure(
                execution_id=execution_id,
                message="broker_position_side_unsupported",
            )

        try:
            tick = self.mt5.symbol_info_tick(
                broker_symbol
            )
        except Exception as exc:
            return self._simple_failure(
                execution_id=execution_id,
                message=(
                    f"mt5_symbol_info_tick_exception:"
                    f"{type(exc).__name__}:{exc}"
                ),
            )

        if tick is None:
            return self._simple_failure(
                execution_id=execution_id,
                message="mt5_symbol_info_tick_returned_none",
                error_code=self._last_error(),
            )

        try:
            close_price = float(
                getattr(
                    tick,
                    price_side,
                )
            )
        except (TypeError, ValueError):
            return self._simple_failure(
                execution_id=execution_id,
                message="close_price_invalid",
            )

        if close_price <= 0:
            return self._simple_failure(
                execution_id=execution_id,
                message="close_price_invalid",
            )

        request: dict[str, Any] = {
            "action": self.mt5.TRADE_ACTION_DEAL,
            "position": ticket,
            "symbol": broker_symbol,
            "volume": close_volume,
            "type": close_type,
            "price": close_price,
            "deviation": int(
                deviation
                if deviation is not None
                else 20
            ),
            "comment": "generic_position_close",
        }

        if self.default_filling is not None:
            request["type_filling"] = int(
                self.default_filling
            )

        if self.default_time_type is not None:
            request["type_time"] = int(
                self.default_time_type
            )

        try:
            result = self.mt5.order_send(
                request
            )
        except Exception as exc:
            return self._simple_failure(
                execution_id=execution_id,
                message=(
                    f"mt5_close_order_send_exception:"
                    f"{type(exc).__name__}:{exc}"
                ),
                diagnostics={
                    "request": dict(request),
                },
            )

        if result is None:
            return self._simple_failure(
                execution_id=execution_id,
                message="mt5_order_send_returned_none",
                error_code=self._last_error(),
                diagnostics={
                    "request": dict(request),
                },
            )

        retcode = getattr(
            result,
            "retcode",
            None,
        )

        done = getattr(
            self.mt5,
            "TRADE_RETCODE_DONE",
            None,
        )
        partial = getattr(
            self.mt5,
            "TRADE_RETCODE_DONE_PARTIAL",
            None,
        )

        if done is not None and retcode == done:
            success = True
            status = AdapterExecutionStatus.FILLED
        elif (
            partial is not None
            and retcode == partial
        ):
            success = True
            status = AdapterExecutionStatus.PARTIALLY_FILLED
        else:
            success = False
            status = AdapterExecutionStatus.REJECTED

        return AdapterExecutionResult(
            execution_id=execution_id,
            adapter=self.name,
            success=success,
            status=status,
            broker_order_id=self._id_or_none(
                getattr(
                    result,
                    "order",
                    None,
                )
            ),
            broker_position_id=str(ticket),
            requested_volume=float(
                close_volume
            ),
            filled_volume=float(
                getattr(
                    result,
                    "volume",
                    0.0,
                )
                or 0.0
            ),
            requested_price=float(
                close_price
            ),
            filled_price=self._float_or_none(
                getattr(
                    result,
                    "price",
                    None,
                )
            ),
            message=str(
                getattr(
                    result,
                    "comment",
                    "",
                )
                or ""
            ),
            error_code=retcode,
            raw=self._result_to_dict(
                result
            ),
            diagnostics={
                "request": dict(request),
                "position_snapshot": {
                    "ticket": ticket,
                    "symbol": broker_symbol,
                    "volume": live_volume,
                    "type": position_type,
                },
                "metadata": dict(
                    metadata or {}
                ),
            },
        )

    def _map_order_type(
        self,
        order: ExecutionOrder,
    ) -> int:
        mt5 = self.mt5

        if (
            order.order_type
            == ExecutionOrderType.MARKET
        ):
            if (
                order.direction
                == ExecutionDirection.BUY
            ):
                return int(
                    mt5.ORDER_TYPE_BUY
                )

            return int(
                mt5.ORDER_TYPE_SELL
            )

        mapping = {
            ExecutionOrderType.BUY_LIMIT: (
                mt5.ORDER_TYPE_BUY_LIMIT
            ),
            ExecutionOrderType.SELL_LIMIT: (
                mt5.ORDER_TYPE_SELL_LIMIT
            ),
            ExecutionOrderType.BUY_STOP: (
                mt5.ORDER_TYPE_BUY_STOP
            ),
            ExecutionOrderType.SELL_STOP: (
                mt5.ORDER_TYPE_SELL_STOP
            ),
        }

        if order.order_type not in mapping:
            raise ValueError(
                "unsupported_execution_order_type"
            )

        return int(
            mapping[
                order.order_type
            ]
        )

    def _send_control_request(
        self,
        *,
        execution_id: str,
        request: dict[str, Any],
        success_status: (
            AdapterExecutionStatus
        ),
        broker_order_id: str | None = None,
        broker_position_id: str | None = None,
    ) -> AdapterExecutionResult:
        try:
            result = self.mt5.order_send(
                request
            )
        except Exception as exc:
            return self._simple_failure(
                execution_id=(
                    execution_id
                ),
                message=str(exc),
                diagnostics={
                    "request": dict(
                        request
                    ),
                },
            )

        if result is None:
            return self._simple_failure(
                execution_id=(
                    execution_id
                ),
                message=(
                    "mt5_order_send_returned_none"
                ),
                error_code=(
                    self._last_error()
                ),
                diagnostics={
                    "request": dict(
                        request
                    ),
                },
            )

        retcode = getattr(
            result,
            "retcode",
            None,
        )

        done_code = getattr(
            self.mt5,
            "TRADE_RETCODE_DONE",
            None,
        )

        success = (
            done_code is not None
            and retcode == done_code
        )

        return AdapterExecutionResult(
            execution_id=execution_id,
            adapter=self.name,
            success=success,
            status=(
                success_status
                if success
                else AdapterExecutionStatus.REJECTED
            ),
            broker_order_id=(
                broker_order_id
            ),
            broker_position_id=(
                broker_position_id
            ),
            message=str(
                getattr(
                    result,
                    "comment",
                    "",
                )
                or ""
            ),
            error_code=retcode,
            raw=self._result_to_dict(
                result
            ),
            diagnostics={
                "request": dict(
                    request
                ),
            },
        )

    def _simple_failure(
        self,
        *,
        execution_id: str,
        message: str,
        error_code: str | int | None = None,
        diagnostics: dict[
            str,
            Any,
        ] | None = None,
    ) -> AdapterExecutionResult:
        return AdapterExecutionResult(
            execution_id=execution_id,
            adapter=self.name,
            success=False,
            status=(
                AdapterExecutionStatus.REJECTED
            ),
            message=message,
            error_code=error_code,
            diagnostics=dict(
                diagnostics or {}
            ),
        )

    def _last_error(self) -> Any:
        try:
            return self.mt5.last_error()
        except Exception:
            return None

    @staticmethod
    def _result_to_dict(
        result: Any,
    ) -> dict[str, Any]:
        if hasattr(
            result,
            "_asdict",
        ):
            try:
                return dict(
                    result._asdict()
                )
            except Exception:
                pass

        return {
            "retcode": getattr(
                result,
                "retcode",
                None,
            ),
            "order": getattr(
                result,
                "order",
                None,
            ),
            "deal": getattr(
                result,
                "deal",
                None,
            ),
            "volume": getattr(
                result,
                "volume",
                None,
            ),
            "price": getattr(
                result,
                "price",
                None,
            ),
            "comment": getattr(
                result,
                "comment",
                None,
            ),
        }

    @staticmethod
    def _id_or_none(
        value: Any,
    ) -> str | None:
        if value in (
            None,
            0,
            "0",
            "",
        ):
            return None

        return str(
            value
        )

    @staticmethod
    def _float_or_none(
        value: Any,
    ) -> float | None:
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