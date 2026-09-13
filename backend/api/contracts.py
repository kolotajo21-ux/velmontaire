from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class APIErrorCode(str, Enum):
    BAD_REQUEST = "BAD_REQUEST"
    NOT_FOUND = "NOT_FOUND"
    FORBIDDEN = "FORBIDDEN"
    CONFLICT = "CONFLICT"
    BOT_CORE_ERROR = "BOT_CORE_ERROR"


@dataclass(frozen=True, slots=True)
class APIRequestContext:
    user_id: str
    request_id: str

    def validate(self) -> None:
        if not str(self.user_id).strip():
            raise ValueError("user_id_required")
        if not str(self.request_id).strip():
            raise ValueError("request_id_required")


@dataclass(frozen=True, slots=True)
class APIResponse:
    success: bool
    status_code: int
    data: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None

    @classmethod
    def ok(
        cls,
        data: dict[str, Any] | None = None,
        *,
        status_code: int = 200,
    ) -> "APIResponse":
        return cls(
            success=True,
            status_code=status_code,
            data=dict(data or {}),
        )

    @classmethod
    def error(
        cls,
        *,
        status_code: int,
        error_code: APIErrorCode | str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> "APIResponse":
        code = (
            error_code.value
            if isinstance(error_code, APIErrorCode)
            else str(error_code)
        )

        return cls(
            success=False,
            status_code=int(status_code),
            data=dict(data or {}),
            error_code=code,
            error_message=str(message),
        )


@dataclass(frozen=True, slots=True)
class CreateStrategyRequest:
    name: str
    source_text: str

    def validate(self) -> None:
        if not str(self.name).strip():
            raise ValueError("strategy_name_required")
        if not str(self.source_text).strip():
            raise ValueError("strategy_source_text_required")


@dataclass(frozen=True, slots=True)
class CompileStrategyRequest:
    strategy_id: str

    def validate(self) -> None:
        if not str(self.strategy_id).strip():
            raise ValueError("strategy_id_required")


@dataclass(frozen=True, slots=True)
class RunBacktestRequest:
    strategy_id: str
    symbol: str
    timeframe: str

    def validate(self) -> None:
        if not str(self.strategy_id).strip():
            raise ValueError("strategy_id_required")
        if not str(self.symbol).strip():
            raise ValueError("symbol_required")
        if not str(self.timeframe).strip():
            raise ValueError("timeframe_required")


@dataclass(frozen=True, slots=True)
class CreateBotInstanceRequest:
    strategy_id: str
    account_ref: str
    mode: str = "PAPER"

    def validate(self) -> None:
        if not str(self.strategy_id).strip():
            raise ValueError("strategy_id_required")
        if not str(self.account_ref).strip():
            raise ValueError("account_ref_required")

        mode = str(self.mode).strip().upper()
        if mode not in {"PAPER", "LIVE"}:
            raise ValueError("bot_mode_invalid")


@dataclass(frozen=True, slots=True)
class BotActionRequest:
    bot_instance_id: str

    def validate(self) -> None:
        if not str(self.bot_instance_id).strip():
            raise ValueError("bot_instance_id_required")
