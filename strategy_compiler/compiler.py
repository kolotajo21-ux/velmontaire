from __future__ import annotations

import hashlib
import json
import re

from dataclasses import dataclass, field
from typing import Any

from core.strategy import ModuleRole
from core.strategy_registry import StrategyModuleRegistry

from strategy_schema import (
    ConditionKind,
    StrategyCondition,
    StrategySchema,
)


@dataclass(slots=True)
class CompiledCondition:
    node_id: str
    kind: str
    operation: str
    payload: dict[str, Any] = field(default_factory=dict)
    children: list["CompiledCondition"] = field(default_factory=list)

    def to_dict(self):
        return {
            "node_id": self.node_id,
            "kind": self.kind,
            "operation": self.operation,
            "payload": dict(self.payload),
            "children": [
                child.to_dict()
                for child in self.children
            ],
        }


@dataclass(slots=True)
class CompiledModuleBinding:
    role: str
    capability: str
    provider: str
    version: str

    def to_dict(self):
        return {
            "role": self.role,
            "capability": self.capability,
            "provider": self.provider,
            "version": self.version,
        }


@dataclass(slots=True)
class CompiledStrategy:
    compilation_id: str
    strategy_id: str
    schema_version: str
    symbols: list[str]
    timeframes: list[str]
    entries: list[dict[str, Any]]
    stop_loss: dict[str, Any] | None
    take_profit: dict[str, Any] | None
    risk: dict[str, Any]
    management: list[dict[str, Any]]
    invalidation: dict[str, Any] | None
    module_bindings: list[CompiledModuleBinding] = field(
        default_factory=list
    )
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self):
        return {
            "compilation_id": self.compilation_id,
            "strategy_id": self.strategy_id,
            "schema_version": self.schema_version,
            "symbols": list(self.symbols),
            "timeframes": list(self.timeframes),
            "entries": list(self.entries),
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "risk": dict(self.risk),
            "management": list(self.management),
            "invalidation": self.invalidation,
            "module_bindings": [
                item.to_dict()
                for item in self.module_bindings
            ],
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class StrategyCompilationResult:
    success: bool
    compiled: CompiledStrategy | None = None
    errors: list[str] = field(
        default_factory=list
    )

    def to_dict(self):
        return {
            "success": self.success,
            "compiled": (
                self.compiled.to_dict()
                if self.compiled
                else None
            ),
            "errors": list(self.errors),
        }


class StrategyCompiler:
    """
    Converts StrategySchema conditions into executable compiled
    conditions and binds every supported runtime EVENT to a real
    production module capability.

    Important:
    an EVENT must not reach runtime without a module binding.
    """

    EVENT_CAPABILITIES = {
        # ----------------------------------------------------------
        # Legacy / generic events
        # ----------------------------------------------------------
        "BOS": (
            ModuleRole.TREND,
            "bos_detection",
        ),
        "CHOCH": (
            ModuleRole.TREND,
            "choch_detection",
        ),
        "LIQUIDITY_SWEEP": (
            ModuleRole.LIQUIDITY,
            "liquidity_sweep",
        ),
        "FVG": (
            ModuleRole.POI,
            "fvg_detection",
        ),
        "ORDER_BLOCK": (
            ModuleRole.POI,
            "order_block_detection",
        ),

        # ----------------------------------------------------------
        # Production SMC events
        # ----------------------------------------------------------
        "DIRECTION_BIAS": (
            ModuleRole.TREND,
            "direction_bias",
        ),
        "MARKET_STRUCTURE": (
            ModuleRole.TREND,
            "market_structure",
        ),
        "POI_DETECTION": (
            ModuleRole.POI,
            "poi_detection",
        ),
        "FVG_DETECTION": (
            ModuleRole.POI,
            "fvg_detection",
        ),
        "M1_SCALPING_SETUP": (
            ModuleRole.ENTRY,
            "m1_scalping_setup",
        ),
        "H4_REJECTION_M15_SETUP": (
            ModuleRole.ENTRY,
            "h4_rejection_m15_setup",
        ),
        "NY_ASIA_SWEEP_M5_SETUP": (
            ModuleRole.ENTRY,
            "ny_asia_sweep_m5_setup",
        ),
        "ICT_NY_ASIA_SWEEP_M5_SETUP": (
            ModuleRole.ENTRY,
            "ict_ny_asia_sweep_m5_setup",
        ),
    }

    # Older user strategies and third-party modules may still expose the
    # pre-production capability names.  Production capabilities above are
    # always attempted first; these aliases only preserve compatibility when
    # no production provider exists in the registry.
    LEGACY_EVENT_CAPABILITY_FALLBACKS = {
        "BOS": ((ModuleRole.MARKET, "bos"),),
        "CHOCH": ((ModuleRole.MARKET, "choch"),),
        "FVG": ((ModuleRole.POI, "fvg"),),
        "ORDER_BLOCK": ((ModuleRole.POI, "order_block"),),
    }

    def __init__(
        self,
        registry: StrategyModuleRegistry,
    ) -> None:
        self.registry = registry

    def compile(
        self,
        schema: StrategySchema,
    ) -> StrategyCompilationResult:
        validation = schema.validate()

        if not validation.valid:
            return StrategyCompilationResult(
                False,
                errors=[
                    f"{issue.path}:{issue.code}"
                    for issue in validation.issues
                ],
            )

        contract_errors = self._validate_execution_contract(schema)
        if contract_errors:
            return StrategyCompilationResult(
                False,
                errors=contract_errors,
            )

        bindings: dict[
            tuple[str, str, str],
            CompiledModuleBinding,
        ] = {}

        entries: list[
            dict[str, Any]
        ] = []

        for idx, entry in enumerate(
            schema.rules.entries
        ):
            condition = self._compile_condition(
                entry.conditions,
                bindings,
            )

            if isinstance(
                condition,
                str,
            ):
                return StrategyCompilationResult(
                    False,
                    errors=[condition],
                )

            entries.append(
                {
                    "entry_index": idx,
                    "side": entry.side.value,
                    "order_type": (
                        entry.order_type.value
                    ),
                    "conditions": (
                        condition.to_dict()
                    ),
                    "entry_price": (
                        entry.entry_price.to_dict()
                        if entry.entry_price
                        else None
                    ),
                    "expiration_bars": (
                        entry.expiration_bars
                    ),
                    "allow_multiple_entries": (
                        entry.allow_multiple_entries
                    ),
                    "max_entries": (
                        entry.max_entries
                    ),
                    "metadata": dict(
                        entry.metadata
                    ),
                }
            )

        risk = schema.rules.risk

        sorted_bindings = list(
            sorted(
                bindings.values(),
                key=lambda item: (
                    item.role,
                    item.capability,
                    item.provider,
                ),
            )
        )

        payload = {
            "strategy_id": (
                schema.strategy_id
            ),
            "schema_version": (
                schema.schema_version
            ),
            "symbols": list(
                schema.symbols
            ),
            "timeframes": list(
                schema.timeframes
            ),
            "entries": entries,
            "stop_loss": (
                schema.rules.stop_loss.to_dict()
                if schema.rules.stop_loss
                else None
            ),
            "take_profit": (
                schema.rules.take_profit.to_dict()
                if schema.rules.take_profit
                else None
            ),
            "risk": risk.to_dict(),
            "management": [
                item.to_dict()
                for item
                in schema.rules.management
            ],
            "invalidation": (
                schema.rules.invalidation.to_dict()
                if schema.rules.invalidation
                else None
            ),
            "module_bindings": [
                item.to_dict()
                for item in sorted_bindings
            ],
        }

        digest = hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode()
        ).hexdigest()[:24]

        compiled = CompiledStrategy(
            compilation_id=(
                f"compiled_{digest}"
            ),
            strategy_id=(
                schema.strategy_id
            ),
            schema_version=(
                schema.schema_version
            ),
            symbols=list(
                schema.symbols
            ),
            timeframes=list(
                schema.timeframes
            ),
            entries=entries,
            stop_loss=(
                payload["stop_loss"]
            ),
            take_profit=(
                payload["take_profit"]
            ),
            risk=(
                payload["risk"]
            ),
            management=(
                payload["management"]
            ),
            invalidation=(
                payload["invalidation"]
            ),
            module_bindings=(
                sorted_bindings
            ),
            metadata={
                "source_schema_name": (
                    schema.name
                ),
                "source_schema_version": (
                    schema.version
                ),
                "compiler_version": (
                    "production_smc_bindings_v5_m1_immediate"
                    if schema.metadata.get("parser_version")
                    == "v5_m1_ifvg_fvg_immediate"
                    else "production_smc_bindings_v3_velmontaire"
                ),
                "source_schema_metadata": dict(schema.metadata),
            },
        )

        return StrategyCompilationResult(
            True,
            compiled=compiled,
        )

    @staticmethod
    def _validate_execution_contract(
        schema: StrategySchema,
    ) -> list[str]:
        """Fail closed when a declared production policy is incomplete."""
        errors: list[str] = []

        take_profit = schema.rules.take_profit
        if take_profit is not None:
            metadata = dict(take_profit.metadata or {})
            if metadata.get("target_policy") == "SESSION_LIQUIDITY":
                try:
                    minimum_r = float(metadata["minimum_r"])
                    base_r = float(metadata["base_r"])
                    maximum_r = float(metadata["maximum_r"])
                except (KeyError, TypeError, ValueError):
                    errors.append(
                        "take_profit:session_liquidity_rr_contract_missing"
                    )
                else:
                    if not (0 < minimum_r <= base_r <= maximum_r):
                        errors.append(
                            "take_profit:session_liquidity_rr_contract_invalid"
                        )
                    if maximum_r > 2.0:
                        errors.append(
                            "take_profit:maximum_r_above_velmontaire_limit"
                        )
                    if metadata.get("allow_above_base") is not False:
                        errors.append(
                            "take_profit:allow_above_base_must_be_false"
                        )
                    if not metadata.get("liquidity_sources"):
                        errors.append(
                            "take_profit:liquidity_sources_missing"
                        )

        risk = schema.rules.risk
        if risk is not None:
            metadata = dict(risk.metadata or {})
            daily = metadata.get("max_daily_loss_percent")
            weekly = metadata.get("max_weekly_loss_percent")
            if daily is not None or weekly is not None:
                try:
                    daily_value = float(daily)
                    weekly_value = float(weekly)
                except (TypeError, ValueError):
                    errors.append("risk:loss_limits_invalid")
                else:
                    if daily_value <= 0 or weekly_value <= 0:
                        errors.append("risk:loss_limits_must_be_positive")
                    if daily_value > weekly_value:
                        errors.append("risk:daily_limit_above_weekly_limit")
                if not metadata.get("loss_limit_timezone"):
                    errors.append("risk:loss_limit_timezone_missing")

        event_metadata: list[dict[str, Any]] = []

        def collect(condition: StrategyCondition) -> None:
            if condition.kind == ConditionKind.EVENT:
                event_metadata.append(dict(condition.metadata or {}))
            for child in condition.children:
                collect(child)
            for step in condition.sequence:
                collect(step)

        atr_entry_order_types: set[str] = set()
        for entry in schema.rules.entries:
            metadata_start = len(event_metadata)
            collect(entry.conditions)
            entry_event_metadata = event_metadata[metadata_start:]
            if any(
                item.get("atr_branch_required") is True
                for item in entry_event_metadata
            ):
                atr_entry_order_types.add(entry.order_type.value)

        dxy_rules = [
            item
            for item in event_metadata
            if item.get("dxy_context_required") is True
        ]
        for metadata in dxy_rules:
            if not str(metadata.get("dxy_symbol") or "").strip():
                errors.append("dxy:dxy_symbol_missing")
            if str(metadata.get("dxy_timeframe") or "").upper() != "H4":
                errors.append("dxy:dxy_timeframe_must_be_H4")
            if metadata.get("dxy_policy") != "NOT_CONTRADICT":
                errors.append("dxy:unsupported_policy")

        atr_rules = [
            item
            for item in event_metadata
            if item.get("atr_branch_required") is True
        ]
        if atr_rules:
            operators = {
                str(item.get("atr_operator") or "")
                for item in atr_rules
            }
            complete_market_limit_split = {"<", ">="}.issubset(operators)
            single_limit_branch = (
                operators == {">="}
                and atr_entry_order_types == {"LIMIT"}
                and len(schema.rules.entries) == 1
                and len(atr_rules) == 1
            )
            if not (complete_market_limit_split or single_limit_branch):
                errors.append("entry:atr_market_limit_branches_incomplete")

            for item in atr_rules:
                raw_minimum = item.get("atr_minimum_multiplier")
                if raw_minimum in {None, ""}:
                    continue
                try:
                    minimum = float(raw_minimum)
                    upper = float(item.get("atr_multiplier"))
                except (TypeError, ValueError):
                    errors.append("entry:atr_minimum_multiplier_invalid")
                    continue
                if minimum <= 0:
                    errors.append("entry:atr_minimum_multiplier_invalid")
                if (
                    str(item.get("atr_operator") or "") in {"<", "<="}
                    and minimum >= upper
                ):
                    errors.append("entry:atr_minimum_not_below_upper_threshold")

        return list(dict.fromkeys(errors))

    def _compile_condition(
        self,
        condition: StrategyCondition,
        bindings: dict[
            tuple[str, str, str],
            CompiledModuleBinding,
        ],
    ):
        # ==========================================================
        # EVENT
        # ==========================================================
        if (
            condition.kind
            == ConditionKind.EVENT
        ):
            event = str(
                condition.event_name
                or ""
            ).strip()

            if not event:
                return (
                    f"condition:"
                    f"{condition.condition_id}:"
                    f"event_missing"
                )

            canonical = (
                event
                .upper()
                .replace(" ", "_")
            )

            info = (
                self.EVENT_CAPABILITIES
                .get(canonical)
            )

            if info is None:
                normalized = self._normalize_legacy_composite_event(
                    condition,
                    canonical,
                )
                if normalized is not None:
                    return self._compile_condition(
                        normalized,
                        bindings,
                    )

                return (
                    f"condition:"
                    f"{condition.condition_id}:"
                    f"event_capability_mapping_missing:"
                    f"{canonical}"
                )

            role, capability = info
            matches = []

            capability_candidates = (
                (role, capability),
                *self.LEGACY_EVENT_CAPABILITY_FALLBACKS.get(
                    canonical,
                    (),
                ),
            )

            for candidate_role, candidate_capability in capability_candidates:
                candidate_matches = list(
                    self.registry.find_by_capability(
                        candidate_capability,
                        role=candidate_role,
                    )
                )
                if candidate_matches:
                    role = candidate_role
                    capability = candidate_capability
                    matches = candidate_matches
                    break

            if not matches:
                return (
                    "module_capability_missing:"
                    f"{role.value}:"
                    f"{capability}"
                )

            # ------------------------------------------------------
            # Prefer explicit provider_hint supplied by parser.
            # ------------------------------------------------------
            metadata = dict(
                condition.metadata
                or {}
            )

            provider_hint = str(
                metadata.get(
                    "provider_hint",
                    "",
                )
                or ""
            ).strip().lower()

            selected = None

            if provider_hint:
                hinted_matches = [
                    match
                    for match in matches
                    if str(
                        match.provider
                    ).strip().lower()
                    == provider_hint
                ]

                if hinted_matches:
                    selected = sorted(
                        hinted_matches,
                        key=lambda match: (
                            str(
                                match.provider
                            ).lower(),
                            str(
                                match.version
                            ),
                        ),
                    )[0]
                else:
                    return (
                        "module_provider_hint_missing:"
                        f"{role.value}:"
                        f"{capability}:"
                        f"{provider_hint}"
                    )

            # ------------------------------------------------------
            # No explicit provider:
            # choose deterministically instead of registry order.
            # ------------------------------------------------------
            if selected is None:
                selected = sorted(
                    matches,
                    key=lambda match: (
                        str(
                            match.provider
                        ).lower(),
                        str(
                            match.version
                        ),
                    ),
                )[0]

            # Binding identity includes provider. Multiple providers may
            # implement the same capability (e.g. POI detection), and they
            # must not overwrite each other in the compiled strategy.
            binding_key = (
                role.value,
                capability,
                str(selected.provider).strip().lower(),
            )

            bindings[binding_key] = CompiledModuleBinding(
                role=role.value,
                capability=capability,
                provider=selected.provider,
                version=selected.version,
            )

            return CompiledCondition(
                node_id=(
                    condition.condition_id
                ),
                kind=(
                    condition.kind.value
                ),
                operation="EVENT",
                payload={
                    "event_name": canonical,
                    "capability": capability,
                    "module_role": role.value,
                    "provider": selected.provider,
                    "description": (
                        condition.description
                    ),
                    "metadata": metadata,
                },
            )

        # ==========================================================
        # LOGICAL GROUP
        # ==========================================================
        if (
            condition.kind
            == ConditionKind.LOGICAL_GROUP
        ):
            if (
                condition.logical_operator
                is None
            ):
                return (
                    f"condition:"
                    f"{condition.condition_id}:"
                    f"logical_operator_missing"
                )

            children = []

            for child in (
                condition.children
            ):
                compiled_child = (
                    self._compile_condition(
                        child,
                        bindings,
                    )
                )

                if isinstance(
                    compiled_child,
                    str,
                ):
                    return compiled_child

                children.append(
                    compiled_child
                )

            return CompiledCondition(
                node_id=(
                    condition.condition_id
                ),
                kind=(
                    condition.kind.value
                ),
                operation=(
                    condition
                    .logical_operator
                    .value
                ),
                payload={
                    "description": (
                        condition.description
                    ),
                },
                children=children,
            )

        # ==========================================================
        # SEQUENCE
        # ==========================================================
        if (
            condition.kind
            == ConditionKind.SEQUENCE
        ):
            children = []

            for step in (
                condition.sequence
            ):
                compiled_step = (
                    self._compile_condition(
                        step,
                        bindings,
                    )
                )

                if isinstance(
                    compiled_step,
                    str,
                ):
                    return compiled_step

                children.append(
                    compiled_step
                )

            return CompiledCondition(
                node_id=(
                    condition.condition_id
                ),
                kind=(
                    condition.kind.value
                ),
                operation="SEQUENCE",
                payload={
                    "max_bars_between_steps": (
                        condition
                        .max_bars_between_steps
                    ),
                    "description": (
                        condition.description
                    ),
                },
                children=children,
            )

        # ==========================================================
        # COMPARISON
        # ==========================================================
        if (
            condition.kind
            == ConditionKind.COMPARISON
        ):
            return CompiledCondition(
                node_id=(
                    condition.condition_id
                ),
                kind=(
                    condition.kind.value
                ),
                operation="COMPARISON",
                payload={
                    "left": (
                        condition.left.to_dict()
                        if condition.left
                        else None
                    ),
                    "operator": (
                        condition.operator.value
                        if condition.operator
                        else None
                    ),
                    "right": (
                        condition.right.to_dict()
                        if condition.right
                        else None
                    ),
                    "description": (
                        condition.description
                    ),
                },
            )

        return (
            f"condition:"
            f"{condition.condition_id}:"
            f"unsupported_kind"
        )

    @staticmethod
    def _normalize_legacy_composite_event(
        condition: StrategyCondition,
        canonical: str,
    ) -> StrategyCondition | None:
        """Recover old parser output that stored CHOCH + OB as one EVENT."""
        if not (
            "CHOCH" in canonical
            and "ORDER_BLOCK" in canonical
        ):
            return None

        timeframe_match = re.search(
            r"(?:^|_)(M1|M5|M15|M30|H1|H4|D1|W1)(?:_|[.]|$)",
            canonical,
        )
        timeframe = timeframe_match.group(1) if timeframe_match else None

        direction = None
        if "BULLISH" in canonical:
            direction = "BULLISH"
        elif "BEARISH" in canonical:
            direction = "BEARISH"

        base_metadata = dict(condition.metadata or {})
        shared_metadata = {
            key: value
            for key, value in {
                "timeframe": timeframe,
                "direction": direction,
                "compiler_normalized_legacy_composite_event": True,
            }.items()
            if value is not None
        }

        choch_metadata = {
            **base_metadata,
            **shared_metadata,
            "provider_hint": "structure_trend",
            "semantic_event": "CHOCH_CONFIRMED",
        }
        order_block_metadata = {
            **base_metadata,
            **shared_metadata,
            "provider_hint": "order_block_poi",
            "semantic_event": "FIRST_ORDER_BLOCK_MITIGATION",
            "first_mitigation_required": "FIRST_MITIGATION" in canonical,
        }

        return StrategyCondition(
            condition_id=f"{condition.condition_id}_normalized_sequence",
            kind=ConditionKind.SEQUENCE,
            sequence=[
                StrategyCondition(
                    condition_id=f"{condition.condition_id}_choch",
                    kind=ConditionKind.EVENT,
                    event_name="CHOCH",
                    description="CHOCH extracted from legacy composite EVENT.",
                    metadata=choch_metadata,
                ),
                StrategyCondition(
                    condition_id=f"{condition.condition_id}_order_block",
                    kind=ConditionKind.EVENT,
                    event_name="ORDER_BLOCK",
                    description=(
                        "Order Block mitigation extracted from legacy "
                        "composite EVENT."
                    ),
                    metadata=order_block_metadata,
                ),
            ],
            description=condition.description or canonical,
            metadata={
                **base_metadata,
                **shared_metadata,
                "source_event": canonical,
            },
        )
