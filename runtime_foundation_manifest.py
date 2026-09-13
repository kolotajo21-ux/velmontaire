from __future__ import annotations

RUNTIME_FOUNDATION_VERSION = "1.0.0"
RUNTIME_FOUNDATION_MILESTONE = "80/80"
RUNTIME_FOUNDATION_STATUS = "FROZEN"
RUNTIME_FOUNDATION_NAME = "Runtime Foundation v1"

CRITICAL_FILES = ['core/compiler.py', 'core/concept_engine.py', 'core/context.py', 'core/detector.py', 'core/entry_signal.py', 'core/execution_adapter.py', 'core/execution_order.py', 'core/execution_state.py', 'core/interfaces.py', 'core/market_snapshot.py', 'core/module_loader.py', 'core/pipeline.py', 'core/poi_selector.py', 'core/registry.py', 'core/risk_plan.py', 'core/strategy.py', 'core/strategy_registry.py', 'core/trade_management_evaluator.py', 'core/trade_management_plan.py', 'core/validator.py', 'core/__init__.py', 'strategy_runtime/bound_position_management.py', 'strategy_runtime/condition_evaluator.py', 'strategy_runtime/execution_lifecycle.py', 'strategy_runtime/execution_lifecycle_sync.py', 'strategy_runtime/execution_position_binding.py', 'strategy_runtime/execution_request.py', 'strategy_runtime/executor.py', 'strategy_runtime/generic_live_runtime.py', 'strategy_runtime/generic_live_runtime_service.py', 'strategy_runtime/generic_runtime_startup.py', 'strategy_runtime/journaled_position_management_cycle.py', 'strategy_runtime/live_position_management_runtime.py', 'strategy_runtime/mt5_state_sync.py', 'strategy_runtime/persistent_position_management_cycle.py', 'strategy_runtime/position_management.py', 'strategy_runtime/position_management_cycle.py', 'strategy_runtime/position_management_execution.py', 'strategy_runtime/position_management_intent_recovery.py', 'strategy_runtime/position_management_journal.py', 'strategy_runtime/position_management_startup_gate.py', 'strategy_runtime/position_management_startup_recovery.py', 'strategy_runtime/position_management_state_store.py', 'strategy_runtime/position_reconciliation.py', 'strategy_runtime/production_live_runtime.py', 'strategy_runtime/recovery.py', 'strategy_runtime/submission_bridge.py', 'strategy_runtime/trade_plan.py', 'strategy_runtime/__init__.py', 'infrastructure/execution_journal.py', 'infrastructure/execution_journal_recovery.py', 'infrastructure/execution_lock.py', 'infrastructure/execution_retry_policy.py', 'infrastructure/journaled_execution_submitter.py', 'infrastructure/multi_symbol_runtime_state_context.py', 'infrastructure/production_safety_gate.py', 'infrastructure/runtime_execution_lifecycle.py', 'infrastructure/runtime_state_context.py', 'infrastructure/runtime_state_store.py', 'infrastructure/strategy_execution_journal.py', 'infrastructure/strategy_execution_lock.py', 'infrastructure/strategy_runtime_state_context.py', 'execution_adapters/mt5_execution.py', 'execution_adapters/mt5_position_reader.py', 'execution_adapters/mt5_execution_reader.py']

CRITICAL_IMPORTS = [
    "core.context",
    "core.execution_adapter",
    "core.execution_order",
    "core.strategy",
    "core.strategy_registry",
    "infrastructure.execution_journal",
    "infrastructure.execution_lock",
    "infrastructure.journaled_execution_submitter",
    "infrastructure.production_safety_gate",
    "strategy_runtime.execution_lifecycle",
    "strategy_runtime.position_reconciliation",
    "strategy_runtime.generic_runtime_startup",
    "strategy_runtime.generic_live_runtime",
    "strategy_runtime.generic_live_runtime_service",
    "strategy_runtime.production_live_runtime",
    "execution_adapters.mt5_execution",
    "execution_adapters.mt5_position_reader",
    "execution_adapters.mt5_execution_reader",
]