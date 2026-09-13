from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    user_id: str
    session_id: str


@dataclass(frozen=True, slots=True)
class AuthResult:
    success: bool
    status: str
    user_id: str | None = None
    token: str | None = None
    error: str | None = None
