from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

@dataclass(frozen=True, slots=True)
class BotCoreCommand:
    command_type: str
    user_id: str
    strategy_id: str | None = None
    bot_instance_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True, slots=True)
class BotCoreResult:
    success: bool
    status: str
    data: dict[str, Any] = field(default_factory=dict)
    errors: tuple[str, ...] = ()

@runtime_checkable
class BotCoreGateway(Protocol):
    def compile_strategy(self, command: BotCoreCommand) -> BotCoreResult: ...
    def run_backtest(self, command: BotCoreCommand) -> BotCoreResult: ...
    def runtime_status(self, command: BotCoreCommand) -> BotCoreResult: ...
    def start_bot(self, command: BotCoreCommand) -> BotCoreResult: ...
    def pause_bot(self, command: BotCoreCommand) -> BotCoreResult: ...
    def stop_bot(self, command: BotCoreCommand) -> BotCoreResult: ...
