from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from .capability_registry import (
    CapabilityVersion,
    CustomCapabilityRegistry,
)


class CapabilityPersistenceError(ValueError):
    """Fail-closed persistence error."""


class CapabilityPersistenceLayer:
    FORMAT_VERSION = 1

    def save(
        self,
        registry: CustomCapabilityRegistry,
        path: str | Path,
    ) -> Path:
        if not isinstance(registry, CustomCapabilityRegistry):
            raise CapabilityPersistenceError(
                "custom_capability_registry_required"
            )

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)

        capabilities: list[dict[str, Any]] = []
        for capability_id in sorted(registry._by_id):
            versions = registry._by_id[capability_id]
            capabilities.append({
                "capability_id": capability_id,
                "versions": [asdict(v) for v in versions],
            })

        payload = {
            "format_version": self.FORMAT_VERSION,
            "capabilities": capabilities,
            "name_to_id": dict(sorted(registry._name_to_id.items())),
        }
        checksum = self._checksum(payload)
        envelope = {
            "checksum": checksum,
            "payload": payload,
        }

        temp = target.with_suffix(target.suffix + ".tmp")
        temp.write_text(
            json.dumps(
                envelope,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            ),
            encoding="utf-8",
        )
        temp.replace(target)
        return target

    def load(
        self,
        path: str | Path,
    ) -> CustomCapabilityRegistry:
        source = Path(path)
        if not source.exists():
            raise CapabilityPersistenceError(
                f"capability_store_not_found:{source}"
            )

        try:
            envelope = json.loads(source.read_text(encoding="utf-8"))
        except Exception as exc:
            raise CapabilityPersistenceError(
                f"capability_store_invalid_json:{exc}"
            ) from exc

        if not isinstance(envelope, dict):
            raise CapabilityPersistenceError(
                "capability_store_envelope_invalid"
            )

        payload = envelope.get("payload")
        checksum = envelope.get("checksum")
        if not isinstance(payload, dict) or not isinstance(checksum, str):
            raise CapabilityPersistenceError(
                "capability_store_envelope_invalid"
            )

        actual = self._checksum(payload)
        if actual != checksum:
            raise CapabilityPersistenceError(
                "capability_store_integrity_failed"
            )

        if payload.get("format_version") != self.FORMAT_VERSION:
            raise CapabilityPersistenceError(
                "unsupported_capability_store_format"
            )

        registry = CustomCapabilityRegistry()
        capabilities = payload.get("capabilities")
        name_to_id = payload.get("name_to_id")

        if not isinstance(capabilities, list):
            raise CapabilityPersistenceError(
                "capabilities_must_be_list"
            )
        if not isinstance(name_to_id, dict):
            raise CapabilityPersistenceError(
                "name_to_id_must_be_object"
            )

        for entry in capabilities:
            if not isinstance(entry, dict):
                raise CapabilityPersistenceError(
                    "invalid_capability_entry"
                )
            capability_id = str(
                entry.get("capability_id") or ""
            ).strip()
            raw_versions = entry.get("versions")
            if not capability_id or not isinstance(raw_versions, list):
                raise CapabilityPersistenceError(
                    "invalid_capability_entry"
                )
            if not raw_versions:
                raise CapabilityPersistenceError(
                    f"capability_versions_required:{capability_id}"
                )

            versions: list[CapabilityVersion] = []
            expected_version = 1
            for raw in raw_versions:
                if not isinstance(raw, dict):
                    raise CapabilityPersistenceError(
                        "invalid_capability_version"
                    )
                try:
                    item = CapabilityVersion(
                        capability_id=str(raw["capability_id"]),
                        name=str(raw["name"]),
                        version=int(raw["version"]),
                        rule_id=str(raw["rule_id"]),
                        enabled=bool(raw["enabled"]),
                        created_at=str(raw["created_at"]),
                        executable_spec=dict(raw["executable_spec"]),
                        description=str(raw.get("description", "")),
                        metadata=dict(raw.get("metadata", {})),
                    )
                except Exception as exc:
                    raise CapabilityPersistenceError(
                        f"invalid_capability_version:{exc}"
                    ) from exc

                if item.capability_id != capability_id:
                    raise CapabilityPersistenceError(
                        "capability_id_mismatch"
                    )
                if item.version != expected_version:
                    raise CapabilityPersistenceError(
                        f"non_contiguous_capability_versions:{capability_id}"
                    )
                if not item.rule_id or not item.name or not item.executable_spec:
                    raise CapabilityPersistenceError(
                        "capability_version_incomplete"
                    )

                versions.append(item)
                expected_version += 1

            registry._by_id[capability_id] = versions

        rebuilt_names: dict[str, str] = {}
        for capability_id, versions in registry._by_id.items():
            latest = versions[-1]
            key = registry._name_key(latest.name)
            if key in rebuilt_names:
                raise CapabilityPersistenceError(
                    f"duplicate_capability_name:{latest.name}"
                )
            rebuilt_names[key] = capability_id

        normalized_saved = {
            str(k): str(v)
            for k, v in name_to_id.items()
        }
        if normalized_saved != rebuilt_names:
            raise CapabilityPersistenceError(
                "capability_name_index_integrity_failed"
            )

        registry._name_to_id = rebuilt_names
        return registry

    @staticmethod
    def _checksum(payload: dict[str, Any]) -> str:
        raw = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return sha256(raw).hexdigest()
