from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any

@dataclass(frozen=True, slots=True)
class PropAccountSnapshot:
    starting_balance: float
    balance: float
    equity: float
    day_start_balance: float
    day_start_equity: float
    high_water_balance: float
    high_water_equity: float
    daily_realized_pnl: float = 0.0
    daily_floating_pnl: float = 0.0
    best_day_profit: float = 0.0
    total_profit: float = 0.0
    trading_days: int = 0
    profitable_days: int = 0
    inactive_days: int = 0
    open_positions: int = 0
    open_risk_amount: float = 0.0

@dataclass(frozen=True, slots=True)
class PropRiskDecision:
    allowed: bool
    action: str
    reason: str
    policy_status: str = "VERIFIED"
    diagnostics: dict[str, Any] | None = None
    def to_dict(self): return asdict(self)
