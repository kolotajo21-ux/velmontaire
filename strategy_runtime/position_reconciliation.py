from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.context import StrategyContext


class BrokerPositionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    UNKNOWN = "UNKNOWN"


@dataclass(slots=True)
class BrokerPositionSnapshot:
    found: bool
    status: BrokerPositionStatus
    broker_position_id: str | None = None
    symbol: str | None = None
    side: str | None = None
    volume: float | None = None
    entry_price: float | None = None
    current_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "found": self.found,
            "status": self.status.value,
            "broker_position_id": self.broker_position_id,
            "symbol": self.symbol,
            "side": self.side,
            "volume": self.volume,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class PositionReconciliationResult:
    success: bool
    resolved: bool
    management_allowed: bool
    state: BrokerPositionStatus
    reason: str
    snapshot: BrokerPositionSnapshot | None = None
    changes: dict[str, Any] = field(default_factory=dict)


class GenericPositionStateReconciler:
    def __init__(self, *, broker_reader: Any) -> None:
        self.broker_reader = broker_reader

    def reconcile(
        self,
        context: StrategyContext,
        *,
        broker_position_id: str | None = None,
    ) -> PositionReconciliationResult:
        position_id = (
            str(broker_position_id).strip()
            if broker_position_id is not None
            else str(context.trade.get("broker_position_id", "")).strip()
        )

        if not position_id:
            return self._blocked(context, "broker_position_id_missing")

        try:
            snapshot = self.broker_reader.get_position(
                broker_position_id=position_id,
                symbol=context.symbol,
            )
        except Exception as exc:
            context.add_error(
                "position_reconciliation",
                f"{type(exc).__name__}:{exc}",
            )
            return self._blocked(context, "broker_position_lookup_failed")

        if snapshot is None:
            return self._blocked(context, "broker_position_state_unknown")

        if not isinstance(snapshot, BrokerPositionSnapshot):
            return self._blocked(context, "broker_position_snapshot_invalid")

        if snapshot.status == BrokerPositionStatus.UNKNOWN:
            return self._blocked(
                context,
                "broker_position_state_unknown",
                snapshot,
            )

        if (
            snapshot.broker_position_id
            and snapshot.broker_position_id != position_id
        ):
            return self._blocked(
                context,
                "broker_position_identity_mismatch",
                snapshot,
            )

        if (
            snapshot.symbol
            and snapshot.symbol.strip().upper()
            != context.symbol.strip().upper()
        ):
            return self._blocked(
                context,
                "broker_position_symbol_mismatch",
                snapshot,
            )

        if snapshot.status == BrokerPositionStatus.CLOSED or not snapshot.found:
            context.trade["position_state"] = "CLOSED"
            context.trade["position_management_allowed"] = False
            context.trade["broker_position_state"] = snapshot.to_dict()
            return PositionReconciliationResult(
                True,
                True,
                False,
                BrokerPositionStatus.CLOSED,
                "broker_position_closed",
                snapshot,
                {
                    "position_state": "CLOSED",
                    "position_management_allowed": False,
                },
            )

        if snapshot.status != BrokerPositionStatus.OPEN:
            return self._blocked(
                context,
                "unsupported_broker_position_state",
                snapshot,
            )

        error = self._validate_open(snapshot)
        if error:
            return self._blocked(context, error, snapshot)

        changes = {}
        self._apply(context, changes, "broker_position_id", position_id)
        self._apply(context, changes, "volume", float(snapshot.volume))
        self._apply(context, changes, "entry_price", float(snapshot.entry_price))

        if snapshot.stop_loss is not None:
            self._apply(context, changes, "stop_loss", float(snapshot.stop_loss))
        if snapshot.take_profit is not None:
            self._apply(context, changes, "take_profit", float(snapshot.take_profit))
        if snapshot.side is not None:
            self._apply(context, changes, "side", str(snapshot.side).upper())
        if snapshot.current_price is not None:
            context.market["position_current_price"] = float(snapshot.current_price)

        context.trade["position_state"] = "OPEN"
        context.trade["position_management_allowed"] = True
        context.trade["broker_position_state"] = snapshot.to_dict()

        return PositionReconciliationResult(
            True,
            True,
            True,
            BrokerPositionStatus.OPEN,
            "broker_position_reconciled",
            snapshot,
            changes,
        )

    @staticmethod
    def _validate_open(snapshot: BrokerPositionSnapshot) -> str | None:
        if not snapshot.found:
            return "open_position_not_found"

        if not snapshot.broker_position_id:
            return "open_position_id_missing"

        try:
            volume = float(snapshot.volume)
            entry = float(snapshot.entry_price)
        except (TypeError, ValueError):
            return "open_position_numeric_data_invalid"

        if volume <= 0:
            return "open_position_volume_invalid"
        if entry <= 0:
            return "open_position_entry_price_invalid"

        return None

    @staticmethod
    def _apply(context, changes, key, value):
        previous = context.trade.get(key)
        if previous != value:
            changes[key] = {"before": previous, "after": value}
            context.trade[key] = value

    @staticmethod
    def _blocked(
        context: StrategyContext,
        reason: str,
        snapshot: BrokerPositionSnapshot | None = None,
    ) -> PositionReconciliationResult:
        context.trade["position_management_allowed"] = False
        if snapshot is not None:
            context.trade["broker_position_state"] = snapshot.to_dict()

        return PositionReconciliationResult(
            False,
            False,
            False,
            BrokerPositionStatus.UNKNOWN,
            reason,
            snapshot,
            {},
        )