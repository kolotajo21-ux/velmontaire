from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1


class ClosingSQLiteConnection(sqlite3.Connection):
    """
    sqlite3.Connection commits/rolls back in __exit__ but does NOT close
    the underlying file handle. On Windows that can keep a temporary .sqlite3
    file locked and make TemporaryDirectory cleanup fail with WinError 32.

    This subclass preserves normal sqlite transaction semantics and then
    explicitly closes the connection on context-manager exit.
    """

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: Any,
    ) -> bool:
        try:
            result = super().__exit__(
                exc_type,
                exc_value,
                traceback,
            )
        finally:
            self.close()

        return bool(result)


class Database:
    """
    Day 103 persistence foundation.

    SQLite is used for local development/test persistence.

    Important Windows safety:
    every connection returned by connect() closes automatically when used as:

        with db.connect() as conn:
            ...

    This prevents leaked SQLite file handles and WinError 32 during cleanup.
    """

    def __init__(
        self,
        path: str | Path,
    ) -> None:
        self.path = str(path)

    def connect(
        self,
    ) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.path,
            factory=ClosingSQLiteConnection,
        )

        conn.row_factory = sqlite3.Row

        conn.execute(
            "PRAGMA foreign_keys = ON"
        )

        return conn

    def initialize(
        self,
    ) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS strategies (
                    strategy_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    active_version_id TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                );

                CREATE INDEX IF NOT EXISTS idx_strategies_user
                    ON strategies(user_id);

                CREATE TABLE IF NOT EXISTS strategy_versions (
                    version_id TEXT PRIMARY KEY,
                    strategy_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    version_number INTEGER NOT NULL,
                    source_text TEXT NOT NULL,
                    schema_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(strategy_id) REFERENCES strategies(strategy_id),
                    FOREIGN KEY(user_id) REFERENCES users(user_id),
                    UNIQUE(strategy_id, version_number)
                );

                CREATE INDEX IF NOT EXISTS idx_versions_owner
                    ON strategy_versions(user_id, strategy_id);

                CREATE TABLE IF NOT EXISTS backtests (
                    backtest_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    strategy_id TEXT NOT NULL,
                    version_id TEXT,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(user_id),
                    FOREIGN KEY(strategy_id) REFERENCES strategies(strategy_id)
                );

                CREATE INDEX IF NOT EXISTS idx_backtests_owner
                    ON backtests(user_id, strategy_id);

                CREATE TABLE IF NOT EXISTS bot_instances (
                    bot_instance_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    strategy_id TEXT NOT NULL,
                    version_id TEXT,
                    account_ref TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(user_id),
                    FOREIGN KEY(strategy_id) REFERENCES strategies(strategy_id)
                );

                CREATE INDEX IF NOT EXISTS idx_bots_owner
                    ON bot_instances(user_id, strategy_id);

                CREATE TABLE IF NOT EXISTS subscriptions (
                    subscription_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    plan TEXT NOT NULL,
                    status TEXT NOT NULL,
                    provider_ref TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                );

                CREATE INDEX IF NOT EXISTS idx_subscriptions_user
                    ON subscriptions(user_id);

                CREATE TABLE IF NOT EXISTS execution_logs (
                    log_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    bot_instance_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(user_id),
                    FOREIGN KEY(bot_instance_id) REFERENCES bot_instances(bot_instance_id)
                );

                CREATE INDEX IF NOT EXISTS idx_execution_logs_owner
                    ON execution_logs(user_id, bot_instance_id);
                """
            )

            conn.execute(
                """
                INSERT INTO schema_meta(key, value)
                VALUES('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (
                    str(SCHEMA_VERSION),
                ),
            )