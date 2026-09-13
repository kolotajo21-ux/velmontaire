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


class CapabilityExecutionError(ValueError):
    """Fail-closed capability execution error."""


PrimitiveHandler = Callable[[dict[str, Any]], bool]


@dataclass(frozen=True, slots=True)
class CapabilityExecutionResult:
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


class CapabilityExecutionAdapter:
    """
    Executes only capabilities that pass Point 27 validation.

    Supported runtime specs:
    - PRIMITIVE
    - LOGICAL_GROUP / AND
    - LOGICAL_GROUP / OR
    - SEQUENCE

    Primitive handlers are injected runtime functions. Unknown or failing
    handlers block execution instead of being guessed.
    """

    def __init__(
        self,
        *,
        registry: CustomCapabilityRegistry,
        validation_gate: CapabilityValidationGate,
        primitive_handlers: Mapping[str, PrimitiveHandler],
    ) -> None:
        if not isinstance(registry, CustomCapabilityRegistry):
            raise CapabilityExecutionError(
                "custom_capability_registry_required"
            )
        if not isinstance(validation_gate, CapabilityValidationGate):
            raise CapabilityExecutionError(
                "capability_validation_gate_required"
            )

        self.registry = registry
        self.validation_gate = validation_gate
        self.handlers = {
            self._norm(name): handler
            for name, handler in primitive_handlers.items()
        }
        if not self.handlers:
            raise CapabilityExecutionError(
                "primitive_handlers_required"
            )
        for name, handler in self.handlers.items():
            if not callable(handler):
                raise CapabilityExecutionError(
                    f"primitive_handler_not_callable:{name}"
                )

    def execute(
        self,
        reference: str,
        context: dict[str, Any],
        *,
        version: int | None = None,
    ) -> CapabilityExecutionResult:
        if not isinstance(context, dict):
            raise CapabilityExecutionError(
                "execution_context_must_be_object"
            )

        try:
            report = self.validation_gate.require_valid(
                reference,
                version=version,
            )
            item = self.registry.resolve(
                report.capability_id,
                version=report.version,
                require_enabled=True,
            )
        except (
            CapabilityValidationError,
            CapabilityRegistryError,
        ) as exc:
            raise CapabilityExecutionError(
                f"execution_validation_failed:{exc}"
            ) from exc

        trace: list[dict[str, Any]] = []
        matched = self._execute_spec(
            item.executable_spec,
            context,
            trace,
        )

        return CapabilityExecutionResult(
            capability_id=item.capability_id,
            version=item.version,
            matched=matched,
            execution_trace=tuple(trace),
        )

    def _execute_spec(
        self,
        spec: dict[str, Any],
        context: dict[str, Any],
        trace: list[dict[str, Any]],
    ) -> bool:
        kind = str(spec.get("kind") or "").strip().upper()

        if kind == "PRIMITIVE":
            return self._execute_primitive(
                str(spec.get("primitive") or ""),
                context,
                trace,
            )

        if kind == "LOGICAL_GROUP":
            operator = str(
                spec.get("logical_operator") or ""
            ).strip().upper()
            children = spec.get("children") or []

            values: list[bool] = []
            for child in children:
                values.append(
                    self._execute_primitive(
                        str(child.get("primitive") or ""),
                        context,
                        trace,
                    )
                )

            if operator == "AND":
                matched = all(values)
            elif operator == "OR":
                matched = any(values)
            else:
                raise CapabilityExecutionError(
                    f"unsupported_runtime_logical_operator:{operator}"
                )

            trace.append({
                "type": "LOGICAL_GROUP",
                "operator": operator,
                "values": values,
                "matched": matched,
            })
            return matched

        if kind == "SEQUENCE":
            steps = spec.get("steps") or []
            for index, step in enumerate(steps, start=1):
                primitive = str(step.get("primitive") or "")
                matched = self._execute_primitive(
                    primitive,
                    context,
                    trace,
                )
                trace.append({
                    "type": "SEQUENCE_STEP",
                    "step": index,
                    "primitive": self._norm(primitive),
                    "matched": matched,
                })
                if not matched:
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

        raise CapabilityExecutionError(
            f"unsupported_runtime_spec_kind:{kind}"
        )

    def _execute_primitive(
        self,
        primitive: str,
        context: dict[str, Any],
        trace: list[dict[str, Any]],
    ) -> bool:
        name = self._norm(primitive)
        handler = self.handlers.get(name)
        if handler is None:
            raise CapabilityExecutionError(
                f"primitive_handler_missing:{name}"
            )

        try:
            result = handler(context)
        except Exception as exc:
            raise CapabilityExecutionError(
                f"primitive_handler_failed:{name}:{exc}"
            ) from exc

        if type(result) is not bool:
            raise CapabilityExecutionError(
                f"primitive_handler_must_return_bool:{name}:"
                f"{type(result).__name__}"
            )

        trace.append({
            "type": "PRIMITIVE",
            "primitive": name,
            "matched": result,
        })
        return result

    @staticmethod
    def _norm(value: str) -> str:
        return "_".join(
            str(value or "")
            .strip()
            .upper()
            .replace("-", " ")
            .split()
        )
