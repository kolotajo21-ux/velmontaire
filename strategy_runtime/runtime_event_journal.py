from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any


class RuntimeEventJournalError(ValueError):
    """Fail-closed runtime event journal error."""


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    event_id: str
    event_type: str
    capability_id: str
    version: int
    symbol: str
    bar_index: int | None
    payload: dict[str, Any]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RuntimeEventJournal:
    FORMAT_VERSION = 1

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._events: list[RuntimeEvent] = []
        self._ids: set[str] = set()
        if self.path.exists():
            self._load()

    @staticmethod
    def make_event_id(
        *,
        event_type: str,
        capability_id: str,
        version: int,
        symbol: str,
        bar_index: int | None,
        payload: dict[str, Any] | None = None,
    ) -> str:
        canonical = {
            "event_type": str(event_type).upper(),
            "capability_id": str(capability_id),
            "version": int(version),
            "symbol": str(symbol).upper(),
            "bar_index": bar_index,
            "payload": payload or {},
        }
        raw = json.dumps(
            canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        return "EVT_" + sha256(raw).hexdigest()[:20].upper()

    def append(
        self,
        *,
        event_type: str,
        capability_id: str,
        version: int,
        symbol: str,
        bar_index: int | None,
        payload: dict[str, Any] | None = None,
    ) -> RuntimeEvent:
        payload = dict(payload or {})
        event_id = self.make_event_id(
            event_type=event_type,
            capability_id=capability_id,
            version=version,
            symbol=symbol,
            bar_index=bar_index,
            payload=payload,
        )
        existing = self.get(event_id)
        if existing is not None:
            return existing

        event = RuntimeEvent(
            event_id=event_id,
            event_type=str(event_type).upper(),
            capability_id=str(capability_id),
            version=int(version),
            symbol=str(symbol).upper(),
            bar_index=None if bar_index is None else int(bar_index),
            payload=payload,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._events.append(event)
        self._ids.add(event_id)
        self._save()
        return event

    def get(self, event_id: str) -> RuntimeEvent | None:
        for event in self._events:
            if event.event_id == event_id:
                return event
        return None

    def events(self) -> tuple[RuntimeEvent, ...]:
        return tuple(self._events)

    def _save(self) -> None:
        payload = {
            "format_version": self.FORMAT_VERSION,
            "events": [e.to_dict() for e in self._events],
        }
        target = self.path
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix(target.suffix + ".tmp")
        temp.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        temp.replace(target)

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeEventJournalError(
                f"event_journal_invalid_json:{exc}"
            ) from exc
        if raw.get("format_version") != self.FORMAT_VERSION:
            raise RuntimeEventJournalError("unsupported_event_journal_format")
        events = raw.get("events")
        if not isinstance(events, list):
            raise RuntimeEventJournalError("event_journal_events_required")
        loaded = []
        ids = set()
        for item in events:
            event = RuntimeEvent(**item)
            if event.event_id in ids:
                raise RuntimeEventJournalError(
                    f"duplicate_event_id:{event.event_id}"
                )
            expected = self.make_event_id(
                event_type=event.event_type,
                capability_id=event.capability_id,
                version=event.version,
                symbol=event.symbol,
                bar_index=event.bar_index,
                payload=event.payload,
            )
            if expected != event.event_id:
                raise RuntimeEventJournalError(
                    f"event_integrity_failed:{event.event_id}"
                )
            loaded.append(event)
            ids.add(event.event_id)
        self._events = loaded
        self._ids = ids


class JournaledRuntimeCoordinator:
    """Wraps a checkpoint coordinator and journals runtime transitions."""

    def __init__(self, *, checkpoint_coordinator: Any, journal: RuntimeEventJournal):
        self.coordinator = checkpoint_coordinator
        self.journal = journal

    def restore_if_present(self) -> bool:
        restored = self.coordinator.restore_if_present()
        if restored:
            state = self.coordinator.runtime.export_state()
            for item in state.values():
                self.journal.append(
                    event_type="RESTORE",
                    capability_id=item["capability_id"],
                    version=item["version"],
                    symbol=item["symbol"],
                    bar_index=item.get("last_bar"),
                    payload={
                        "current_step": item.get("current_step"),
                        "status": item.get("status"),
                    },
                )
        return restored

    def process_bar(self, *args: Any, **kwargs: Any) -> Any:
        result = self.coordinator.process_bar(*args, **kwargs)
        self._journal_result(result)
        return result

    def _journal_result(self, result: Any) -> None:
        trace = getattr(result, "trace", ()) or ()
        cap_id = result.capability_id
        version = result.version
        symbol = result.symbol
        bar_index = result.bar_index

        for item in trace:
            typ = item.get("type")
            if typ == "SEQUENCE_STEP" and item.get("matched"):
                self.journal.append(
                    event_type="STEP_MATCHED",
                    capability_id=cap_id,
                    version=version,
                    symbol=symbol,
                    bar_index=bar_index,
                    payload={
                        "step": item.get("step"),
                        "reference": item.get("reference"),
                        "state_key": item.get("state_key"),
                    },
                )
            elif typ == "EXPIRE":
                self.journal.append(
                    event_type="EXPIRED",
                    capability_id=cap_id,
                    version=version,
                    symbol=symbol,
                    bar_index=bar_index,
                    payload={"reason": item.get("reason"), "state_key": item.get("state_key")},
                )
            elif typ == "AUTO_RESET":
                self.journal.append(
                    event_type="RESET",
                    capability_id=cap_id,
                    version=version,
                    symbol=symbol,
                    bar_index=bar_index,
                    payload={"state_key": item.get("state_key")},
                )

        if getattr(result, "matched", False):
            self.journal.append(
                event_type="CAPABILITY_MATCHED",
                capability_id=cap_id,
                version=version,
                symbol=symbol,
                bar_index=bar_index,
                payload={"status": getattr(result, "status", "MATCHED")},
            )
