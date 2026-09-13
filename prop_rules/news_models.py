from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any

@dataclass(frozen=True, slots=True)
class EconomicEvent:
    event_id: str
    timestamp_utc: str
    impact: str
    currencies: tuple[str, ...]
    title: str = ""
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

@dataclass(frozen=True, slots=True)
class NewsComplianceDecision:
    allowed: bool
    action: str
    reason: str
    matched_event_id: str | None = None
    minutes_from_event: float | None = None
    policy_status: str = "VERIFIED"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
