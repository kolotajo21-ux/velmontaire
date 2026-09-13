from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class UserRecord:
    user_id: str
    email: str
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(frozen=True, slots=True)
class StrategyRecord:
    strategy_id: str
    user_id: str
    name: str
    active_version_id: str | None = None
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(frozen=True, slots=True)
class StrategyVersionRecord:
    version_id: str
    strategy_id: str
    user_id: str
    version_number: int
    source_text: str
    schema_json: str | None = None
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(frozen=True, slots=True)
class BacktestRecord:
    backtest_id: str
    user_id: str
    strategy_id: str
    version_id: str | None
    status: str
    result_json: str | None = None
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(frozen=True, slots=True)
class BotInstanceRecord:
    bot_instance_id: str
    user_id: str
    strategy_id: str
    version_id: str | None
    account_ref: str
    mode: str
    state: str = "STOPPED"
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(frozen=True, slots=True)
class SubscriptionRecord:
    subscription_id: str
    user_id: str
    plan: str
    status: str
    provider_ref: str | None = None
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(frozen=True, slots=True)
class ExecutionLogRecord:
    log_id: str
    user_id: str
    bot_instance_id: str
    event_type: str
    payload_json: str
    created_at: str = field(default_factory=utc_now_iso)
