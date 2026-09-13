from __future__ import annotations

from typing import Any

from core.execution_adapter import AdapterExecutionStatus
from strategy_runtime.execution_lifecycle_sync import (
    BrokerExecutionSnapshot,
)


class MT5ExecutionReader:
    """
    Day 66 read-only MT5 execution-state reader.

    Resolution order:
      1. active order by broker_order_id -> SUBMITTED
      2. historical order terminal state -> CANCELLED / REJECTED / FILLED
      3. matching historical deal -> FILLED
      4. otherwise -> unknown (found=False)

    No submit/cancel/modify/close calls are performed here.
    """

    def __init__(self, *, mt5: Any | None = None) -> None:
        if mt5 is None:
            try:
                import MetaTrader5 as mt5_module
            except ImportError as exc:
                raise RuntimeError(
                    "MetaTrader5 package is not installed"
                ) from exc
            mt5 = mt5_module

        self.mt5 = mt5

    def get_execution(
        self,
        *,
        execution_id: str,
        broker_order_id: str | None = None,
    ) -> BrokerExecutionSnapshot | None:
        if not execution_id:
            return None

        if broker_order_id:
            try:
                ticket = int(broker_order_id)
            except (TypeError, ValueError):
                return None

            active = self._active_order(ticket)
            if active is not None:
                return BrokerExecutionSnapshot(
                    found=True,
                    status=AdapterExecutionStatus.SUBMITTED,
                    broker_order_id=str(ticket),
                    metadata={
                        "source": "MT5ExecutionReader",
                        "location": "active_orders",
                    },
                )

            historical = self._historical_order(ticket)
            if historical is not None:
                status = self._map_order_state(
                    getattr(
                        historical,
                        "state",
                        None,
                    )
                )

                if status is not None:
                    return BrokerExecutionSnapshot(
                        found=True,
                        status=status,
                        broker_order_id=str(ticket),
                        metadata={
                            "source": "MT5ExecutionReader",
                            "location": "history_orders",
                            "order_state": getattr(
                                historical,
                                "state",
                                None,
                            ),
                        },
                    )

            deal = self._historical_deal_for_order(
                ticket
            )
            if deal is not None:
                return BrokerExecutionSnapshot(
                    found=True,
                    status=AdapterExecutionStatus.FILLED,
                    broker_order_id=str(ticket),
                    broker_deal_id=self._id_or_none(
                        getattr(
                            deal,
                            "ticket",
                            None,
                        )
                    ),
                    metadata={
                        "source": "MT5ExecutionReader",
                        "location": "history_deals",
                    },
                )

        return BrokerExecutionSnapshot(
            found=False,
            status=None,
            broker_order_id=(
                str(broker_order_id)
                if broker_order_id
                else None
            ),
            metadata={
                "source": "MT5ExecutionReader",
                "reason": "execution_not_found",
            },
        )

    def _active_order(
        self,
        ticket: int,
    ) -> Any | None:
        try:
            orders = self.mt5.orders_get(
                ticket=ticket
            )
        except Exception:
            return None

        if not orders:
            return None

        if len(orders) != 1:
            return None

        return orders[0]

    def _historical_order(
        self,
        ticket: int,
    ) -> Any | None:
        try:
            orders = self.mt5.history_orders_get(
                ticket=ticket
            )
        except Exception:
            return None

        if not orders:
            return None

        if len(orders) != 1:
            return None

        return orders[0]

    def _historical_deal_for_order(
        self,
        ticket: int,
    ) -> Any | None:
        try:
            deals = self.mt5.history_deals_get(
                ticket=ticket
            )
        except TypeError:
            deals = None
        except Exception:
            deals = None

        if deals:
            return deals[-1]

        try:
            deals = self.mt5.history_deals_get(
                position=ticket
            )
        except Exception:
            return None

        if not deals:
            return None

        return deals[-1]

    def _map_order_state(
        self,
        state: Any,
    ) -> AdapterExecutionStatus | None:
        mapping = {}

        self._put_state(
            mapping,
            "ORDER_STATE_STARTED",
            AdapterExecutionStatus.SUBMITTED,
        )
        self._put_state(
            mapping,
            "ORDER_STATE_PLACED",
            AdapterExecutionStatus.SUBMITTED,
        )
        self._put_state(
            mapping,
            "ORDER_STATE_PARTIAL",
            AdapterExecutionStatus.PARTIALLY_FILLED,
        )
        self._put_state(
            mapping,
            "ORDER_STATE_FILLED",
            AdapterExecutionStatus.FILLED,
        )
        self._put_state(
            mapping,
            "ORDER_STATE_CANCELED",
            AdapterExecutionStatus.CANCELLED,
        )
        self._put_state(
            mapping,
            "ORDER_STATE_REJECTED",
            AdapterExecutionStatus.REJECTED,
        )
        self._put_state(
            mapping,
            "ORDER_STATE_EXPIRED",
            AdapterExecutionStatus.CANCELLED,
        )

        return mapping.get(state)

    def _put_state(
        self,
        mapping: dict[Any, AdapterExecutionStatus],
        name: str,
        status: AdapterExecutionStatus,
    ) -> None:
        value = getattr(
            self.mt5,
            name,
            None,
        )
        if value is not None:
            mapping[value] = status

    @staticmethod
    def _id_or_none(
        value: Any,
    ) -> str | None:
        if value in (
            None,
            "",
            0,
            "0",
        ):
            return None

        return str(value)