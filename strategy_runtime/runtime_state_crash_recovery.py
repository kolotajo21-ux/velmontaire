from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any


class RuntimeStateRecoveryError(ValueError):
    """Fail-closed runtime state recovery error."""


class RuntimeStateCrashRecovery:
    FORMAT_VERSION = 1

    @staticmethod
    def _checksum(payload: dict[str, Any]) -> str:
        raw = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return sha256(raw).hexdigest()

    def save(self, runtime: Any, path: str | Path) -> Path:
        if not hasattr(runtime, "export_state"):
            raise RuntimeStateRecoveryError("runtime_export_state_required")
        states = runtime.export_state()
        if not isinstance(states, dict):
            raise RuntimeStateRecoveryError("runtime_state_must_be_object")

        payload = {
            "format_version": self.FORMAT_VERSION,
            "states": states,
        }
        envelope = {
            "checksum": self._checksum(payload),
            "payload": payload,
        }

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix(target.suffix + ".tmp")
        temp.write_text(
            json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        temp.replace(target)
        return target

    def restore(self, runtime: Any, path: str | Path) -> dict[str, dict[str, Any]]:
        if not hasattr(runtime, "import_state"):
            raise RuntimeStateRecoveryError("runtime_import_state_required")

        source = Path(path)
        if not source.exists():
            raise RuntimeStateRecoveryError(
                f"runtime_state_store_not_found:{source}"
            )
        try:
            envelope = json.loads(source.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeStateRecoveryError(
                f"runtime_state_invalid_json:{exc}"
            ) from exc

        if not isinstance(envelope, dict):
            raise RuntimeStateRecoveryError("runtime_state_envelope_invalid")
        payload = envelope.get("payload")
        checksum = envelope.get("checksum")
        if not isinstance(payload, dict) or not isinstance(checksum, str):
            raise RuntimeStateRecoveryError("runtime_state_envelope_invalid")
        if self._checksum(payload) != checksum:
            raise RuntimeStateRecoveryError("runtime_state_integrity_failed")
        if payload.get("format_version") != self.FORMAT_VERSION:
            raise RuntimeStateRecoveryError("unsupported_runtime_state_format")

        states = payload.get("states")
        if not isinstance(states, dict):
            raise RuntimeStateRecoveryError("runtime_states_required")

        try:
            runtime.import_state(states)
        except Exception as exc:
            raise RuntimeStateRecoveryError(
                f"runtime_state_import_failed:{exc}"
            ) from exc
        return states
