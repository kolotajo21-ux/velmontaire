from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True, slots=True)
class BotDashboard:
    bot_id: str
    user_id: str
    status: str
    balance: float
    equity: float
    daily_pnl: float
    daily_pnl_percent: float
    drawdown_percent: float
    open_positions: int
    connection_status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BotControlPanelService:
    """
    Product control/dashboard boundary.

    Backend requests START/PAUSE/STOP through Bot Core only.
    Runtime state is read through Bot Core and normalized for the UI.
    No direct MetaTrader5 dependency or broker order call exists here.
    """

    ALLOWED_TRANSITIONS = {
        "STOPPED": {"START"},
        "RUNNING": {"PAUSE", "STOP"},
        "PAUSED": {"START", "STOP"},
    }

    def __init__(self, *, repository: Any, bot_core: Any) -> None:
        self.repository = repository
        self.bot_core = bot_core

    def command(
        self,
        *,
        user_id: str,
        bot_id: str,
        action: str,
    ) -> BotDashboard:
        bot = self._owned_bot(user_id, bot_id)
        action = str(action).strip().upper()

        current = str(self._field(bot, "status", "STOPPED")).upper()
        allowed = self.ALLOWED_TRANSITIONS.get(current, set())

        if action not in {"START", "PAUSE", "STOP"}:
            raise ValueError("bot_action_invalid")
        if action not in allowed:
            raise RuntimeError(
                f"bot_transition_not_allowed:{current}->{action}"
            )

        result = self.bot_core.control_bot(
            user_id=user_id,
            bot_id=bot_id,
            action=action,
        )
        if not bool(result.get("ok")):
            raise RuntimeError("bot_core_control_failed")

        return self.dashboard(user_id=user_id, bot_id=bot_id)

    def dashboard(
        self,
        *,
        user_id: str,
        bot_id: str,
    ) -> BotDashboard:
        self._owned_bot(user_id, bot_id)

        state = self.bot_core.runtime_status(
            user_id=user_id,
            bot_id=bot_id,
        )
        if not isinstance(state, dict):
            raise RuntimeError("runtime_status_invalid")

        required = (
            "status",
            "balance",
            "equity",
            "daily_pnl",
            "drawdown_percent",
            "open_positions",
            "connection_status",
        )
        missing = [key for key in required if key not in state]
        if missing:
            raise RuntimeError(
                "runtime_status_incomplete:" + ",".join(missing)
            )

        balance = float(state["balance"])
        daily_pnl = float(state["daily_pnl"])
        daily_pct = (
            (daily_pnl / balance) * 100.0
            if balance > 0
            else 0.0
        )

        return BotDashboard(
            bot_id=bot_id,
            user_id=user_id,
            status=str(state["status"]).upper(),
            balance=round(balance, 8),
            equity=round(float(state["equity"]), 8),
            daily_pnl=round(daily_pnl, 8),
            daily_pnl_percent=round(daily_pct, 8),
            drawdown_percent=round(
                float(state["drawdown_percent"]), 8
            ),
            open_positions=int(state["open_positions"]),
            connection_status=str(
                state["connection_status"]
            ).upper(),
        )

    def _owned_bot(self, user_id: str, bot_id: str) -> Any:
        # Day 102/105 repository implementations may expose either name.
        getter = getattr(self.repository, "get_bot_instance", None)
        if getter is None:
            getter = getattr(self.repository, "get_bot", None)
        if getter is None:
            raise RuntimeError("bot_repository_getter_missing")

        try:
            bot = getter(user_id, bot_id)
        except TypeError:
            bot = getter(user_id=user_id, bot_id=bot_id)
        except (KeyError, LookupError, PermissionError):
            raise PermissionError("bot_not_found")

        if bot is None:
            raise PermissionError("bot_not_found")

        owner = self._field(bot, "user_id", None)
        if owner is not None and str(owner) != str(user_id):
            raise PermissionError("bot_not_found")

        return bot

    @staticmethod
    def _field(obj: Any, name: str, default: Any) -> Any:
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)
