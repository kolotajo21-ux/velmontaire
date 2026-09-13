from __future__ import annotations

from infrastructure.execution_lock import ExecutionLock


class StrategyExecutionLock(ExecutionLock):
    """Strategy-scoped execution lock."""

    def __init__(self, directory, *, strategy_id: str) -> None:
        super().__init__(directory)
        self.strategy_id = self._normalize_strategy_id(strategy_id)

    def _key(self, execution_id: str) -> str:
        value = str(execution_id).strip()
        if not value:
            raise ValueError("execution_id is required")
        return f"{self.strategy_id}::{value}"

    def acquire(self, execution_id):
        return super().acquire(self._key(execution_id))

    def is_locked(self, execution_id):
        return super().is_locked(self._key(execution_id))

    @staticmethod
    def _normalize_strategy_id(strategy_id: str) -> str:
        value = str(strategy_id).strip()
        if not value:
            raise ValueError("strategy_id is required")
        return value