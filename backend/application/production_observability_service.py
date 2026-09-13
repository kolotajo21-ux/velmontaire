from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any
import hashlib
import json
import re


@dataclass(frozen=True, slots=True)
class AuditEvent:
    event_id: str
    timestamp: str
    user_id: str
    category: str
    action: str
    severity: str
    resource_type: str | None
    resource_id: str | None
    correlation_id: str
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProductionObservabilityService:
    """
    Sanitized production observability + audit boundary.

    Records operational/security/product events without persisting credentials,
    bearer tokens or other obvious secret material. Support views remain
    user-scoped and expose sanitized diagnostics only.
    """

    SECRET_KEYS = {
        "password", "broker_password", "token", "access_token",
        "refresh_token", "authorization", "secret", "api_key",
        "credential", "credentials",
    }
    ALLOWED_SEVERITIES = {"INFO", "WARNING", "ERROR", "CRITICAL"}
    ALLOWED_CATEGORIES = {
        "AUTH", "SECURITY", "STRATEGY", "BACKTEST",
        "BROKER_CONNECTION", "RUNTIME", "BILLING", "SYSTEM",
    }

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    def record(
        self,
        *,
        user_id: str,
        category: str,
        action: str,
        severity: str,
        correlation_id: str,
        details: dict[str, Any] | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        timestamp: str | None = None,
    ) -> AuditEvent:
        category = str(category).upper()
        severity = str(severity).upper()

        if category not in self.ALLOWED_CATEGORIES:
            raise ValueError("audit_category_invalid")
        if severity not in self.ALLOWED_SEVERITIES:
            raise ValueError("audit_severity_invalid")
        if not user_id or not correlation_id or not action:
            raise ValueError("audit_identity_fields_required")

        ts = timestamp or datetime.now(timezone.utc).isoformat()
        sanitized = self._sanitize(details or {})

        raw = json.dumps(
            [ts, user_id, category, action, correlation_id,
             resource_type, resource_id, sanitized],
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        event_id = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

        event = AuditEvent(
            event_id=event_id,
            timestamp=ts,
            user_id=user_id,
            category=category,
            action=str(action),
            severity=severity,
            resource_type=resource_type,
            resource_id=resource_id,
            correlation_id=correlation_id,
            details=sanitized,
        )
        self._events.append(event)
        return event

    def user_events(
        self,
        *,
        authenticated_user_id: str,
        target_user_id: str,
        correlation_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if authenticated_user_id != target_user_id:
            raise LookupError("audit_events_not_found")

        events = [x for x in self._events if x.user_id == target_user_id]
        if correlation_id is not None:
            events = [x for x in events if x.correlation_id == correlation_id]
        return [x.to_dict() for x in events]

    def support_snapshot(
        self,
        *,
        authenticated_user_id: str,
        target_user_id: str,
    ) -> dict[str, Any]:
        events = self.user_events(
            authenticated_user_id=authenticated_user_id,
            target_user_id=target_user_id,
        )
        counts: dict[str, int] = {}
        for event in events:
            key = event["severity"]
            counts[key] = counts.get(key, 0) + 1

        return {
            "user_id": target_user_id,
            "event_count": len(events),
            "severity_counts": counts,
            "recent_events": events[-50:],
            "contains_raw_credentials": False,
        }

    @classmethod
    def _sanitize(cls, value: Any, key: str | None = None) -> Any:
        if key and key.lower() in cls.SECRET_KEYS:
            return "[REDACTED]"

        if isinstance(value, dict):
            return {
                str(k): cls._sanitize(v, str(k))
                for k, v in value.items()
            }

        if isinstance(value, (list, tuple)):
            return [cls._sanitize(v) for v in value]

        if isinstance(value, str):
            # Redact obvious Bearer token material embedded in free text.
            value = re.sub(
                r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+",
                "Bearer [REDACTED]",
                value,
            )
            return value

        return value
