from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from .compiler import CompiledStrategy

@dataclass(slots=True)
class RuntimeBridgePayload:
    compilation_id: str
    strategy_id: str
    symbols: list[str]
    timeframes: list[str]
    execution_plan: dict[str, Any]
    def to_dict(self):
        return {"compilation_id":self.compilation_id,"strategy_id":self.strategy_id,"symbols":list(self.symbols),"timeframes":list(self.timeframes),"execution_plan":dict(self.execution_plan)}

class StrategyRuntimeBridge:
    def build_payload(self, compiled: CompiledStrategy) -> RuntimeBridgePayload:
        return RuntimeBridgePayload(
            compiled.compilation_id, compiled.strategy_id, list(compiled.symbols), list(compiled.timeframes),
            {"entries":list(compiled.entries),"stop_loss":compiled.stop_loss,"take_profit":compiled.take_profit,"risk":dict(compiled.risk),"management":list(compiled.management),"invalidation":compiled.invalidation,"module_bindings":[x.to_dict() for x in compiled.module_bindings]}
        )