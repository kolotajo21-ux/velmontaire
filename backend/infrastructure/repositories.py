from __future__ import annotations

from dataclasses import asdict
from typing import Any

from backend.domain.persistence_models import (
    BacktestRecord,
    BotInstanceRecord,
    ExecutionLogRecord,
    StrategyRecord,
    StrategyVersionRecord,
    SubscriptionRecord,
    UserRecord,
)
from backend.infrastructure.database import Database


class PersistenceRepository:
    """
    Every user-owned lookup requires user_id.

    Foreign resources deliberately return None/empty instead of revealing
    whether another user's resource exists.
    """

    def __init__(self, database: Database) -> None:
        self.db = database

    def create_user(self, record: UserRecord) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO users(user_id,email,created_at) VALUES(?,?,?)",
                (record.user_id, record.email, record.created_at),
            )

    def get_user(self, user_id: str) -> UserRecord | None:
        row = self._one(
            "SELECT * FROM users WHERE user_id=?",
            (user_id,),
        )
        return UserRecord(**dict(row)) if row else None

    def create_strategy(self, record: StrategyRecord) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """INSERT INTO strategies
                (strategy_id,user_id,name,active_version_id,created_at)
                VALUES(?,?,?,?,?)""",
                (
                    record.strategy_id, record.user_id, record.name,
                    record.active_version_id, record.created_at,
                ),
            )

    def get_strategy(
        self,
        user_id: str,
        strategy_id: str,
    ) -> StrategyRecord | None:
        row = self._one(
            "SELECT * FROM strategies WHERE strategy_id=? AND user_id=?",
            (strategy_id, user_id),
        )
        return StrategyRecord(**dict(row)) if row else None

    def list_strategies(self, user_id: str) -> list[StrategyRecord]:
        rows = self._all(
            "SELECT * FROM strategies WHERE user_id=? ORDER BY created_at",
            (user_id,),
        )
        return [StrategyRecord(**dict(row)) for row in rows]

    def create_strategy_version(
        self,
        record: StrategyVersionRecord,
    ) -> None:
        # Ownership is checked before insert; user_id cannot attach a version
        # to somebody else's strategy.
        if self.get_strategy(record.user_id, record.strategy_id) is None:
            raise PermissionError("strategy_not_owned")

        with self.db.connect() as conn:
            conn.execute(
                """INSERT INTO strategy_versions
                (version_id,strategy_id,user_id,version_number,source_text,
                 schema_json,created_at)
                VALUES(?,?,?,?,?,?,?)""",
                (
                    record.version_id, record.strategy_id, record.user_id,
                    record.version_number, record.source_text,
                    record.schema_json, record.created_at,
                ),
            )

    def get_strategy_version(
        self,
        user_id: str,
        version_id: str,
    ) -> StrategyVersionRecord | None:
        row = self._one(
            "SELECT * FROM strategy_versions WHERE version_id=? AND user_id=?",
            (version_id, user_id),
        )
        return StrategyVersionRecord(**dict(row)) if row else None

    def set_active_version(
        self,
        user_id: str,
        strategy_id: str,
        version_id: str,
    ) -> None:
        version = self.get_strategy_version(user_id, version_id)
        if version is None or version.strategy_id != strategy_id:
            raise PermissionError("strategy_version_not_owned")

        with self.db.connect() as conn:
            cur = conn.execute(
                """UPDATE strategies SET active_version_id=?
                WHERE strategy_id=? AND user_id=?""",
                (version_id, strategy_id, user_id),
            )
            if cur.rowcount != 1:
                raise PermissionError("strategy_not_owned")

    def create_backtest(self, record: BacktestRecord) -> None:
        if self.get_strategy(record.user_id, record.strategy_id) is None:
            raise PermissionError("strategy_not_owned")
        with self.db.connect() as conn:
            conn.execute(
                """INSERT INTO backtests
                (backtest_id,user_id,strategy_id,version_id,status,result_json,created_at)
                VALUES(?,?,?,?,?,?,?)""",
                (
                    record.backtest_id, record.user_id, record.strategy_id,
                    record.version_id, record.status, record.result_json,
                    record.created_at,
                ),
            )

    def get_backtest(
        self,
        user_id: str,
        backtest_id: str,
    ) -> BacktestRecord | None:
        row = self._one(
            "SELECT * FROM backtests WHERE backtest_id=? AND user_id=?",
            (backtest_id, user_id),
        )
        return BacktestRecord(**dict(row)) if row else None

    def create_bot_instance(self, record: BotInstanceRecord) -> None:
        if self.get_strategy(record.user_id, record.strategy_id) is None:
            raise PermissionError("strategy_not_owned")
        with self.db.connect() as conn:
            conn.execute(
                """INSERT INTO bot_instances
                (bot_instance_id,user_id,strategy_id,version_id,account_ref,
                 mode,state,created_at)
                VALUES(?,?,?,?,?,?,?,?)""",
                (
                    record.bot_instance_id, record.user_id, record.strategy_id,
                    record.version_id, record.account_ref, record.mode,
                    record.state, record.created_at,
                ),
            )

    def get_bot_instance(
        self,
        user_id: str,
        bot_instance_id: str,
    ) -> BotInstanceRecord | None:
        row = self._one(
            "SELECT * FROM bot_instances WHERE bot_instance_id=? AND user_id=?",
            (bot_instance_id, user_id),
        )
        return BotInstanceRecord(**dict(row)) if row else None

    def create_subscription(self, record: SubscriptionRecord) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """INSERT INTO subscriptions
                (subscription_id,user_id,plan,status,provider_ref,created_at)
                VALUES(?,?,?,?,?,?)""",
                (
                    record.subscription_id, record.user_id, record.plan,
                    record.status, record.provider_ref, record.created_at,
                ),
            )

    def get_subscription(
        self,
        user_id: str,
        subscription_id: str,
    ) -> SubscriptionRecord | None:
        row = self._one(
            "SELECT * FROM subscriptions WHERE subscription_id=? AND user_id=?",
            (subscription_id, user_id),
        )
        return SubscriptionRecord(**dict(row)) if row else None

    def create_execution_log(self, record: ExecutionLogRecord) -> None:
        bot = self.get_bot_instance(record.user_id, record.bot_instance_id)
        if bot is None:
            raise PermissionError("bot_instance_not_owned")
        with self.db.connect() as conn:
            conn.execute(
                """INSERT INTO execution_logs
                (log_id,user_id,bot_instance_id,event_type,payload_json,created_at)
                VALUES(?,?,?,?,?,?)""",
                (
                    record.log_id, record.user_id, record.bot_instance_id,
                    record.event_type, record.payload_json, record.created_at,
                ),
            )

    def list_execution_logs(
        self,
        user_id: str,
        bot_instance_id: str,
    ) -> list[ExecutionLogRecord]:
        if self.get_bot_instance(user_id, bot_instance_id) is None:
            return []
        rows = self._all(
            """SELECT * FROM execution_logs
            WHERE user_id=? AND bot_instance_id=?
            ORDER BY created_at""",
            (user_id, bot_instance_id),
        )
        return [ExecutionLogRecord(**dict(row)) for row in rows]

    def _one(self, sql: str, params: tuple[Any, ...]):
        with self.db.connect() as conn:
            return conn.execute(sql, params).fetchone()

    def _all(self, sql: str, params: tuple[Any, ...]):
        with self.db.connect() as conn:
            return conn.execute(sql, params).fetchall()
