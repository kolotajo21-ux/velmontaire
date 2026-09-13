from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from strategy_compiler.runtime_bridge import (
    RuntimeBridgePayload,
    StrategyRuntimeBridge,
)

from .ai_compilation_pipeline import (
    AICompilationPipelineResult,
)


@dataclass(slots=True)
class AIRuntimeBridgeResult:
    success: bool
    attempted: bool
    reason: str
    payload: RuntimeBridgePayload | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": bool(self.success),
            "attempted": bool(self.attempted),
            "reason": self.reason,
            "payload": (
                self.payload.to_dict()
                if self.payload is not None
                else None
            ),
            "diagnostics": dict(self.diagnostics),
        }


class AIStrategyRuntimeBridge:
    """
    Day 88 bridge:
        Day 87 READY compiled strategy
        -> existing StrategyRuntimeBridge
        -> RuntimeBridgePayload

    Safety:
    - non-READY AI compilation cannot reach runtime;
    - missing compiled strategy fails closed;
    - payload identity must match compiled identity;
    - no execution/broker call is performed here.
    """

    def __init__(
        self,
        *,
        runtime_bridge: StrategyRuntimeBridge | None = None,
    ) -> None:
        self.runtime_bridge = (
            runtime_bridge
            if runtime_bridge is not None
            else StrategyRuntimeBridge()
        )

    def build(
        self,
        result: AICompilationPipelineResult,
    ) -> AIRuntimeBridgeResult:
        if not result.ready:
            return AIRuntimeBridgeResult(
                success=False,
                attempted=False,
                reason="ai_compilation_pipeline_not_ready",
                diagnostics={
                    "runtime_bridge_called": False,
                    "execution_performed": False,
                    "broker_call_performed": False,
                },
            )

        compiled = result.compiled

        if compiled is None:
            return AIRuntimeBridgeResult(
                success=False,
                attempted=False,
                reason="compiled_strategy_missing",
                diagnostics={
                    "runtime_bridge_called": False,
                    "execution_performed": False,
                    "broker_call_performed": False,
                },
            )

        try:
            payload = self.runtime_bridge.build_payload(
                compiled
            )
        except Exception as exc:
            return AIRuntimeBridgeResult(
                success=False,
                attempted=True,
                reason="strategy_runtime_bridge_exception",
                diagnostics={
                    "runtime_bridge_called": True,
                    "execution_performed": False,
                    "broker_call_performed": False,
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                },
            )

        identity_error = self._verify_identity(
            compiled=compiled,
            payload=payload,
        )

        if identity_error is not None:
            return AIRuntimeBridgeResult(
                success=False,
                attempted=True,
                reason=identity_error,
                payload=None,
                diagnostics={
                    "runtime_bridge_called": True,
                    "execution_performed": False,
                    "broker_call_performed": False,
                    "payload_verified": False,
                },
            )

        execution_plan = getattr(
            payload,
            "execution_plan",
            None,
        )

        if not isinstance(
            execution_plan,
            dict,
        ):
            return AIRuntimeBridgeResult(
                success=False,
                attempted=True,
                reason="runtime_bridge_execution_plan_invalid",
                diagnostics={
                    "runtime_bridge_called": True,
                    "execution_performed": False,
                    "broker_call_performed": False,
                    "payload_verified": False,
                },
            )

        required_keys = {
            "entries",
            "stop_loss",
            "take_profit",
            "risk",
            "management",
            "invalidation",
            "module_bindings",
        }

        missing = sorted(
            required_keys
            - set(execution_plan)
        )

        if missing:
            return AIRuntimeBridgeResult(
                success=False,
                attempted=True,
                reason=(
                    "runtime_bridge_execution_plan_incomplete:"
                    + ",".join(missing)
                ),
                diagnostics={
                    "runtime_bridge_called": True,
                    "execution_performed": False,
                    "broker_call_performed": False,
                    "payload_verified": False,
                },
            )

        return AIRuntimeBridgeResult(
            success=True,
            attempted=True,
            reason="compiled_strategy_runtime_payload_ready",
            payload=payload,
            diagnostics={
                "runtime_bridge_called": True,
                "execution_performed": False,
                "broker_call_performed": False,
                "payload_verified": True,
                "module_binding_count": len(
                    execution_plan.get(
                        "module_bindings",
                        [],
                    )
                ),
            },
        )

    def require_payload(
        self,
        result: AIRuntimeBridgeResult,
    ) -> RuntimeBridgePayload:
        if not result.success or result.payload is None:
            raise ValueError(
                "ai_strategy_runtime_payload_not_ready"
            )

        return result.payload

    @staticmethod
    def _verify_identity(
        *,
        compiled: Any,
        payload: RuntimeBridgePayload,
    ) -> str | None:
        if (
            str(payload.compilation_id)
            != str(compiled.compilation_id)
        ):
            return "runtime_bridge_compilation_id_mismatch"

        if (
            str(payload.strategy_id)
            != str(compiled.strategy_id)
        ):
            return "runtime_bridge_strategy_id_mismatch"

        if list(payload.symbols) != list(
            compiled.symbols
        ):
            return "runtime_bridge_symbols_mismatch"

        if list(payload.timeframes) != list(
            compiled.timeframes
        ):
            return "runtime_bridge_timeframes_mismatch"

        return None