from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from backend.application.strategy_management_service import StrategyManagementService
from backend.domain.persistence_models import BacktestRecord
from backend.infrastructure.repositories import PersistenceRepository


@dataclass(frozen=True, slots=True)
class BacktestJob:
    backtest_id: str
    user_id: str
    strategy_id: str
    version_id: str
    status: str
    result: Any = None


class BacktestJobService:
    TERMINAL = {"COMPLETED", "FAILED"}

    def __init__(self, *, repository: PersistenceRepository, strategies: StrategyManagementService, bot_core: Any) -> None:
        self.repo = repository
        self.strategies = strategies
        self.bot_core = bot_core

    def create(
        self, *, user_id: str, strategy_id: str, symbol: str, timeframe: str,
        date_from: str, date_to: str, starting_balance: float = 5000,
        spread_pips: float = 0, commission_per_lot: float = 0, slippage_pips: float = 0,
    ) -> BacktestJob:
        version = self.strategies.active_version(user_id=user_id, strategy_id=strategy_id)
        if not version.schema_json:
            raise RuntimeError("active_strategy_schema_missing")

        payload = {
            "symbol": symbol.strip().upper(),
            "timeframe": timeframe.strip().upper(),
            "date_from": date_from,
            "date_to": date_to,
            "starting_balance": float(starting_balance),
            "spread_pips": float(spread_pips),
            "commission_per_lot": float(commission_per_lot),
            "slippage_pips": float(slippage_pips),
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        backtest_id = f"backtest_{uuid.uuid4().hex[:24]}"

        self.repo.create_backtest(BacktestRecord(
            backtest_id, user_id, strategy_id, version.version_id,
            "QUEUED", json.dumps(payload, sort_keys=True),
        ))
        return self.get(user_id=user_id, backtest_id=backtest_id)

    def run(self, *, user_id: str, backtest_id: str) -> BacktestJob:
        record = self._owned(user_id, backtest_id)
        if record.status != "QUEUED":
            raise RuntimeError("backtest_not_queued")

        self._update(record, status="RUNNING", result_json=record.result_json)
        try:
            result = self.bot_core.run_backtest({
                "user_id": user_id,
                "backtest_id": backtest_id,
                "strategy_id": record.strategy_id,
                "version_id": record.version_id,
            })
        except Exception as exc:
            self._update(record, status="FAILED", result_json=json.dumps({
                "error": type(exc).__name__, "message": str(exc)
            }, sort_keys=True))
            return self.get(user_id=user_id, backtest_id=backtest_id)

        success = bool(result.get("success", False) if isinstance(result, dict) else getattr(result, "success", False))
        payload = result if isinstance(result, dict) else getattr(result, "data", {"repr": str(result)})
        self._update(
            record,
            status="COMPLETED" if success else "FAILED",
            result_json=json.dumps(payload, sort_keys=True, default=str),
        )
        return self.get(user_id=user_id, backtest_id=backtest_id)

    def get(self, *, user_id: str, backtest_id: str) -> BacktestJob:
        record = self._owned(user_id, backtest_id)
        parsed = json.loads(record.result_json) if record.result_json else None
        return BacktestJob(
            record.backtest_id, record.user_id, record.strategy_id,
            record.version_id or "", record.status, parsed,
        )

    def _owned(self, user_id: str, backtest_id: str):
        record = self.repo.get_backtest(user_id, backtest_id)
        if record is None:
            raise PermissionError("backtest_not_owned")
        return record

    def _update(self, record, *, status: str, result_json: str | None) -> None:
        with self.repo.db.connect() as conn:
            conn.execute(
                "UPDATE backtests SET status=?, result_json=? WHERE backtest_id=? AND user_id=?",
                (status, result_json, record.backtest_id, record.user_id),
            )

    @staticmethod
    def _id(*parts: str) -> str:
        return "backtest_" + hashlib.sha256("|".join(map(str, parts)).encode("utf-8")).hexdigest()[:24]
