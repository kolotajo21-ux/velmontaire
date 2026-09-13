from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Any

from backend.application.backtest_job_service import BacktestJobService


class BacktestAPI:
    def __init__(self, *, jobs: BacktestJobService) -> None:
        self.jobs = jobs

    def create(self, *, principal: Any, body: dict[str, Any]) -> dict[str, Any]:
        user_id = self._user_id(principal)
        if not isinstance(body, dict):
            return self._error(400, "invalid_request")

        strategy_id = str(body.get("strategy_id", "")).strip()
        symbol = str(body.get("symbol", "")).strip().upper()
        timeframe = str(body.get("timeframe", "")).strip().upper()
        date_from = str(body.get("date_from", "")).strip()
        date_to = str(body.get("date_to", "")).strip()

        if not all((strategy_id, symbol, timeframe, date_from, date_to)):
            return self._error(400, "strategy_symbol_timeframe_dates_required")

        try:
            if date.fromisoformat(date_from) > date.fromisoformat(date_to):
                return self._error(400, "invalid_date_range")

            starting_balance = float(body.get("starting_balance", 5000))
            spread_pips = float(body.get("spread_pips", 0))
            commission_per_lot = float(body.get("commission_per_lot", 0))
            slippage_pips = float(body.get("slippage_pips", 0))

            if starting_balance <= 0:
                return self._error(400, "invalid_starting_balance")
            if min(spread_pips, commission_per_lot, slippage_pips) < 0:
                return self._error(400, "invalid_backtest_costs")

            job = self.jobs.create(
                user_id=user_id,
                strategy_id=strategy_id,
                symbol=symbol,
                timeframe=timeframe,
                date_from=date_from,
                date_to=date_to,
                starting_balance=starting_balance,
                spread_pips=spread_pips,
                commission_per_lot=commission_per_lot,
                slippage_pips=slippage_pips,
            )
        except PermissionError:
            return self._error(404, "backtest_resource_not_found")
        except (ValueError, RuntimeError) as exc:
            return self._error(400, str(exc))

        return {"status_code": 202, "data": self._job(job)}

    def run(self, *, principal: Any, backtest_id: str) -> dict[str, Any]:
        user_id = self._user_id(principal)
        try:
            job = self.jobs.run(user_id=user_id, backtest_id=backtest_id)
        except PermissionError:
            return self._error(404, "backtest_resource_not_found")
        except RuntimeError as exc:
            return self._error(409, str(exc))
        return {"status_code": 200, "data": self._job(job)}

    def status(self, *, principal: Any, backtest_id: str) -> dict[str, Any]:
        user_id = self._user_id(principal)
        try:
            job = self.jobs.get(user_id=user_id, backtest_id=backtest_id)
        except PermissionError:
            return self._error(404, "backtest_resource_not_found")
        return {"status_code": 200, "data": self._job(job)}

    @staticmethod
    def _user_id(principal: Any) -> str:
        user_id = principal.get("user_id") if isinstance(principal, dict) else getattr(principal, "user_id", None)
        if not user_id:
            raise PermissionError("authentication_required")
        return str(user_id)

    @staticmethod
    def _job(job: Any) -> dict[str, Any]:
        return asdict(job) if hasattr(job, "__dataclass_fields__") else dict(job)

    @staticmethod
    def _error(status_code: int, code: str) -> dict[str, Any]:
        return {"status_code": status_code, "error": code}
