from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Callable


class CapabilityMigrationError(ValueError):
    """Fail-closed capability store migration error."""


@dataclass(frozen=True, slots=True)
class MigrationResult:
    from_version: int
    to_version: int
    applied_steps: tuple[str, ...]
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_version": self.from_version,
            "to_version": self.to_version,
            "applied_steps": list(self.applied_steps),
            "payload": deepcopy(self.payload),
        }


class CapabilityMigrationEngine:
    """
    Deterministic schema migration engine for persisted capability stores.

    v1 -> v2 adds:
      - schema_version to each capability version
      - lifecycle object with enabled flag
      - normalized metadata defaults

    Old data is never mutated in place.
    Unsupported future formats fail closed.
    """

    CURRENT_VERSION = 2

    def __init__(self) -> None:
        self._migrations: dict[
            int,
            tuple[int, str, Callable[[dict[str, Any]], dict[str, Any]]],
        ] = {
            1: (2, "v1_to_v2_capability_lifecycle", self._v1_to_v2),
        }

    def migrate(
        self,
        payload: dict[str, Any],
        *,
        target_version: int | None = None,
    ) -> MigrationResult:
        if not isinstance(payload, dict):
            raise CapabilityMigrationError("migration_payload_required")

        data = deepcopy(payload)
        try:
            start = int(data["format_version"])
        except Exception as exc:
            raise CapabilityMigrationError(
                "format_version_required"
            ) from exc

        target = (
            self.CURRENT_VERSION
            if target_version is None
            else int(target_version)
        )

        if start <= 0 or target <= 0:
            raise CapabilityMigrationError(
                "format_version_must_be_positive"
            )
        if start > self.CURRENT_VERSION:
            raise CapabilityMigrationError(
                f"future_format_not_supported:{start}"
            )
        if target > self.CURRENT_VERSION:
            raise CapabilityMigrationError(
                f"target_format_not_supported:{target}"
            )
        if target < start:
            raise CapabilityMigrationError(
                f"downgrade_not_supported:{start}:{target}"
            )

        current = start
        steps: list[str] = []

        while current < target:
            migration = self._migrations.get(current)
            if migration is None:
                raise CapabilityMigrationError(
                    f"migration_path_missing:{current}:{target}"
                )
            next_version, name, fn = migration
            if next_version <= current:
                raise CapabilityMigrationError(
                    "invalid_migration_registration"
                )

            data = fn(data)
            if int(data.get("format_version", -1)) != next_version:
                raise CapabilityMigrationError(
                    f"migration_did_not_advance:{name}"
                )

            steps.append(name)
            current = next_version

        self.validate_current(data, expected_version=target)

        return MigrationResult(
            from_version=start,
            to_version=current,
            applied_steps=tuple(steps),
            payload=data,
        )

    def validate_current(
        self,
        payload: dict[str, Any],
        *,
        expected_version: int | None = None,
    ) -> None:
        version = int(payload.get("format_version", -1))
        expected = (
            self.CURRENT_VERSION
            if expected_version is None
            else int(expected_version)
        )
        if version != expected:
            raise CapabilityMigrationError(
                f"unexpected_format_version:{version}:{expected}"
            )

        capabilities = payload.get("capabilities")
        name_to_id = payload.get("name_to_id")
        if not isinstance(capabilities, list):
            raise CapabilityMigrationError(
                "capabilities_must_be_list"
            )
        if not isinstance(name_to_id, dict):
            raise CapabilityMigrationError(
                "name_to_id_must_be_object"
            )

        seen_ids: set[str] = set()
        for entry in capabilities:
            if not isinstance(entry, dict):
                raise CapabilityMigrationError(
                    "invalid_capability_entry"
                )
            cid = str(entry.get("capability_id") or "").strip()
            versions = entry.get("versions")
            if not cid or cid in seen_ids:
                raise CapabilityMigrationError(
                    f"invalid_or_duplicate_capability_id:{cid}"
                )
            seen_ids.add(cid)
            if not isinstance(versions, list) or not versions:
                raise CapabilityMigrationError(
                    f"capability_versions_required:{cid}"
                )

            expected_number = 1
            for item in versions:
                if not isinstance(item, dict):
                    raise CapabilityMigrationError(
                        "invalid_capability_version"
                    )
                if int(item.get("version", -1)) != expected_number:
                    raise CapabilityMigrationError(
                        f"non_contiguous_capability_versions:{cid}"
                    )
                if str(item.get("capability_id")) != cid:
                    raise CapabilityMigrationError(
                        "capability_id_mismatch"
                    )
                if not str(item.get("rule_id") or "").strip():
                    raise CapabilityMigrationError(
                        "rule_id_required"
                    )
                if not str(item.get("name") or "").strip():
                    raise CapabilityMigrationError(
                        "capability_name_required"
                    )
                if not isinstance(item.get("executable_spec"), dict):
                    raise CapabilityMigrationError(
                        "executable_spec_required"
                    )

                if version >= 2:
                    if int(item.get("schema_version", -1)) != 2:
                        raise CapabilityMigrationError(
                            "capability_schema_version_invalid"
                        )
                    lifecycle = item.get("lifecycle")
                    if not isinstance(lifecycle, dict):
                        raise CapabilityMigrationError(
                            "capability_lifecycle_required"
                        )
                    if not isinstance(
                        lifecycle.get("enabled"), bool
                    ):
                        raise CapabilityMigrationError(
                            "capability_enabled_flag_invalid"
                        )
                    if not isinstance(item.get("metadata"), dict):
                        raise CapabilityMigrationError(
                            "capability_metadata_invalid"
                        )
                expected_number += 1

    @staticmethod
    def payload_checksum(payload: dict[str, Any]) -> str:
        raw = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return sha256(raw).hexdigest()

    @staticmethod
    def _v1_to_v2(payload: dict[str, Any]) -> dict[str, Any]:
        data = deepcopy(payload)
        if int(data.get("format_version", -1)) != 1:
            raise CapabilityMigrationError(
                "v1_migration_requires_v1_payload"
            )

        capabilities = data.get("capabilities")
        if not isinstance(capabilities, list):
            raise CapabilityMigrationError(
                "capabilities_must_be_list"
            )

        for entry in capabilities:
            if not isinstance(entry, dict):
                raise CapabilityMigrationError(
                    "invalid_capability_entry"
                )
            versions = entry.get("versions")
            if not isinstance(versions, list):
                raise CapabilityMigrationError(
                    "capability_versions_must_be_list"
                )
            for item in versions:
                if not isinstance(item, dict):
                    raise CapabilityMigrationError(
                        "invalid_capability_version"
                    )

                enabled = item.pop("enabled", None)
                if not isinstance(enabled, bool):
                    raise CapabilityMigrationError(
                        "legacy_enabled_flag_invalid"
                    )

                item["schema_version"] = 2
                item["lifecycle"] = {
                    "enabled": enabled,
                    "state": "ACTIVE" if enabled else "DISABLED",
                }
                metadata = item.get("metadata")
                if metadata is None:
                    item["metadata"] = {}
                elif not isinstance(metadata, dict):
                    raise CapabilityMigrationError(
                        "capability_metadata_invalid"
                    )

        data["format_version"] = 2
        return data
