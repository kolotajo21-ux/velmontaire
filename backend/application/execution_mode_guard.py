from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class LiveConfirmation:
    user_id: str
    bot_id: str
    strategy_version_id: str
    broker_connection_id: str
    confirmed: bool


class ExecutionModeGuard:
    """
    Day 119 PAPER/LIVE separation and explicit LIVE authorization boundary.

    Invariants:
    - PAPER never requires live confirmation.
    - LIVE always requires:
        * explicit user confirmation;
        * verified broker connection;
        * human-approved active strategy version;
        * production safety readiness;
    - confirmation is pinned to bot + exact strategy version + exact broker connection;
    - changing version or broker connection invalidates the previous confirmation;
    - no direct broker/MT5 call is performed here.
    """

    VALID_MODES = {"PAPER", "LIVE"}

    def __init__(self) -> None:
        self._confirmations: dict[
            tuple[str, str, str, str],
            LiveConfirmation,
        ] = {}

    def confirm_live(
        self,
        *,
        user_id: str,
        bot_id: str,
        strategy_version_id: str,
        broker_connection_id: str,
        confirmation_text: str,
    ) -> LiveConfirmation:
        self._require(user_id, "user_id_required")
        self._require(bot_id, "bot_id_required")
        self._require(strategy_version_id, "strategy_version_id_required")
        self._require(broker_connection_id, "broker_connection_id_required")

        normalized = str(confirmation_text).strip().upper()
        if normalized != "ENABLE LIVE TRADING":
            raise ValueError("live_confirmation_phrase_invalid")

        confirmation = LiveConfirmation(
            user_id=user_id,
            bot_id=bot_id,
            strategy_version_id=strategy_version_id,
            broker_connection_id=broker_connection_id,
            confirmed=True,
        )

        self._confirmations[
            (
                user_id,
                bot_id,
                strategy_version_id,
                broker_connection_id,
            )
        ] = confirmation

        return confirmation

    def authorize_start(
        self,
        *,
        user_id: str,
        bot_id: str,
        mode: str,
        strategy_version_id: str,
        broker_connection_id: str | None,
        broker_connection_status: str | None,
        strategy_human_approved: bool,
        production_safety_ready: bool,
    ) -> dict[str, Any]:
        mode = str(mode).strip().upper()

        if mode not in self.VALID_MODES:
            return self._deny("execution_mode_invalid")

        if mode == "PAPER":
            return {
                "allowed": True,
                "mode": "PAPER",
                "requires_live_confirmation": False,
                "reason": "paper_execution_allowed",
            }

        # LIVE must fail closed on every missing prerequisite.
        if not broker_connection_id:
            return self._deny("live_broker_connection_required")

        if str(broker_connection_status).strip().upper() != "VERIFIED":
            return self._deny("live_broker_connection_not_verified")

        if strategy_human_approved is not True:
            return self._deny("live_strategy_not_human_approved")

        if production_safety_ready is not True:
            return self._deny("live_production_safety_not_ready")

        key = (
            user_id,
            bot_id,
            strategy_version_id,
            broker_connection_id,
        )
        confirmation = self._confirmations.get(key)

        if confirmation is None or confirmation.confirmed is not True:
            return self._deny("live_explicit_confirmation_required")

        return {
            "allowed": True,
            "mode": "LIVE",
            "requires_live_confirmation": True,
            "reason": "live_execution_explicitly_authorized",
            "strategy_version_id": strategy_version_id,
            "broker_connection_id": broker_connection_id,
        }

    def revoke_live(
        self,
        *,
        user_id: str,
        bot_id: str,
    ) -> None:
        keys = [
            key
            for key in self._confirmations
            if key[0] == user_id and key[1] == bot_id
        ]
        for key in keys:
            self._confirmations.pop(key, None)

    @staticmethod
    def _deny(reason: str) -> dict[str, Any]:
        return {
            "allowed": False,
            "mode": "LIVE",
            "requires_live_confirmation": True,
            "reason": reason,
        }

    @staticmethod
    def _require(value: str, error: str) -> None:
        if not str(value).strip():
            raise ValueError(error)
