from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .runtime_event_journal import RuntimeEvent


class RuntimeEventReplayError(ValueError):
    """Fail-closed event replay / reconstruction error."""


@dataclass(frozen=True, slots=True)
class ReconstructedRuntimeState:
    capability_id: str
    version: int
    symbol: str
    current_step: int
    last_bar: int | None
    status: str
    matched: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "version": self.version,
            "symbol": self.symbol,
            "current_step": self.current_step,
            "last_bar": self.last_bar,
            "status": self.status,
            "matched": self.matched,
        }


class RuntimeEventReplayer:
    """Reconstructs semantic runtime state from an ordered event journal."""

    def replay(
        self,
        events: Iterable[RuntimeEvent],
    ) -> dict[str, ReconstructedRuntimeState]:
        states: dict[str, ReconstructedRuntimeState] = {}
        seen: set[str] = set()

        for event in events:
            if event.event_id in seen:
                continue
            seen.add(event.event_id)

            key = (
                f"{event.capability_id}@v{event.version}:"
                f"{event.symbol.upper()}"
            )
            previous = states.get(key)
            step = previous.current_step if previous else 0
            status = previous.status if previous else "IDLE"
            matched = previous.matched if previous else False
            last_bar = event.bar_index if event.bar_index is not None else (
                previous.last_bar if previous else None
            )

            typ = event.event_type.upper()
            payload = event.payload or {}

            if typ == "STEP_MATCHED":
                raw_step = payload.get("step")
                if raw_step is None:
                    raise RuntimeEventReplayError(
                        f"replay_step_missing:{event.event_id}"
                    )
                raw_step = int(raw_step)
                if raw_step <= 0:
                    raise RuntimeEventReplayError(
                        f"replay_step_invalid:{event.event_id}:{raw_step}"
                    )
                if raw_step < step:
                    raise RuntimeEventReplayError(
                        f"replay_step_moved_backwards:{event.event_id}"
                    )
                step = raw_step
                status = "ACTIVE"
                matched = False

            elif typ == "CAPABILITY_MATCHED":
                status = "MATCHED"
                matched = True

            elif typ == "EXPIRED":
                status = "EXPIRED"
                matched = False

            elif typ == "RESET":
                step = 0
                status = "IDLE"
                matched = False

            elif typ == "RESTORE":
                restored_step = payload.get("current_step")
                restored_status = payload.get("status")
                if restored_step is not None:
                    step = int(restored_step)
                if restored_status is not None:
                    status = str(restored_status).upper()
                    matched = status == "MATCHED"

            else:
                raise RuntimeEventReplayError(
                    f"unsupported_replay_event:{typ}"
                )

            states[key] = ReconstructedRuntimeState(
                capability_id=event.capability_id,
                version=event.version,
                symbol=event.symbol.upper(),
                current_step=step,
                last_bar=last_bar,
                status=status,
                matched=matched,
            )

        return states

    def verify_checkpoint(
        self,
        *,
        events: Iterable[RuntimeEvent],
        checkpoint_states: dict[str, dict[str, Any]],
    ) -> bool:
        replayed = self.replay(events)
        for key, state in replayed.items():
            checkpoint = checkpoint_states.get(key)
            if checkpoint is None:
                raise RuntimeEventReplayError(
                    f"checkpoint_state_missing:{key}"
                )

            # Compare semantic fields journal can prove.
            expected = {
                "capability_id": checkpoint.get("capability_id"),
                "version": int(checkpoint.get("version")),
                "symbol": str(checkpoint.get("symbol")).upper(),
                "current_step": int(checkpoint.get("current_step", 0)),
                "last_bar": checkpoint.get("last_bar"),
                "status": str(checkpoint.get("status", "IDLE")).upper(),
            }
            actual = state.to_dict()
            for field in (
                "capability_id",
                "version",
                "symbol",
                "current_step",
                "last_bar",
                "status",
            ):
                if actual[field] != expected[field]:
                    raise RuntimeEventReplayError(
                        f"checkpoint_replay_mismatch:{key}:{field}:"
                        f"{actual[field]}:{expected[field]}"
                    )
        return True
