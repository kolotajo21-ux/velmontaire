from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class APIRoute:
    method: str
    path: str
    operation_id: str


ROUTES: tuple[APIRoute, ...] = (
    APIRoute("POST", "/api/v1/strategies", "create_strategy"),
    APIRoute("GET", "/api/v1/strategies/{strategy_id}", "get_strategy"),
    APIRoute("POST", "/api/v1/strategies/{strategy_id}/compile", "compile_strategy"),
    APIRoute("POST", "/api/v1/backtests", "run_backtest"),
    APIRoute("GET", "/api/v1/backtests/{backtest_id}", "get_backtest"),
    APIRoute("POST", "/api/v1/bots", "create_bot_instance"),
    APIRoute("GET", "/api/v1/bots/{bot_instance_id}", "get_bot_instance"),
    APIRoute("POST", "/api/v1/bots/{bot_instance_id}/start", "start_bot"),
    APIRoute("POST", "/api/v1/bots/{bot_instance_id}/pause", "pause_bot"),
    APIRoute("POST", "/api/v1/bots/{bot_instance_id}/stop", "stop_bot"),
    APIRoute("GET", "/api/v1/bots/{bot_instance_id}/runtime", "runtime_status"),
)


def route_by_operation(operation_id: str) -> APIRoute:
    for route in ROUTES:
        if route.operation_id == operation_id:
            return route

    raise KeyError(f"unknown_api_operation:{operation_id}")
