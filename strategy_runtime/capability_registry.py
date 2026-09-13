from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any

from .custom_rule_builder import CompiledCustomRule


class CapabilityRegistryError(ValueError):
    """Fail-closed custom capability registry error."""


@dataclass(frozen=True, slots=True)
class CapabilityVersion:
    capability_id: str
    name: str
    version: int
    rule_id: str
    enabled: bool
    created_at: str
    executable_spec: dict[str, Any]
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "name": self.name,
            "version": self.version,
            "rule_id": self.rule_id,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "executable_spec": dict(self.executable_spec),
            "description": self.description,
            "metadata": dict(self.metadata),
        }


class CustomCapabilityRegistry:
    """
    In-memory versioned registry for compiled custom rules.

    Safety properties:
    - names are unique per capability;
    - registering the same rule again is idempotent;
    - changed definitions create a new version only explicitly;
    - existing capabilities are never silently overwritten;
    - disabled capabilities cannot be resolved for execution.
    """

    def __init__(self) -> None:
        self._by_id: dict[str, list[CapabilityVersion]] = {}
        self._name_to_id: dict[str, str] = {}

    def register(
        self,
        rule: CompiledCustomRule,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> CapabilityVersion:
        self._validate_rule(rule)
        name_key = self._name_key(rule.name)

        existing_id = self._name_to_id.get(name_key)
        if existing_id is not None:
            latest = self.latest(existing_id)
            if latest.rule_id == rule.rule_id:
                return latest
            raise CapabilityRegistryError(
                f"capability_name_conflict:{rule.name}"
            )

        capability_id = "CAP_" + rule.rule_id.removeprefix("CR_")
        item = self._make_version(
            capability_id=capability_id,
            rule=rule,
            version=1,
            enabled=True,
            metadata=metadata,
        )
        self._by_id[capability_id] = [item]
        self._name_to_id[name_key] = capability_id
        return item

    def create_version(
        self,
        capability_id: str,
        rule: CompiledCustomRule,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> CapabilityVersion:
        self._validate_rule(rule)
        versions = self._versions(capability_id)
        latest = versions[-1]

        if self._name_key(rule.name) != self._name_key(latest.name):
            raise CapabilityRegistryError(
                "capability_version_name_mismatch"
            )

        if latest.rule_id == rule.rule_id:
            return latest

        item = self._make_version(
            capability_id=latest.capability_id,
            rule=rule,
            version=latest.version + 1,
            enabled=latest.enabled,
            metadata=metadata,
        )
        versions.append(item)
        return item

    def set_enabled(
        self,
        capability_id: str,
        enabled: bool,
    ) -> CapabilityVersion:
        versions = self._versions(capability_id)
        latest = versions[-1]
        updated = replace(latest, enabled=bool(enabled))
        versions[-1] = updated
        return updated

    def latest(self, capability_id: str) -> CapabilityVersion:
        return self._versions(capability_id)[-1]

    def get_version(
        self,
        capability_id: str,
        version: int,
    ) -> CapabilityVersion:
        if int(version) <= 0:
            raise CapabilityRegistryError("version_must_be_positive")
        for item in self._versions(capability_id):
            if item.version == int(version):
                return item
        raise CapabilityRegistryError(
            f"capability_version_not_found:{capability_id}:{version}"
        )

    def resolve(
        self,
        name_or_id: str,
        *,
        version: int | None = None,
        require_enabled: bool = True,
    ) -> CapabilityVersion:
        raw = str(name_or_id or "").strip()
        if not raw:
            raise CapabilityRegistryError("capability_reference_required")

        capability_id = (
            raw
            if raw in self._by_id
            else self._name_to_id.get(self._name_key(raw))
        )
        if capability_id is None:
            raise CapabilityRegistryError(
                f"capability_not_found:{raw}"
            )

        latest = self.latest(capability_id)
        item = (
            latest
            if version is None
            else self.get_version(capability_id, version)
        )

        # Enabled/disabled is a capability-level execution gate.
        # A pinned historical version must not bypass a disabled capability.
        if require_enabled and not latest.enabled:
            raise CapabilityRegistryError(
                f"capability_disabled:{capability_id}"
            )

        return item

    def history(
        self,
        capability_id: str,
    ) -> tuple[CapabilityVersion, ...]:
        return tuple(self._versions(capability_id))

    def list_capabilities(
        self,
        *,
        enabled_only: bool = False,
    ) -> list[CapabilityVersion]:
        items = [versions[-1] for versions in self._by_id.values()]
        if enabled_only:
            items = [x for x in items if x.enabled]
        return sorted(items, key=lambda x: (x.name.upper(), x.capability_id))

    def _versions(
        self,
        capability_id: str,
    ) -> list[CapabilityVersion]:
        cid = str(capability_id or "").strip()
        versions = self._by_id.get(cid)
        if not versions:
            raise CapabilityRegistryError(
                f"capability_not_found:{cid}"
            )
        return versions

    @staticmethod
    def _validate_rule(rule: CompiledCustomRule) -> None:
        if not isinstance(rule, CompiledCustomRule):
            raise CapabilityRegistryError(
                "compiled_custom_rule_required"
            )
        if not rule.rule_id or not rule.executable_spec:
            raise CapabilityRegistryError(
                "compiled_rule_incomplete"
            )

    @staticmethod
    def _name_key(name: str) -> str:
        key = " ".join(str(name or "").strip().upper().split())
        if not key:
            raise CapabilityRegistryError("capability_name_required")
        return key

    @staticmethod
    def _make_version(
        *,
        capability_id: str,
        rule: CompiledCustomRule,
        version: int,
        enabled: bool,
        metadata: dict[str, Any] | None,
    ) -> CapabilityVersion:
        return CapabilityVersion(
            capability_id=capability_id,
            name=rule.name,
            version=version,
            rule_id=rule.rule_id,
            enabled=enabled,
            created_at=datetime.now(timezone.utc).isoformat(),
            executable_spec=dict(rule.executable_spec),
            description=rule.description,
            metadata=dict(metadata or {}),
        )
