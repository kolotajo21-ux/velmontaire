from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True, slots=True)
class JourneyStep:
    code: str
    title: str
    status: str
    blocked_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CustomerJourneyService:
    """
    Builds a deterministic dashboard journey from server-owned product state.

    The frontend receives status/navigation data only. It cannot mark protected
    stages complete or bypass review, backtest, broker, PAPER or LIVE gates.
    """

    ORDER = (
        ("ACCOUNT", "Account"),
        ("STRATEGY", "Create strategy"),
        ("CLARIFICATION", "AI clarification"),
        ("REVIEW", "Human review"),
        ("BACKTEST", "Backtest"),
        ("COMPARE", "Compare versions"),
        ("MT5", "Connect MT5"),
        ("PAPER", "Run PAPER"),
        ("LIVE", "Authorize LIVE"),
        ("MONITOR", "Monitor bot"),
    )

    def build(self, state: dict[str, Any]) -> dict[str, Any]:
        completed = set()

        if state.get("authenticated"):
            completed.add("ACCOUNT")
        if state.get("strategy_exists"):
            completed.add("STRATEGY")
        if state.get("clarification_ready"):
            completed.add("CLARIFICATION")
        if state.get("human_approved"):
            completed.add("REVIEW")
        if state.get("backtest_completed"):
            completed.add("BACKTEST")
        if state.get("comparison_available"):
            completed.add("COMPARE")
        if state.get("mt5_verified"):
            completed.add("MT5")
        if state.get("paper_ready"):
            completed.add("PAPER")
        if state.get("live_authorized"):
            completed.add("LIVE")
        if state.get("runtime_monitoring"):
            completed.add("MONITOR")

        prerequisites = {
            "STRATEGY": "ACCOUNT",
            "CLARIFICATION": "STRATEGY",
            "REVIEW": "CLARIFICATION",
            "BACKTEST": "REVIEW",
            "COMPARE": "BACKTEST",
            "MT5": "REVIEW",
            "PAPER": "MT5",
            "LIVE": "PAPER",
            "MONITOR": "PAPER",
        }

        steps = []
        first_actionable = None

        for code, title in self.ORDER:
            if code in completed:
                status = "COMPLETED"
                reason = None
            else:
                prerequisite = prerequisites.get(code)
                if prerequisite and prerequisite not in completed:
                    status = "BLOCKED"
                    reason = f"requires_{prerequisite.lower()}"
                else:
                    status = "ACTION_REQUIRED"
                    reason = None
                    if first_actionable is None:
                        first_actionable = code

            steps.append(JourneyStep(code, title, status, reason).to_dict())

        mode = "LIVE" if "LIVE" in completed else ("PAPER" if "PAPER" in completed else "SETUP")

        return {
            "steps": steps,
            "next_action": first_actionable,
            "execution_mode": mode,
            "strategy_version_id": state.get("strategy_version_id"),
            "backtest_id": state.get("backtest_id"),
            "bot_id": state.get("bot_id"),
        }
