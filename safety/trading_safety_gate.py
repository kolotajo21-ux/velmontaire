from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

class SafetyDecision(str, Enum):
    ALLOWED = "ALLOWED"
    BLOCKED = "BLOCKED"

class SafetyReason(str, Enum):
    ALLOWED = "ALLOWED"
    NEW_ENTRIES_DISABLED = "NEW_ENTRIES_DISABLED"
    RECOVERY_PAUSED = "RECOVERY_PAUSED"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
    MAX_OPEN_POSITIONS = "MAX_OPEN_POSITIONS"
    MAX_ACTIVE_ORDERS = "MAX_ACTIVE_ORDERS"
    EXECUTION_STATE_MISSING = "EXECUTION_STATE_MISSING"

@dataclass(slots=True)
class TradingSafetyConfig:
    max_open_positions: int = 1
    max_active_orders: int = 1
    require_execution_snapshot: bool = True
    block_on_manual_review: bool = True

@dataclass(slots=True)
class TradingSafetyResult:
    decision: SafetyDecision
    reasons: list[SafetyReason] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.decision == SafetyDecision.ALLOWED

    @property
    def blocked(self) -> bool:
        return not self.allowed

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "allowed": self.allowed,
            "blocked": self.blocked,
            "reasons": [x.value for x in self.reasons],
            "diagnostics": dict(self.diagnostics),
        }

class TradingSafetyGate:
    def __init__(self, config: TradingSafetyConfig | None = None) -> None:
        self.config = config or TradingSafetyConfig()
        if self.config.max_open_positions < 0:
            raise ValueError("max_open_positions must be >= 0")
        if self.config.max_active_orders < 0:
            raise ValueError("max_active_orders must be >= 0")

    def evaluate(
        self,
        *,
        execution_snapshot: dict[str, Any] | None,
        recovery_plan: dict[str, Any] | None = None,
        new_entries_allowed: bool = True,
    ) -> TradingSafetyResult:
        reasons: list[SafetyReason] = []

        if not new_entries_allowed:
            reasons.append(SafetyReason.NEW_ENTRIES_DISABLED)

        if execution_snapshot is None:
            if self.config.require_execution_snapshot:
                reasons.append(SafetyReason.EXECUTION_STATE_MISSING)
            active_orders = 0
            open_positions = 0
        else:
            active_orders = self._count(execution_snapshot, "active_orders")
            open_positions = self._count(execution_snapshot, "open_positions")

        if recovery_plan:
            if bool(recovery_plan.get("pause_new_entries", False)):
                reasons.append(SafetyReason.RECOVERY_PAUSED)
            if (
                self.config.block_on_manual_review
                and bool(recovery_plan.get("requires_manual_review", False))
            ):
                reasons.append(SafetyReason.MANUAL_REVIEW_REQUIRED)

        if open_positions >= self.config.max_open_positions:
            reasons.append(SafetyReason.MAX_OPEN_POSITIONS)

        if active_orders >= self.config.max_active_orders:
            reasons.append(SafetyReason.MAX_ACTIVE_ORDERS)

        reasons = self._unique(reasons)

        diagnostics = {
            "active_orders": active_orders,
            "open_positions": open_positions,
            "max_active_orders": self.config.max_active_orders,
            "max_open_positions": self.config.max_open_positions,
        }

        if reasons:
            return TradingSafetyResult(
                decision=SafetyDecision.BLOCKED,
                reasons=reasons,
                diagnostics=diagnostics,
            )

        return TradingSafetyResult(
            decision=SafetyDecision.ALLOWED,
            reasons=[SafetyReason.ALLOWED],
            diagnostics=diagnostics,
        )

    @staticmethod
    def _count(snapshot: dict[str, Any], key: str) -> int:
        value = snapshot.get(key, 0)
        if isinstance(value, int):
            return max(0, value)
        if isinstance(value, (list, tuple)):
            return len(value)
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _unique(reasons: list[SafetyReason]) -> list[SafetyReason]:
        result: list[SafetyReason] = []
        seen: set[SafetyReason] = set()
        for reason in reasons:
            if reason not in seen:
                seen.add(reason)
                result.append(reason)
        return result