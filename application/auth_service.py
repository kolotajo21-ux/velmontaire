from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from backend.domain.auth_models import AuthenticatedPrincipal, AuthResult
from backend.domain.persistence_models import UserRecord
from backend.infrastructure.auth_store import AuthStore
from backend.infrastructure.repositories import PersistenceRepository


class AuthService:
    PBKDF2_ITERATIONS = 310_000
    SESSION_HOURS = 24

    def __init__(
        self,
        *,
        repository: PersistenceRepository,
        auth_store: AuthStore,
    ) -> None:
        self.repository = repository
        self.auth_store = auth_store

    def register(self, email: str, password: str) -> AuthResult:
        email = str(email).strip().lower()
        password = str(password)

        if "@" not in email or len(email) > 254:
            return AuthResult(False, "REJECTED", error="invalid_email")
        if len(password) < 10:
            return AuthResult(False, "REJECTED", error="password_too_short")
        if self.auth_store.user_by_email(email) is not None:
            return AuthResult(False, "REJECTED", error="account_exists")

        user_id = f"user_{uuid.uuid4().hex}"
        salt = secrets.token_bytes(32)
        digest = self._derive(password, salt, self.PBKDF2_ITERATIONS)

        self.repository.create_user(UserRecord(user_id, email))
        self.auth_store.create_credential(
            user_id,
            base64.b64encode(digest).decode("ascii"),
            base64.b64encode(salt).decode("ascii"),
            self.PBKDF2_ITERATIONS,
        )
        return self._issue_session(user_id)

    def login(self, email: str, password: str) -> AuthResult:
        user = self.auth_store.user_by_email(str(email).strip().lower())
        # Same public error for unknown account and wrong password.
        if user is None:
            self._derive(str(password), b"\x00" * 32, self.PBKDF2_ITERATIONS)
            return AuthResult(False, "REJECTED", error="invalid_credentials")

        cred = self.auth_store.credential(user["user_id"])
        if cred is None:
            return AuthResult(False, "REJECTED", error="invalid_credentials")

        salt = base64.b64decode(cred["password_salt"])
        expected = base64.b64decode(cred["password_hash"])
        actual = self._derive(str(password), salt, int(cred["iterations"]))

        if not hmac.compare_digest(actual, expected):
            return AuthResult(False, "REJECTED", error="invalid_credentials")

        return self._issue_session(user["user_id"])

    def authenticate(self, token: str) -> AuthenticatedPrincipal | None:
        token = str(token).strip()
        if not token:
            return None

        row = self.auth_store.session_by_token_hash(self._token_hash(token))
        if row is None or row["revoked_at"] is not None:
            return None

        expires_at = datetime.fromisoformat(row["expires_at"])
        if expires_at <= datetime.now(timezone.utc):
            return None

        return AuthenticatedPrincipal(
            user_id=row["user_id"],
            session_id=row["session_id"],
        )

    def logout(self, token: str) -> bool:
        principal = self.authenticate(token)
        if principal is None:
            return False
        self.auth_store.revoke_session(
            principal.session_id,
            datetime.now(timezone.utc).isoformat(),
        )
        return True

    def revoke_all_sessions(self, user_id: str) -> None:
        self.auth_store.revoke_all_for_user(
            user_id,
            datetime.now(timezone.utc).isoformat(),
        )

    def _issue_session(self, user_id: str) -> AuthResult:
        token = secrets.token_urlsafe(48)
        now = datetime.now(timezone.utc)
        expires = now + timedelta(hours=self.SESSION_HOURS)
        session_id = f"session_{uuid.uuid4().hex}"

        self.auth_store.create_session(
            session_id,
            user_id,
            self._token_hash(token),
            now.isoformat(),
            expires.isoformat(),
        )
        return AuthResult(
            True,
            "AUTHENTICATED",
            user_id=user_id,
            token=token,
        )

    @staticmethod
    def _derive(password: str, salt: bytes, iterations: int) -> bytes:
        return hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            iterations,
        )

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()
