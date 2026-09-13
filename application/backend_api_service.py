from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from backend.api.contracts import (
    APIErrorCode,
    APIRequestContext,
    APIResponse,
    BotActionRequest,
    CompileStrategyRequest,
    CreateBotInstanceRequest,
    CreateStrategyRequest,
    RunBacktestRequest,
)
from backend.application.bot_core_gateway import (
    BotCoreCommand,
    BotCoreGateway,
)


@dataclass(slots=True)
class StrategyRecord:
    strategy_id: str
    user_id: str
    name: str
    source_text: str


@dataclass(slots=True)
class BotInstanceRecord:
    bot_instance_id: str
    user_id: str
    strategy_id: str
    account_ref: str
    mode: str
    state: str = "STOPPED"


class BackendAPIService:
    """
    Day 102 application-facing API service.

    Temporary in-memory records exist only to prove API contracts.
    Day 103 replaces storage with the database layer.

    Security invariant:
    user_id from APIRequestContext scopes every resource.
    """

    def __init__(
        self,
        *,
        bot_core: BotCoreGateway,
    ) -> None:
        self.bot_core = bot_core
        self._strategies: dict[str, StrategyRecord] = {}
        self._bots: dict[str, BotInstanceRecord] = {}
        self._backtests: dict[str, dict[str, Any]] = {}

    def create_strategy(
        self,
        context: APIRequestContext,
        request: CreateStrategyRequest,
    ) -> APIResponse:
        try:
            context.validate()
            request.validate()
        except ValueError as exc:
            return self._bad_request(str(exc))

        strategy_id = self._stable_id(
            "strategy",
            context.user_id,
            context.request_id,
            request.name,
        )

        if strategy_id in self._strategies:
            return APIResponse.error(
                status_code=409,
                error_code=APIErrorCode.CONFLICT,
                message="strategy_already_exists",
            )

        record = StrategyRecord(
            strategy_id=strategy_id,
            user_id=context.user_id,
            name=request.name.strip(),
            source_text=request.source_text.strip(),
        )

        self._strategies[strategy_id] = record

        return APIResponse.ok(
            {
                "strategy_id": strategy_id,
                "name": record.name,
                "status": "DRAFT",
            },
            status_code=201,
        )

    def get_strategy(
        self,
        context: APIRequestContext,
        strategy_id: str,
    ) -> APIResponse:
        try:
            context.validate()
        except ValueError as exc:
            return self._bad_request(str(exc))

        record = self._strategies.get(str(strategy_id))

        if record is None:
            return self._not_found("strategy_not_found")

        if record.user_id != context.user_id:
            return self._not_found("strategy_not_found")

        return APIResponse.ok(
            {
                "strategy_id": record.strategy_id,
                "name": record.name,
                "source_text": record.source_text,
                "status": "DRAFT",
            }
        )

    def compile_strategy(
        self,
        context: APIRequestContext,
        request: CompileStrategyRequest,
    ) -> APIResponse:
        try:
            context.validate()
            request.validate()
        except ValueError as exc:
            return self._bad_request(str(exc))

        record = self._strategies.get(request.strategy_id)

        if record is None or record.user_id != context.user_id:
            return self._not_found("strategy_not_found")

        result = self.bot_core.compile_strategy(
            BotCoreCommand(
                command_type="COMPILE_STRATEGY",
                user_id=context.user_id,
                strategy_id=record.strategy_id,
                payload={
                    "source_text": record.source_text,
                },
            )
        )

        return self._from_core(result)

    def run_backtest(
        self,
        context: APIRequestContext,
        request: RunBacktestRequest,
    ) -> APIResponse:
        try:
            context.validate()
            request.validate()
        except ValueError as exc:
            return self._bad_request(str(exc))

        strategy = self._strategies.get(request.strategy_id)

        if strategy is None or strategy.user_id != context.user_id:
            return self._not_found("strategy_not_found")

        backtest_id = self._stable_id(
            "backtest",
            context.user_id,
            context.request_id,
            request.strategy_id,
        )

        result = self.bot_core.run_backtest(
            BotCoreCommand(
                command_type="RUN_BACKTEST",
                user_id=context.user_id,
                strategy_id=request.strategy_id,
                payload={
                    "symbol": request.symbol.strip().upper(),
                    "timeframe": request.timeframe.strip().upper(),
                    "backtest_id": backtest_id,
                },
            )
        )

        if result.success:
            self._backtests[backtest_id] = {
                "backtest_id": backtest_id,
                "user_id": context.user_id,
                "strategy_id": request.strategy_id,
                "status": result.status,
                "data": dict(result.data),
            }

        response = self._from_core(result)

        if response.success:
            data = dict(response.data)
            data["backtest_id"] = backtest_id
            return APIResponse.ok(
                data,
                status_code=202,
            )

        return response

    def get_backtest(
        self,
        context: APIRequestContext,
        backtest_id: str,
    ) -> APIResponse:
        try:
            context.validate()
        except ValueError as exc:
            return self._bad_request(str(exc))

        record = self._backtests.get(str(backtest_id))

        if record is None or record["user_id"] != context.user_id:
            return self._not_found("backtest_not_found")

        safe = {
            key: value
            for key, value in record.items()
            if key != "user_id"
        }

        return APIResponse.ok(safe)

    def create_bot_instance(
        self,
        context: APIRequestContext,
        request: CreateBotInstanceRequest,
    ) -> APIResponse:
        try:
            context.validate()
            request.validate()
        except ValueError as exc:
            return self._bad_request(str(exc))

        strategy = self._strategies.get(request.strategy_id)

        if strategy is None or strategy.user_id != context.user_id:
            return self._not_found("strategy_not_found")

        bot_id = self._stable_id(
            "bot",
            context.user_id,
            context.request_id,
            request.strategy_id,
            request.account_ref,
        )

        record = BotInstanceRecord(
            bot_instance_id=bot_id,
            user_id=context.user_id,
            strategy_id=request.strategy_id,
            account_ref=request.account_ref.strip(),
            mode=request.mode.strip().upper(),
        )

        self._bots[bot_id] = record

        return APIResponse.ok(
            {
                "bot_instance_id": bot_id,
                "strategy_id": record.strategy_id,
                "mode": record.mode,
                "state": record.state,
            },
            status_code=201,
        )

    def get_bot_instance(
        self,
        context: APIRequestContext,
        bot_instance_id: str,
    ) -> APIResponse:
        record = self._owned_bot(
            context,
            bot_instance_id,
        )

        if isinstance(record, APIResponse):
            return record

        return APIResponse.ok(
            {
                "bot_instance_id": record.bot_instance_id,
                "strategy_id": record.strategy_id,
                "mode": record.mode,
                "state": record.state,
            }
        )

    def runtime_status(
        self,
        context: APIRequestContext,
        request: BotActionRequest,
    ) -> APIResponse:
        try:
            context.validate()
            request.validate()
        except ValueError as exc:
            return self._bad_request(str(exc))

        record = self._bots.get(request.bot_instance_id)

        if record is None or record.user_id != context.user_id:
            return self._not_found("bot_instance_not_found")

        result = self.bot_core.runtime_status(
            BotCoreCommand(
                command_type="RUNTIME_STATUS",
                user_id=context.user_id,
                strategy_id=record.strategy_id,
                bot_instance_id=record.bot_instance_id,
                payload={
                    "mode": record.mode,
                },
            )
        )

        return self._from_core(result)

    def start_bot(
        self,
        context: APIRequestContext,
        request: BotActionRequest,
    ) -> APIResponse:
        return self._bot_action(
            context,
            request,
            "START_BOT",
            self.bot_core.start_bot,
            new_state="RUNNING",
        )

    def pause_bot(
        self,
        context: APIRequestContext,
        request: BotActionRequest,
    ) -> APIResponse:
        return self._bot_action(
            context,
            request,
            "PAUSE_BOT",
            self.bot_core.pause_bot,
            new_state="PAUSED",
        )

    def stop_bot(
        self,
        context: APIRequestContext,
        request: BotActionRequest,
    ) -> APIResponse:
        return self._bot_action(
            context,
            request,
            "STOP_BOT",
            self.bot_core.stop_bot,
            new_state="STOPPED",
        )

    def _bot_action(
        self,
        context: APIRequestContext,
        request: BotActionRequest,
        command_type: str,
        handler: Any,
        *,
        new_state: str,
    ) -> APIResponse:
        try:
            context.validate()
            request.validate()
        except ValueError as exc:
            return self._bad_request(str(exc))

        record = self._bots.get(request.bot_instance_id)

        if record is None or record.user_id != context.user_id:
            return self._not_found("bot_instance_not_found")

        result = handler(
            BotCoreCommand(
                command_type=command_type,
                user_id=context.user_id,
                strategy_id=record.strategy_id,
                bot_instance_id=record.bot_instance_id,
                payload={
                    "mode": record.mode,
                    "account_ref": record.account_ref,
                },
            )
        )

        if result.success:
            record.state = new_state

        return self._from_core(result)

    def _owned_bot(
        self,
        context: APIRequestContext,
        bot_instance_id: str,
    ) -> BotInstanceRecord | APIResponse:
        try:
            context.validate()
        except ValueError as exc:
            return self._bad_request(str(exc))

        record = self._bots.get(str(bot_instance_id))

        if record is None or record.user_id != context.user_id:
            return self._not_found("bot_instance_not_found")

        return record

    @staticmethod
    def _from_core(result: Any) -> APIResponse:
        if bool(getattr(result, "success", False)):
            return APIResponse.ok(
                {
                    "status": str(getattr(result, "status", "OK")),
                    **dict(getattr(result, "data", {}) or {}),
                }
            )

        errors = tuple(
            getattr(result, "errors", ())
            or ()
        )

        return APIResponse.error(
            status_code=502,
            error_code=APIErrorCode.BOT_CORE_ERROR,
            message=(
                errors[0]
                if errors
                else str(getattr(result, "status", "bot_core_error"))
            ),
            data={
                "status": str(getattr(result, "status", "ERROR")),
            },
        )

    @staticmethod
    def _bad_request(message: str) -> APIResponse:
        return APIResponse.error(
            status_code=400,
            error_code=APIErrorCode.BAD_REQUEST,
            message=message,
        )

    @staticmethod
    def _not_found(message: str) -> APIResponse:
        # Deliberately use 404 for foreign resources too so resource
        # existence is not leaked across users.
        return APIResponse.error(
            status_code=404,
            error_code=APIErrorCode.NOT_FOUND,
            message=message,
        )

    @staticmethod
    def _stable_id(
        prefix: str,
        *parts: str,
    ) -> str:
        payload = "|".join(
            str(part)
            for part in parts
        )

        digest = hashlib.sha256(
            payload.encode("utf-8")
        ).hexdigest()[:20]

        return f"{prefix}_{digest}"
