from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from application.auth_service import AuthService
from backend.infrastructure.auth_store import AuthStore
from backend.infrastructure.database import Database
from backend.infrastructure.repositories import PersistenceRepository


@dataclass(frozen=True, slots=True)
class WebAuthResponse:
    status_code: int
    payload: dict[str, Any]
    session_token: str | None = None
    clear_session: bool = False


class WebAuthApplication:
    """
    HTTP-facing auth adapter for the existing Day 104 AuthService.

    Browser/API concerns live here; password hashing/session persistence remain
    inside the existing AuthService/AuthStore boundaries.
    """

    def __init__(self, *, database_path: str | Path) -> None:
        db = Database(Path(database_path))
        db.initialize()

        store = AuthStore(db)
        store.initialize()

        repository = PersistenceRepository(db)
        self.auth = AuthService(
            repository=repository,
            auth_store=store,
        )

    def register(self, body: dict[str, Any]) -> WebAuthResponse:
        email = str(body.get("email", "")).strip()
        password = str(body.get("password", ""))

        result = self.auth.register(email, password)
        if not result.success:
            return WebAuthResponse(
                status_code=self._auth_error_status(result.error),
                payload={
                    "ok": False,
                    "error": result.error or "registration_failed",
                },
            )

        return WebAuthResponse(
            status_code=201,
            payload={
                "ok": True,
                "status": result.status,
                "user_id": result.user_id,
            },
            session_token=result.token,
        )

    def login(self, body: dict[str, Any]) -> WebAuthResponse:
        email = str(body.get("email", "")).strip()
        password = str(body.get("password", ""))

        result = self.auth.login(email, password)
        if not result.success:
            return WebAuthResponse(
                status_code=401,
                payload={
                    "ok": False,
                    "error": "invalid_credentials",
                },
            )

        return WebAuthResponse(
            status_code=200,
            payload={
                "ok": True,
                "status": result.status,
                "user_id": result.user_id,
            },
            session_token=result.token,
        )

    def me(self, token: str | None) -> WebAuthResponse:
        if not token:
            return WebAuthResponse(
                status_code=401,
                payload={"ok": False, "error": "authentication_required"},
            )

        principal = self.auth.authenticate(token)
        if principal is None:
            return WebAuthResponse(
                status_code=401,
                payload={"ok": False, "error": "invalid_or_expired_session"},
                clear_session=True,
            )

        return WebAuthResponse(
            status_code=200,
            payload={
                "ok": True,
                "user_id": principal.user_id,
                "session_id": principal.session_id,
            },
        )

    def logout(self, token: str | None) -> WebAuthResponse:
        if token:
            self.auth.logout(token)

        return WebAuthResponse(
            status_code=200,
            payload={"ok": True, "status": "LOGGED_OUT"},
            clear_session=True,
        )

    @staticmethod
    def _auth_error_status(error: str | None) -> int:
        if error == "account_exists":
            return 409
        if error in {"invalid_email", "password_too_short"}:
            return 400
        return 400
