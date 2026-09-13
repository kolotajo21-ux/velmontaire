from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .runtime_event_journal import RuntimeEvent
from .runtime_event_replay import RuntimeEventReplayer, RuntimeEventReplayError


class RuntimeReconciliationError(ValueError):
    """Fail-closed checkpoint / journal reconciliation error."""


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    status: str
    source_of_truth: str
    checkpoint_keys: tuple[str, ...]
    replay_keys: tuple[str, ...]
    repaired_keys: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "source_of_truth": self.source_of_truth,
            "checkpoint_keys": list(self.checkpoint_keys),
            "replay_keys": list(self.replay_keys),
            "repaired_keys": list(self.repaired_keys),
        }


class RuntimeCheckpointJournalReconciler:
    """
    Reconciles durable checkpoint state with the semantic event journal.

    Rules:
    - exact agreement -> checkpoint accepted;
    - checkpoint behind journal -> journal advances semantic state;
    - contradictory checkpoint -> fail closed;
    - journal missing state present in checkpoint -> fail closed.
    """

    def __init__(self, replayer: RuntimeEventReplayer | None = None) -> None:
        self.replayer = replayer or RuntimeEventReplayer()

    def reconcile(
        self,
        *,
        checkpoint_states: dict[str, dict[str, Any]],
        events: Iterable[RuntimeEvent],
    ) -> tuple[dict[str, dict[str, Any]], ReconciliationReport]:
        if not isinstance(checkpoint_states, dict):
            raise RuntimeReconciliationError("checkpoint_states_must_be_object")

        events = tuple(events)
        try:
            replayed = self.replayer.replay(events)
        except RuntimeEventReplayError as exc:
            raise RuntimeReconciliationError(
                f"journal_replay_failed:{exc}"
            ) from exc

        if not replayed:
            if checkpoint_states:
                raise RuntimeReconciliationError(
                    "journal_empty_checkpoint_nonempty"
                )
            return {}, ReconciliationReport(
                status="CONSISTENT",
                source_of_truth="EMPTY",
                checkpoint_keys=(),
                replay_keys=(),
                repaired_keys=(),
            )

        repaired = {
            key: dict(value)
            for key, value in checkpoint_states.items()
        }
        repaired_keys: list[str] = []

        for key, replay_state in replayed.items():
            journal = replay_state.to_dict()
            checkpoint = repaired.get(key)

            if checkpoint is None:
                repaired[key] = self._state_from_replay(journal)
                repaired_keys.append(key)
                continue

            self._validate_identity(key, checkpoint, journal)

            cp_step = int(checkpoint.get("current_step", 0))
            jr_step = int(journal["current_step"])
            cp_bar = checkpoint.get("last_bar")
            jr_bar = journal["last_bar"]
            cp_status = str(checkpoint.get("status", "IDLE")).upper()
            jr_status = str(journal["status"]).upper()

            if self._same_semantics(
                cp_step, jr_step, cp_bar, jr_bar, cp_status, jr_status
            ):
                continue

            if self._checkpoint_is_behind(
                cp_step=cp_step,
                jr_step=jr_step,
                cp_bar=cp_bar,
                jr_bar=jr_bar,
                cp_status=cp_status,
                jr_status=jr_status,
            ):
                updated = dict(checkpoint)
                updated["current_step"] = jr_step
                updated["last_bar"] = jr_bar
                updated["status"] = jr_status

                # Journal does not always prove these exact bar values.
                # Preserve them only when still semantically safe.
                if jr_status in {"IDLE", "EXPIRED"}:
                    updated["started_bar"] = None
                    updated["last_step_bar"] = None
                elif jr_bar is not None:
                    updated["last_step_bar"] = jr_bar
                    if updated.get("started_bar") is None:
                        updated["started_bar"] = jr_bar

                repaired[key] = updated
                repaired_keys.append(key)
                continue

            raise RuntimeReconciliationError(
                f"checkpoint_journal_conflict:{key}:"
                f"checkpoint(step={cp_step},bar={cp_bar},status={cp_status}):"
                f"journal(step={jr_step},bar={jr_bar},status={jr_status})"
            )

        extra_checkpoint = set(repaired) - set(replayed)
        if extra_checkpoint:
            raise RuntimeReconciliationError(
                "checkpoint_state_without_journal:"
                + ",".join(sorted(extra_checkpoint))
            )

        status = "REPAIRED_FROM_JOURNAL" if repaired_keys else "CONSISTENT"
        source = "JOURNAL" if repaired_keys else "CHECKPOINT"
        return repaired, ReconciliationReport(
            status=status,
            source_of_truth=source,
            checkpoint_keys=tuple(sorted(checkpoint_states)),
            replay_keys=tuple(sorted(replayed)),
            repaired_keys=tuple(sorted(repaired_keys)),
        )

    @staticmethod
    def _validate_identity(key, checkpoint, journal):
        fields = ("capability_id", "version", "symbol")
        for field in fields:
            cp = checkpoint.get(field)
            jr = journal.get(field)
            if field == "version":
                cp, jr = int(cp), int(jr)
            elif field == "symbol":
                cp, jr = str(cp).upper(), str(jr).upper()
            if cp != jr:
                raise RuntimeReconciliationError(
                    f"checkpoint_identity_conflict:{key}:{field}:{cp}:{jr}"
                )

    @staticmethod
    def _same_semantics(cp_step, jr_step, cp_bar, jr_bar, cp_status, jr_status):
        return (
            cp_step == jr_step
            and cp_bar == jr_bar
            and cp_status == jr_status
        )

    @staticmethod
    def _checkpoint_is_behind(
        *, cp_step, jr_step, cp_bar, jr_bar, cp_status, jr_status
    ):
        if cp_bar is None:
            return jr_bar is not None
        if jr_bar is None:
            return False
        if cp_bar > jr_bar:
            return False

        terminal = {"MATCHED", "EXPIRED"}
        if cp_status in terminal and cp_status != jr_status:
            return False

        if cp_bar < jr_bar:
            if jr_status == "IDLE":
                return True
            return jr_step >= cp_step or jr_status in terminal

        # Same bar: journal may contain later transition on that bar.
        if jr_step > cp_step:
            return True
        if jr_step == cp_step and cp_status != jr_status:
            allowed = {
                ("ACTIVE", "MATCHED"),
                ("ACTIVE", "EXPIRED"),
                ("MATCHED", "IDLE"),
                ("EXPIRED", "IDLE"),
            }
            return (cp_status, jr_status) in allowed
        return False

    @staticmethod
    def _state_from_replay(journal):
        status = journal["status"]
        bar = journal["last_bar"]
        return {
            "capability_id": journal["capability_id"],
            "version": journal["version"],
            "symbol": journal["symbol"],
            "current_step": journal["current_step"],
            "started_bar": None if status in {"IDLE", "EXPIRED"} else bar,
            "last_step_bar": None if status in {"IDLE", "EXPIRED"} else bar,
            "last_bar": bar,
            "status": status,
        }
