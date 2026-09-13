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


class NestedCapabilityExecutionError(ValueError):
    """Fail-closed nested capability runtime error."""


PrimitiveHandler = Callable[[dict[str, Any]], bool]


@dataclass(frozen=True, slots=True)
class NestedCapabilityExecutionResult:
    capability_id: str
    version: int
    matched: bool
    execution_trace: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "version": self.version,
            "matched": self.matched,
            "execution_trace": [
                dict(item) for item in self.execution_trace
            ],
        }


class NestedCapabilityRuntime:
    """
    Executes capabilities recursively.

    A primitive reference may resolve either to:
    - a real primitive handler; or
    - another registered capability.

    Explicit dependency declarations can pin nested capability versions.
    Recursion cycles are blocked at runtime as a second safety layer.
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

    def execute(
        self,
        reference: str,
        context: dict[str, Any],
        *,
        version: int | None = None,
    ) -> NestedCapabilityExecutionResult:
        if not isinstance(context, dict):
            raise NestedCapabilityExecutionError(
                "execution_context_must_be_object"
            )

        trace: list[dict[str, Any]] = []
        stack: list[str] = []
        item = self._resolve_valid(reference, version)
        matched = self._execute_capability(
            item.capability_id,
            item.version,
            context,
            trace,
            stack,
        )

        return NestedCapabilityExecutionResult(
            capability_id=item.capability_id,
            version=item.version,
            matched=matched,
            execution_trace=tuple(trace),
        )

    def _execute_capability(
        self,
        capability_id: str,
        version: int,
        context: dict[str, Any],
        trace: list[dict[str, Any]],
        stack: list[str],
    ) -> bool:
        key = f"{capability_id}@v{version}"
        if key in stack:
            cycle = stack[stack.index(key):] + [key]
            raise NestedCapabilityExecutionError(
                "runtime_capability_cycle:" + "->".join(cycle)
            )

        item = self._resolve_valid(capability_id, version)
        stack.append(key)
        trace.append({
            "type": "CAPABILITY_ENTER",
            "capability_id": capability_id,
            "version": version,
            "name": item.name,
        })

        try:
            matched = self._execute_spec(
                item.executable_spec,
                context,
                trace,
                stack,
            )
        finally:
            stack.pop()

        trace.append({
            "type": "CAPABILITY_EXIT",
            "capability_id": capability_id,
            "version": version,
            "matched": matched,
        })
        return matched

    def _execute_spec(
        self,
        spec: dict[str, Any],
        context: dict[str, Any],
        trace: list[dict[str, Any]],
        stack: list[str],
    ) -> bool:
        kind = str(spec.get("kind") or "").upper()

        if kind == "PRIMITIVE":
            return self._execute_reference(
                str(spec.get("primitive") or ""),
                context,
                trace,
                stack,
                self._dependency_version(
                    spec,
                    str(spec.get("primitive") or ""),
                ),
            )

        if kind == "LOGICAL_GROUP":
            op = str(spec.get("logical_operator") or "").upper()
            values = []
            for child in spec.get("children") or []:
                ref = str(child.get("primitive") or "")
                values.append(
                    self._execute_reference(
                        ref,
                        context,
                        trace,
                        stack,
                        self._dependency_version(spec, ref),
                    )
                )
            if op == "AND":
                matched = all(values)
            elif op == "OR":
                matched = any(values)
            else:
                raise NestedCapabilityExecutionError(
                    f"unsupported_runtime_logical_operator:{op}"
                )
            trace.append({
                "type": "LOGICAL_GROUP",
                "operator": op,
                "values": values,
                "matched": matched,
            })
            return matched

        if kind == "SEQUENCE":
            steps = spec.get("steps") or []
            for index, step in enumerate(steps, 1):
                ref = str(step.get("primitive") or "")
                ok = self._execute_reference(
                    ref,
                    context,
                    trace,
                    stack,
                    self._dependency_version(spec, ref),
                )
                trace.append({
                    "type": "SEQUENCE_STEP",
                    "step": index,
                    "reference": ref,
                    "matched": ok,
                })
                if not ok:
                    trace.append({
                        "type": "SEQUENCE",
                        "matched": False,
                        "failed_step": index,
                    })
                    return False
            trace.append({
                "type": "SEQUENCE",
                "matched": True,
                "completed_steps": len(steps),
            })
            return True

        raise NestedCapabilityExecutionError(
            f"unsupported_runtime_spec_kind:{kind}"
        )

    def _execute_reference(
        self,
        reference: str,
        context: dict[str, Any],
        trace: list[dict[str, Any]],
        stack: list[str],
        pinned_version: int | None,
    ) -> bool:
        norm = self._norm(reference)
        handler = self.handlers.get(norm)

        if handler is not None:
            try:
                value = handler(context)
            except Exception as exc:
                raise NestedCapabilityExecutionError(
                    f"primitive_handler_failed:{norm}:{exc}"
                ) from exc
            if type(value) is not bool:
                raise NestedCapabilityExecutionError(
                    f"primitive_handler_must_return_bool:"
                    f"{norm}:{type(value).__name__}"
                )
            trace.append({
                "type": "PRIMITIVE",
                "primitive": norm,
                "matched": value,
            })
            return value

        try:
            nested = self.registry.resolve(
                reference,
                version=pinned_version,
                require_enabled=True,
            )
        except CapabilityRegistryError as exc:
            raise NestedCapabilityExecutionError(
                f"runtime_reference_unresolved:{reference}:{exc}"
            ) from exc

        trace.append({
            "type": "NESTED_CAPABILITY",
            "reference": reference,
            "resolved_capability_id": nested.capability_id,
            "version": nested.version,
        })
        return self._execute_capability(
            nested.capability_id,
            nested.version,
            context,
            trace,
            stack,
        )

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
            raise NestedCapabilityExecutionError(
                f"nested_execution_validation_failed:{exc}"
            ) from exc

    @staticmethod
    def _dependency_version(
        spec: dict[str, Any],
        reference: str,
    ) -> int | None:
        target = str(reference).strip()
        target_norm = NestedCapabilityRuntime._norm(target)
        for raw in spec.get("dependencies") or []:
            if isinstance(raw, str):
                continue
            if not isinstance(raw, dict):
                continue
            dep_ref = str(
                raw.get("reference")
                or raw.get("capability")
                or ""
            ).strip()
            if (
                dep_ref == target
                or NestedCapabilityRuntime._norm(dep_ref) == target_norm
            ):
                version = raw.get("version")
                return None if version is None else int(version)
        return None

    @staticmethod
    def _norm(value: str) -> str:
        return "_".join(
            str(value or "")
            .strip()
            .upper()
            .replace("-", " ")
            .split()
        )
