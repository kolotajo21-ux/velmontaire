from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable


class SequenceEvaluationError(ValueError):
    """Fail-closed sequence evaluation error."""


class SequenceStatus(str, Enum):
    WAITING = "WAITING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"


@dataclass(frozen=True, slots=True)
class SequenceStep:
    name: str
    max_bars_after_previous: int | None = None

    def __post_init__(self) -> None:
        name = str(self.name or "").strip()
        if not name:
            raise ValueError("sequence_step_name_required")
        object.__setattr__(self, "name", name)

        if self.max_bars_after_previous is not None:
            value = int(self.max_bars_after_previous)
            if value < 0:
                raise ValueError("max_bars_after_previous_must_be_non_negative")
            object.__setattr__(self, "max_bars_after_previous", value)


@dataclass(slots=True)
class SequenceState:
    next_step_index: int = 0
    started_bar: int | None = None
    last_matched_bar: int | None = None
    matched_bars: list[int] = field(default_factory=list)
    status: SequenceStatus = SequenceStatus.WAITING
    reason: str | None = None

    @property
    def completed(self) -> bool:
        return self.status == SequenceStatus.COMPLETED

    def reset(self) -> None:
        self.next_step_index = 0
        self.started_bar = None
        self.last_matched_bar = None
        self.matched_bars.clear()
        self.status = SequenceStatus.WAITING
        self.reason = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "next_step_index": self.next_step_index,
            "started_bar": self.started_bar,
            "last_matched_bar": self.last_matched_bar,
            "matched_bars": list(self.matched_bars),
            "status": self.status.value,
            "reason": self.reason,
            "completed": self.completed,
        }


@dataclass(frozen=True, slots=True)
class SequenceUpdate:
    status: SequenceStatus
    matched_step: str | None
    next_step: str | None
    completed: bool
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "matched_step": self.matched_step,
            "next_step": self.next_step,
            "completed": self.completed,
            "reason": self.reason,
        }


class UniversalSequenceEngine:
    """
    Stateful ordered-event engine.

    Guarantees:
    - steps must occur in declared order;
    - max bars between steps can be global or step-specific;
    - optional total expiration is enforced;
    - explicit invalidation terminates the sequence;
    - missing/invalid state never gets guessed;
    - reset is explicit and deterministic.
    """

    def __init__(
        self,
        steps: Iterable[str | SequenceStep],
        *,
        max_bars_between_steps: int | None = None,
        expiration_bars: int | None = None,
    ) -> None:
        parsed: list[SequenceStep] = []
        for item in steps:
            parsed.append(item if isinstance(item, SequenceStep) else SequenceStep(str(item)))

        if not parsed:
            raise ValueError("sequence_steps_required")

        if max_bars_between_steps is not None and int(max_bars_between_steps) < 0:
            raise ValueError("max_bars_between_steps_must_be_non_negative")
        if expiration_bars is not None and int(expiration_bars) < 0:
            raise ValueError("expiration_bars_must_be_non_negative")

        self.steps = tuple(parsed)
        self.max_bars_between_steps = (
            int(max_bars_between_steps)
            if max_bars_between_steps is not None
            else None
        )
        self.expiration_bars = (
            int(expiration_bars)
            if expiration_bars is not None
            else None
        )

    def new_state(self) -> SequenceState:
        return SequenceState()

    def update(
        self,
        state: SequenceState,
        *,
        bar_index: int,
        events: Iterable[str] = (),
        invalidated: bool = False,
    ) -> SequenceUpdate:
        if not isinstance(state, SequenceState):
            raise SequenceEvaluationError("invalid_sequence_state")

        bar = int(bar_index)
        if bar < 0:
            raise SequenceEvaluationError("bar_index_must_be_non_negative")

        if state.status in {
            SequenceStatus.COMPLETED,
            SequenceStatus.EXPIRED,
            SequenceStatus.INVALIDATED,
        }:
            return self._result(state, None)

        if state.last_matched_bar is not None and bar < state.last_matched_bar:
            raise SequenceEvaluationError("bar_index_moved_backwards")

        if invalidated:
            state.status = SequenceStatus.INVALIDATED
            state.reason = "sequence_invalidated"
            return self._result(state, None)

        if self._is_total_expired(state, bar):
            state.status = SequenceStatus.EXPIRED
            state.reason = "sequence_expired"
            return self._result(state, None)

        if self._is_step_expired(state, bar):
            state.status = SequenceStatus.EXPIRED
            state.reason = "max_bars_between_steps_exceeded"
            return self._result(state, None)

        normalized_events = {
            str(event or "").strip().upper()
            for event in events
            if str(event or "").strip()
        }

        expected = self.steps[state.next_step_index]
        if expected.name.upper() not in normalized_events:
            return self._result(state, None)

        if state.started_bar is None:
            state.started_bar = bar

        state.last_matched_bar = bar
        state.matched_bars.append(bar)
        state.next_step_index += 1

        if state.next_step_index >= len(self.steps):
            state.status = SequenceStatus.COMPLETED
            state.reason = None
            return self._result(state, expected.name)

        state.status = SequenceStatus.IN_PROGRESS
        state.reason = None
        return self._result(state, expected.name)

    def reset(self, state: SequenceState) -> SequenceState:
        if not isinstance(state, SequenceState):
            raise SequenceEvaluationError("invalid_sequence_state")
        state.reset()
        return state

    def must_happen_after(self, earlier_step: str, later_step: str) -> bool:
        return self._index(earlier_step) < self._index(later_step)

    def must_happen_before(self, earlier_step: str, later_step: str) -> bool:
        return self.must_happen_after(earlier_step, later_step)

    def _is_total_expired(self, state: SequenceState, bar: int) -> bool:
        return (
            self.expiration_bars is not None
            and state.started_bar is not None
            and bar - state.started_bar > self.expiration_bars
        )

    def _is_step_expired(self, state: SequenceState, bar: int) -> bool:
        if state.last_matched_bar is None or state.next_step_index == 0:
            return False

        expected = self.steps[state.next_step_index]
        limit = (
            expected.max_bars_after_previous
            if expected.max_bars_after_previous is not None
            else self.max_bars_between_steps
        )
        return limit is not None and bar - state.last_matched_bar > limit

    def _index(self, name: str) -> int:
        target = str(name or "").strip().upper()
        for index, step in enumerate(self.steps):
            if step.name.upper() == target:
                return index
        raise SequenceEvaluationError(f"unknown_sequence_step:{name}")

    def _result(
        self,
        state: SequenceState,
        matched_step: str | None,
    ) -> SequenceUpdate:
        next_step = (
            self.steps[state.next_step_index].name
            if state.next_step_index < len(self.steps)
            else None
        )
        return SequenceUpdate(
            status=state.status,
            matched_step=matched_step,
            next_step=next_step,
            completed=state.completed,
            reason=state.reason,
        )
