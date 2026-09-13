from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .capability_registry import CapabilityRegistryError, CustomCapabilityRegistry
from .capability_validation_gate import CapabilityValidationError, CapabilityValidationGate
from .capability_runtime_state import SequenceRuntimeState, SequenceRuntimeStatus


class StatefulNestedCapabilityRuntimeError(ValueError):
    """Fail-closed stateful nested runtime error."""


PrimitiveHandler = Callable[[dict[str, Any]], bool]


@dataclass(frozen=True, slots=True)
class StatefulNestedResult:
    capability_id: str
    version: int
    symbol: str
    bar_index: int
    status: str
    matched: bool
    trace: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "version": self.version,
            "symbol": self.symbol,
            "bar_index": self.bar_index,
            "status": self.status,
            "matched": self.matched,
            "trace": [dict(x) for x in self.trace],
        }


class StatefulNestedCapabilityRuntime:
    """Stateful SEQUENCE runtime supporting nested, version-pinned capabilities."""

    def __init__(
        self,
        *,
        registry: CustomCapabilityRegistry,
        validation_gate: CapabilityValidationGate,
        primitive_handlers: Mapping[str, PrimitiveHandler],
    ) -> None:
        self.registry = registry
        self.gate = validation_gate
        self.handlers = {self._norm(k): v for k, v in primitive_handlers.items()}
        self._states: dict[str, SequenceRuntimeState] = {}

    def process_bar(
        self,
        reference: str,
        *,
        symbol: str,
        bar_index: int,
        context: dict[str, Any],
        version: int | None = None,
    ) -> StatefulNestedResult:
        symbol = str(symbol).strip().upper()
        if not symbol:
            raise StatefulNestedCapabilityRuntimeError("symbol_required")
        if not isinstance(context, dict):
            raise StatefulNestedCapabilityRuntimeError("execution_context_must_be_object")

        item = self._resolve(reference, version)
        trace: list[dict[str, Any]] = []
        stack: list[str] = []
        matched, status = self._process_capability(
            item.capability_id, item.version, symbol, int(bar_index),
            context, trace, stack,
        )
        return StatefulNestedResult(
            item.capability_id, item.version, symbol, int(bar_index),
            status, matched, tuple(trace),
        )

    def _process_capability(
        self, capability_id: str, version: int, symbol: str, bar_index: int,
        context: dict[str, Any], trace: list[dict[str, Any]], stack: list[str],
    ) -> tuple[bool, str]:
        stack_key = f"{capability_id}@v{version}"
        if stack_key in stack:
            raise StatefulNestedCapabilityRuntimeError(
                "runtime_capability_cycle:" + "->".join(stack + [stack_key])
            )

        item = self._resolve(capability_id, version)
        spec = item.executable_spec
        kind = str(spec.get("kind") or "").upper()

        stack.append(stack_key)
        trace.append({"type": "CAPABILITY_ENTER", "capability_id": capability_id, "version": version})

        try:
            if kind == "SEQUENCE":
                matched, status = self._process_sequence(
                    item, symbol, bar_index, context, trace, stack
                )
            elif kind in {"PRIMITIVE", "LOGICAL_GROUP"}:
                matched = self._evaluate_stateless(spec, symbol, bar_index, context, trace, stack)
                status = "MATCHED" if matched else "IDLE"
            else:
                raise StatefulNestedCapabilityRuntimeError(
                    f"unsupported_runtime_spec_kind:{kind}"
                )
        finally:
            stack.pop()

        trace.append({
            "type": "CAPABILITY_EXIT", "capability_id": capability_id,
            "version": version, "matched": matched, "status": status,
        })
        return matched, status

    def _process_sequence(self, item, symbol, bar_index, context, trace, stack):
        spec = item.executable_spec
        steps = spec.get("steps") or []
        if not steps:
            raise StatefulNestedCapabilityRuntimeError("sequence_steps_required")

        key = f"{item.capability_id}@v{item.version}:{symbol}"
        state = self._states.get(key)
        if state is None:
            state = SequenceRuntimeState(item.capability_id, item.version, symbol)
            self._states[key] = state

        if state.last_bar is not None and bar_index < state.last_bar:
            raise StatefulNestedCapabilityRuntimeError("bar_index_moved_backwards")
        state.last_bar = bar_index

        if state.status in {SequenceRuntimeStatus.MATCHED, SequenceRuntimeStatus.EXPIRED}:
            state.reset()
            trace.append({"type": "AUTO_RESET", "state_key": key})

        max_between = spec.get("max_bars_between_steps")
        total = spec.get("total_expiration_bars")

        if (
            state.status == SequenceRuntimeStatus.ACTIVE
            and total is not None and state.started_bar is not None
            and bar_index - state.started_bar > int(total)
        ):
            state.status = SequenceRuntimeStatus.EXPIRED
            trace.append({"type": "EXPIRE", "reason": "TOTAL_EXPIRATION", "state_key": key})
            return False, "EXPIRED"

        if (
            state.status == SequenceRuntimeStatus.ACTIVE
            and max_between is not None and state.last_step_bar is not None
            and bar_index - state.last_step_bar > int(max_between)
        ):
            state.status = SequenceRuntimeStatus.EXPIRED
            trace.append({"type": "EXPIRE", "reason": "MAX_BARS_BETWEEN_STEPS", "state_key": key})
            return False, "EXPIRED"

        idx = state.current_step
        ref = str(steps[idx].get("primitive") or "")
        pin = self._dependency_version(spec, ref)
        ok = self._evaluate_reference(ref, pin, symbol, bar_index, context, trace, stack)

        trace.append({
            "type": "SEQUENCE_STEP", "state_key": key, "step": idx + 1,
            "reference": ref, "matched": ok,
        })
        if not ok:
            return False, state.status.value

        if state.status == SequenceRuntimeStatus.IDLE:
            state.status = SequenceRuntimeStatus.ACTIVE
            state.started_bar = bar_index
        state.current_step += 1
        state.last_step_bar = bar_index

        if state.current_step >= len(steps):
            state.status = SequenceRuntimeStatus.MATCHED
            trace.append({"type": "SEQUENCE_MATCHED", "state_key": key})
            return True, "MATCHED"
        return False, "ACTIVE"

    def _evaluate_stateless(self, spec, symbol, bar_index, context, trace, stack):
        kind = str(spec.get("kind") or "").upper()
        if kind == "PRIMITIVE":
            ref = str(spec.get("primitive") or "")
            return self._evaluate_reference(
                ref, self._dependency_version(spec, ref),
                symbol, bar_index, context, trace, stack
            )

        op = str(spec.get("logical_operator") or "").upper()
        values = []
        for child in spec.get("children") or []:
            ref = str(child.get("primitive") or "")
            values.append(self._evaluate_reference(
                ref, self._dependency_version(spec, ref),
                symbol, bar_index, context, trace, stack
            ))
        if op == "AND":
            return all(values)
        if op == "OR":
            return any(values)
        raise StatefulNestedCapabilityRuntimeError(
            f"unsupported_runtime_logical_operator:{op}"
        )

    def _evaluate_reference(self, ref, pin, symbol, bar_index, context, trace, stack):
        norm = self._norm(ref)
        handler = self.handlers.get(norm)
        if handler is not None:
            try:
                value = handler(context)
            except Exception as exc:
                raise StatefulNestedCapabilityRuntimeError(
                    f"primitive_handler_failed:{norm}:{exc}"
                ) from exc
            if type(value) is not bool:
                raise StatefulNestedCapabilityRuntimeError(
                    f"primitive_handler_must_return_bool:{norm}:{type(value).__name__}"
                )
            trace.append({"type": "PRIMITIVE", "primitive": norm, "matched": value})
            return value

        nested = self._resolve(ref, pin)
        trace.append({
            "type": "NESTED_CAPABILITY", "reference": ref,
            "resolved_capability_id": nested.capability_id, "version": nested.version,
        })
        matched, _ = self._process_capability(
            nested.capability_id, nested.version, symbol, bar_index,
            context, trace, stack,
        )
        return matched

    def export_state(self) -> dict[str, dict[str, Any]]:
        return {k: v.to_dict() for k, v in self._states.items()}

    def import_state(self, payload: dict[str, dict[str, Any]]) -> None:
        restored = {}
        for key, raw in payload.items():
            state = SequenceRuntimeState.from_dict(raw)
            if state.key() != key:
                raise StatefulNestedCapabilityRuntimeError(
                    f"runtime_state_key_mismatch:{key}"
                )
            restored[key] = state
        self._states = restored

    def _resolve(self, reference, version):
        try:
            report = self.gate.require_valid(reference, version=version)
            return self.registry.resolve(
                report.capability_id, version=report.version, require_enabled=True
            )
        except (CapabilityValidationError, CapabilityRegistryError) as exc:
            raise StatefulNestedCapabilityRuntimeError(
                f"stateful_nested_validation_failed:{exc}"
            ) from exc

    @staticmethod
    def _dependency_version(spec, reference):
        target = str(reference).strip()
        for dep in spec.get("dependencies") or []:
            if isinstance(dep, dict):
                ref = str(dep.get("reference") or dep.get("capability") or "").strip()
                if ref == target:
                    v = dep.get("version")
                    return None if v is None else int(v)
        return None

    @staticmethod
    def _norm(value):
        return "_".join(str(value or "").strip().upper().replace("-", " ").split())
