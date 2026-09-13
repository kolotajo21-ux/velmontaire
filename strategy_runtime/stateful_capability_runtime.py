from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .capability_registry import (
    CapabilityRegistryError,
    CustomCapabilityRegistry,
)
from .capability_validation_gate import (
    CapabilityValidationError,
    CapabilityValidationGate,
)
from .capability_runtime_state import (
    CapabilityRuntimeStateError,
    SequenceRuntimeState,
    SequenceRuntimeStatus,
)


class StatefulCapabilityRuntimeError(ValueError):
    """Fail-closed stateful capability runtime error."""


PrimitiveHandler = Callable[[dict[str, Any]], bool]


@dataclass(frozen=True, slots=True)
class StatefulExecutionResult:
    capability_id: str
    version: int
    symbol: str
    bar_index: int
    status: SequenceRuntimeStatus
    current_step: int
    matched: bool
    expired: bool
    trace: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "version": self.version,
            "symbol": self.symbol,
            "bar_index": self.bar_index,
            "status": self.status.value,
            "current_step": self.current_step,
            "matched": self.matched,
            "expired": self.expired,
            "trace": [dict(x) for x in self.trace],
        }


class StatefulCapabilityRuntime:
    """
    Stateful bar-by-bar runtime for SEQUENCE capabilities.

    State is isolated by capability id, pinned version, and symbol.
    The runtime never moves bar_index backwards.
    """

    def __init__(
        self,
        *,
        registry: CustomCapabilityRegistry,
        validation_gate: CapabilityValidationGate,
        primitive_handlers: Mapping[str, PrimitiveHandler],
    ) -> None:
        self.registry = registry
        self.validation_gate = validation_gate
        self.handlers = {
            self._norm(k): v
            for k, v in primitive_handlers.items()
        }
        self._states: dict[str, SequenceRuntimeState] = {}

    def process_bar(
        self,
        reference: str,
        *,
        symbol: str,
        bar_index: int,
        context: dict[str, Any],
        version: int | None = None,
    ) -> StatefulExecutionResult:
        item = self._resolve_valid(reference, version)

        spec = item.executable_spec
        kind = str(spec.get("kind") or "").upper()
        if kind != "SEQUENCE":
            raise StatefulCapabilityRuntimeError(
                f"stateful_runtime_requires_sequence:{kind}"
            )

        steps = spec.get("steps") or []
        if not steps:
            raise StatefulCapabilityRuntimeError(
                "sequence_steps_required"
            )

        symbol_key = str(symbol or "").strip().upper()
        if not symbol_key:
            raise StatefulCapabilityRuntimeError("symbol_required")

        idx = int(bar_index)
        key = (
            f"{item.capability_id}@v{item.version}:"
            f"{symbol_key}"
        )
        state = self._states.get(key)
        if state is None:
            state = SequenceRuntimeState(
                capability_id=item.capability_id,
                version=item.version,
                symbol=symbol_key,
            )
            self._states[key] = state

        if state.last_bar is not None and idx < state.last_bar:
            raise StatefulCapabilityRuntimeError(
                "bar_index_moved_backwards"
            )
        state.last_bar = idx

        trace: list[dict[str, Any]] = []

        # If prior bar matched or expired, next bar starts fresh.
        if state.status in (
            SequenceRuntimeStatus.MATCHED,
            SequenceRuntimeStatus.EXPIRED,
        ):
            state.reset()
            trace.append({"type": "AUTO_RESET"})

        max_between = spec.get("max_bars_between_steps")
        if max_between is not None:
            max_between = int(max_between)
            if max_between <= 0:
                raise StatefulCapabilityRuntimeError(
                    "invalid_max_bars_between_steps"
                )

        total_expiration = spec.get("total_expiration_bars")
        if total_expiration is not None:
            total_expiration = int(total_expiration)
            if total_expiration <= 0:
                raise StatefulCapabilityRuntimeError(
                    "invalid_total_expiration_bars"
                )

        if (
            state.status == SequenceRuntimeStatus.ACTIVE
            and total_expiration is not None
            and state.started_bar is not None
            and idx - state.started_bar > total_expiration
        ):
            state.status = SequenceRuntimeStatus.EXPIRED
            trace.append({
                "type": "EXPIRE",
                "reason": "TOTAL_EXPIRATION",
            })
            return self._result(state, idx, trace)

        if (
            state.status == SequenceRuntimeStatus.ACTIVE
            and max_between is not None
            and state.last_step_bar is not None
            and idx - state.last_step_bar > max_between
        ):
            state.status = SequenceRuntimeStatus.EXPIRED
            trace.append({
                "type": "EXPIRE",
                "reason": "MAX_BARS_BETWEEN_STEPS",
            })
            return self._result(state, idx, trace)

        step_index = state.current_step
        primitive = self._norm(
            str(steps[step_index].get("primitive") or "")
        )
        matched = self._execute_primitive(primitive, context)

        trace.append({
            "type": "STEP_CHECK",
            "step": step_index + 1,
            "primitive": primitive,
            "matched": matched,
        })

        if not matched:
            return self._result(state, idx, trace)

        if state.status == SequenceRuntimeStatus.IDLE:
            state.status = SequenceRuntimeStatus.ACTIVE
            state.started_bar = idx

        state.current_step += 1
        state.last_step_bar = idx

        if state.current_step >= len(steps):
            state.status = SequenceRuntimeStatus.MATCHED
            trace.append({
                "type": "SEQUENCE_MATCHED",
                "completed_steps": len(steps),
            })

        return self._result(state, idx, trace)

    def get_state(
        self,
        reference: str,
        *,
        symbol: str,
        version: int | None = None,
    ) -> SequenceRuntimeState:
        item = self._resolve_valid(reference, version)
        key = (
            f"{item.capability_id}@v{item.version}:"
            f"{str(symbol).strip().upper()}"
        )
        state = self._states.get(key)
        if state is None:
            state = SequenceRuntimeState(
                capability_id=item.capability_id,
                version=item.version,
                symbol=str(symbol).strip().upper(),
            )
            self._states[key] = state
        return state

    def export_state(self) -> dict[str, dict[str, Any]]:
        return {
            key: state.to_dict()
            for key, state in self._states.items()
        }

    def import_state(
        self,
        payload: dict[str, dict[str, Any]],
    ) -> None:
        if not isinstance(payload, dict):
            raise StatefulCapabilityRuntimeError(
                "runtime_state_payload_must_be_object"
            )
        restored: dict[str, SequenceRuntimeState] = {}
        for key, raw in payload.items():
            try:
                state = SequenceRuntimeState.from_dict(raw)
            except CapabilityRuntimeStateError as exc:
                raise StatefulCapabilityRuntimeError(
                    f"runtime_state_restore_failed:{exc}"
                ) from exc
            if state.key() != key:
                raise StatefulCapabilityRuntimeError(
                    f"runtime_state_key_mismatch:{key}"
                )
            restored[key] = state
        self._states = restored

    def reset(
        self,
        reference: str,
        *,
        symbol: str,
        version: int | None = None,
    ) -> None:
        state = self.get_state(
            reference,
            symbol=symbol,
            version=version,
        )
        state.reset()

    def _execute_primitive(
        self,
        primitive: str,
        context: dict[str, Any],
    ) -> bool:
        handler = self.handlers.get(primitive)
        if handler is None:
            raise StatefulCapabilityRuntimeError(
                f"primitive_handler_missing:{primitive}"
            )
        try:
            value = handler(context)
        except Exception as exc:
            raise StatefulCapabilityRuntimeError(
                f"primitive_handler_failed:{primitive}:{exc}"
            ) from exc
        if type(value) is not bool:
            raise StatefulCapabilityRuntimeError(
                f"primitive_handler_must_return_bool:"
                f"{primitive}:{type(value).__name__}"
            )
        return value

    def _resolve_valid(self, reference: str, version: int | None):
        try:
            report = self.validation_gate.require_valid(
                reference,
                version=version,
            )
            return self.registry.resolve(
                report.capability_id,
                version=report.version,
                require_enabled=True,
            )
        except (
            CapabilityValidationError,
            CapabilityRegistryError,
        ) as exc:
            raise StatefulCapabilityRuntimeError(
                f"stateful_execution_validation_failed:{exc}"
            ) from exc

    @staticmethod
    def _result(
        state: SequenceRuntimeState,
        bar_index: int,
        trace: list[dict[str, Any]],
    ) -> StatefulExecutionResult:
        return StatefulExecutionResult(
            capability_id=state.capability_id,
            version=state.version,
            symbol=state.symbol,
            bar_index=bar_index,
            status=state.status,
            current_step=state.current_step,
            matched=state.status == SequenceRuntimeStatus.MATCHED,
            expired=state.status == SequenceRuntimeStatus.EXPIRED,
            trace=tuple(trace),
        )

    @staticmethod
    def _norm(value: str) -> str:
        return "_".join(
            str(value or "")
            .strip()
            .upper()
            .replace("-", " ")
            .split()
        )
