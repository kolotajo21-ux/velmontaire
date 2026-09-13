from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True, slots=True)
class BetaSimulationResult:
    user_id: str
    completed_steps: tuple[str, ...]
    execution_mode: str
    live_order_submitted: bool
    blocked_reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ClosedBetaSimulation:
    """
    Product-level closed-beta customer simulation.

    It verifies that one user can traverse the SaaS journey through existing
    service/gateway boundaries. This orchestrator never talks directly to MT5
    and never submits a real broker order.
    """

    def __init__(self, *, services: Any) -> None:
        self.services = services

    def run_happy_path(self, *, user_id: str) -> BetaSimulationResult:
        done: list[str] = []

        self._require(self.services.register(user_id=user_id), "registration_failed")
        done.append("REGISTER")

        strategy = self._require(
            self.services.create_strategy(user_id=user_id),
            "strategy_create_failed",
        )
        done.append("CREATE_STRATEGY")

        clarified = self._require(
            self.services.clarify_strategy(
                user_id=user_id,
                strategy_id=strategy["strategy_id"],
            ),
            "clarification_failed",
        )
        done.append("CLARIFY")

        reviewed = self._require(
            self.services.approve_strategy(
                user_id=user_id,
                strategy_version_id=clarified["strategy_version_id"],
            ),
            "review_failed",
        )
        done.append("REVIEW")

        backtest = self._require(
            self.services.run_backtest(
                user_id=user_id,
                strategy_version_id=reviewed["strategy_version_id"],
            ),
            "backtest_failed",
        )
        done.append("BACKTEST")

        self._require(
            self.services.connect_mt5(user_id=user_id),
            "mt5_connection_failed",
        )
        done.append("CONNECT_MT5")

        paper = self._require(
            self.services.start_paper(
                user_id=user_id,
                strategy_version_id=reviewed["strategy_version_id"],
            ),
            "paper_start_failed",
        )
        done.append("PAPER")

        return BetaSimulationResult(
            user_id=user_id,
            completed_steps=tuple(done),
            execution_mode=paper.get("mode", "PAPER"),
            live_order_submitted=False,
            blocked_reason=None,
        )

    def attempt_live_without_confirmation(self, *, user_id: str) -> BetaSimulationResult:
        result = self.services.start_live(
            user_id=user_id,
            explicit_confirmation=None,
        )
        if result.get("ok"):
            raise AssertionError("live_started_without_explicit_confirmation")
        return BetaSimulationResult(
            user_id=user_id,
            completed_steps=(),
            execution_mode="PAPER",
            live_order_submitted=False,
            blocked_reason=result.get("reason", "live_blocked"),
        )

    @staticmethod
    def _require(result: dict[str, Any], reason: str) -> dict[str, Any]:
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise RuntimeError(reason)
        return result
