from __future__ import annotations

import sqlite3
from backend.infrastructure.database import Database


class AuthStore:
    def __init__(self, database: Database) -> None:
        self.db = database

    def initialize(self) -> None:
        with self.db.connect() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS auth_credentials (
                user_id TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                iterations INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            );

            CREATE TABLE IF NOT EXISTS auth_sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                revoked_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            );

            CREATE INDEX IF NOT EXISTS idx_auth_sessions_user
                ON auth_sessions(user_id);
            """)

    def create_credential(
        self, user_id: str, password_hash: str, salt: str, iterations: int
    ) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """INSERT INTO auth_credentials
                (user_id,password_hash,password_salt,iterations)
                VALUES(?,?,?,?)""",
                (user_id, password_hash, salt, iterations),
            )

    def credential(self, user_id: str):
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM auth_credentials WHERE user_id=?",
                (user_id,),
            ).fetchone()
            return dict(row) if row else None

    def user_by_email(self, email: str):
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE lower(email)=lower(?)",
                (email.strip(),),
            ).fetchone()
            return dict(row) if row else None

    def create_session(
        self, session_id: str, user_id: str, token_hash: str,
        created_at: str, expires_at: str
    ) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """INSERT INTO auth_sessions
                (session_id,user_id,token_hash,created_at,expires_at,revoked_at)
                VALUES(?,?,?,?,?,NULL)""",
                (session_id, user_id, token_hash, created_at, expires_at),
            )

    def session_by_token_hash(self, token_hash: str):
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM auth_sessions WHERE token_hash=?",
                (token_hash,),
            ).fetchone()
            return dict(row) if row else None

    def revoke_session(self, session_id: str, revoked_at: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """UPDATE auth_sessions SET revoked_at=?
                WHERE session_id=? AND revoked_at IS NULL""",
                (revoked_at, session_id),
            )

    def revoke_all_for_user(self, user_id: str, revoked_at: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """UPDATE auth_sessions SET revoked_at=?
                WHERE user_id=? AND revoked_at IS NULL""",
                (revoked_at, user_id),
            )
