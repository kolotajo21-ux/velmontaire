from __future__ import annotations

import json
from typing import Any

from generic_backtest.runner import ProductionGenericHistoricalRunner


class ProductionGenericBacktestGateway:
    def __init__(self, *, repository: Any, history_source: Any, starting_balance: float = 5000) -> None:
        self.repo = repository
        self.runner = ProductionGenericHistoricalRunner(history_source, starting_balance=starting_balance)

    def run_backtest(self, command: dict[str, Any]) -> dict[str, Any]:
        user_id = self._required(command, "user_id")
        backtest_id = self._required(command, "backtest_id")
        strategy_id = self._required(command, "strategy_id")
        version_id = self._required(command, "version_id")

        bt = self.repo.get_backtest(user_id, backtest_id)
        if bt is None:
            raise PermissionError("backtest_not_owned")
        if bt.strategy_id != strategy_id or bt.version_id != version_id:
            raise RuntimeError("backtest_pinned_version_mismatch")

        version = self.repo.get_strategy_version(user_id, version_id)
        if version is None or version.strategy_id != strategy_id:
            raise RuntimeError("pinned_strategy_version_missing")
        if not version.schema_json:
            raise RuntimeError("pinned_strategy_schema_missing")

        request = json.loads(bt.result_json or "{}")
        result = self.runner.run(
            schema_payload=json.loads(version.schema_json),
            symbol=str(request.get("symbol", "")),
            timeframe=str(request.get("timeframe", "")),
            date_from=request.get("date_from"),
            date_to=request.get("date_to"),
            starting_balance=request.get("starting_balance", 5000),
            spread_pips=request.get("spread_pips", 0),
            commission_per_lot=request.get("commission_per_lot", 0),
            slippage_pips=request.get("slippage_pips", 0),
        )
        result["diagnostics"]["backtest_id"] = backtest_id
        result["diagnostics"]["pinned_version_id"] = version_id
        return result

    @staticmethod
    def _required(command: dict[str, Any], key: str) -> str:
        value = str(command.get(key, "")).strip()
        if not value:
            raise ValueError(f"{key}_required")
        return value
