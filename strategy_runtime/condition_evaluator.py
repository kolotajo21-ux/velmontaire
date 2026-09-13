from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.context import StrategyContext
from core.strategy import ModuleRole, StrategyModuleDefinition
from core.strategy_registry import StrategyModuleRegistry
from strategy_compiler import CompiledCondition, CompiledStrategy


@dataclass(slots=True)
class ConditionEvaluationResult:
    success: bool
    passed: bool
    reason: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": bool(self.success),
            "passed": bool(self.passed),
            "reason": self.reason,
            "diagnostics": dict(self.diagnostics),
        }


class GenericConditionEvaluator:
    """
    Day 52 generic condition evaluator.

    Supports:
    - EVENT
    - AND / OR / NOT
    - SEQUENCE with persistent progress in StrategyContext.state
    - basic COMPARISON value references

    Unknown events/value sources fail closed.
    """

    def __init__(
        self,
        *,
        registry: StrategyModuleRegistry,
        compiled: CompiledStrategy,
    ) -> None:
        self.registry = registry
        self.compiled = compiled

        self._bindings = {
            self._capability_key(binding.capability): binding
            for binding in compiled.module_bindings
        }

        self._instances: dict[
            tuple[str, str],
            Any,
        ] = {}

    def evaluate(
        self,
        condition: dict[str, Any] | CompiledCondition,
        context: StrategyContext,
    ) -> ConditionEvaluationResult:
        node = (
            condition.to_dict()
            if isinstance(condition, CompiledCondition)
            else dict(condition)
        )

        operation = str(
            node.get("operation", "")
        ).upper()

        if operation == "EVENT":
            return self._evaluate_event(
                node,
                context,
            )

        if operation == "AND":
            return self._evaluate_and(
                node,
                context,
            )

        if operation == "OR":
            return self._evaluate_or(
                node,
                context,
            )

        if operation == "NOT":
            return self._evaluate_not(
                node,
                context,
            )

        if operation == "SEQUENCE":
            return self._evaluate_sequence(
                node,
                context,
            )

        if operation == "COMPARISON":
            return self._evaluate_comparison(
                node,
                context,
            )

        return ConditionEvaluationResult(
            success=False,
            passed=False,
            reason=(
                "unsupported_condition_operation:"
                f"{operation or 'EMPTY'}"
            ),
        )

    def _evaluate_event(
        self,
        node: dict[str, Any],
        context: StrategyContext,
    ) -> ConditionEvaluationResult:
        payload = dict(
            node.get("payload") or {}
        )

        payload = self._ensure_event_timeframe(
            payload=payload,
            context=context,
        )

        event_name = str(
            payload.get("event_name", "")
        ).strip().upper()

        if not event_name:
            return ConditionEvaluationResult(
                False,
                False,
                "event_name_missing",
            )

        # Compiler bindings use production capability names such as
        # choch_detection/order_block_detection, which are intentionally not
        # identical to user-facing EVENT names.  Prefer the exact capability
        # persisted by the compiler and fall back to the legacy event name.
        capability = self._capability_key(
            payload.get("capability")
            or event_name
        )

        alternative_poi = self._evaluate_alternative_poi_event(
            event_name=event_name,
            capability=capability,
            payload=payload,
            context=context,
        )

        if alternative_poi is not None:
            return alternative_poi

        binding = self._select_event_binding(
            capability=capability,
            payload=payload,
        )

        if binding is None:
            return ConditionEvaluationResult(
                False,
                False,
                (
                    "event_module_binding_missing:"
                    f"{event_name}"
                ),
            )

        try:
            role = ModuleRole(
                binding.role
            )
        except ValueError:
            return ConditionEvaluationResult(
                False,
                False,
                (
                    "invalid_module_role:"
                    f"{binding.role}"
                ),
            )

        definition = StrategyModuleDefinition(
            role=role,
            provider=binding.provider,
            enabled=True,
            required=True,
            parameters={
                "capability": (
                    binding.capability
                ),
                "event_name": event_name,
                "event_metadata": dict(
                    payload.get("metadata") or {}
                ),
            },
            metadata={
                "compiled_strategy_id": (
                    self.compiled.strategy_id
                ),
                "compilation_id": (
                    self.compiled.compilation_id
                ),
                **dict(
                    payload.get("metadata") or {}
                ),
            },
        )

        key = (
            role.value,
            binding.provider.lower(),
        )

        module = self._instances.get(
            key
        )

        if module is None:
            try:
                module = self.registry.create(
                    definition
                )
            except Exception as exc:
                return ConditionEvaluationResult(
                    False,
                    False,
                    (
                        "module_create_failed:"
                        f"{type(exc).__name__}:{exc}"
                    ),
                )

            self._instances[key] = module

        self._apply_event_runtime_hints(
            module=module,
            payload=payload,
        )

        dependency_result = self._ensure_module_dependencies(
            module=module,
            context=context,
            stack=set(),
            runtime_payload=payload,
        )

        if dependency_result is not None:
            return dependency_result

        result = module.run(
            context
        )

        context.set_result(
            result
        )

        self._record_event_result(
            context=context,
            payload=payload,
            event_name=event_name,
            provider=binding.provider,
            role=role,
            result=result,
        )

        # ATR entry routing belongs to the exact FVG/IFVG that the module
        # selected.  Evaluating it before the module made the comparison use
        # the current tap candle, so a large-displacement LIMIT setup could
        # later be misclassified as MARKET.  Run the contract only after a
        # successful event and bind it to that event's active zone.
        if result.success and result.passed:
            atr_branch = self._evaluate_atr_branch(
                payload=payload,
                context=context,
                result=result,
            )

            if atr_branch is not None:
                if (
                    not atr_branch.success
                    or not atr_branch.passed
                ):
                    return atr_branch

        direction_contract = self._evaluate_direction_contract(
            payload=payload,
            event_name=event_name,
            module=module,
            result=result,
            context=context,
        )
        if direction_contract is not None:
            return direction_contract

        if not result.success:
            return ConditionEvaluationResult(
                success=False,
                passed=False,
                reason=(
                    result.error
                    or "module_execution_failed"
                ),
                diagnostics={
                    "role": role.value,
                    "provider": binding.provider,
                    "event_name": event_name,
                },
            )

        module_diagnostics = dict(
            result.diagnostics or {}
        )

        if result.passed:
            event_reason = "event_passed"
        else:
            rejection_reason = str(
                module_diagnostics.get(
                    "rejection_reason",
                    "",
                )
                or module_diagnostics.get(
                    "reason",
                    "",
                )
                or ""
            ).strip()

            event_reason = (
                "event_not_passed:"
                f"provider={binding.provider}"
            )

            if rejection_reason:
                event_reason += (
                    ":rejection_reason="
                    f"{rejection_reason}"
                )

            # Compact runtime trace for event-local failures.
            # This is intentionally encoded into `reason` because the
            # historical runner aggregates only runtime.reason counters.
            trace_parts: list[str] = []

            for trace_key in (
                "poi_found",
                "candidate_count",
                "selected_timeframe",
                "timeframe",
                "direction",
                "event_count",
            ):
                trace_value = module_diagnostics.get(
                    trace_key
                )

                if trace_value is None:
                    continue

                if isinstance(
                    trace_value,
                    (dict, list, tuple, set),
                ):
                    continue

                trace_parts.append(
                    f"{trace_key}={trace_value}"
                )

            attempts = module_diagnostics.get(
                "timeframe_attempts"
            )

            if isinstance(attempts, list):
                attempt_parts: list[str] = []

                for attempt in attempts[:4]:
                    if not isinstance(
                        attempt,
                        dict,
                    ):
                        continue

                    attempt_tf = str(
                        attempt.get("timeframe")
                        or "?"
                    )

                    attempt_found = attempt.get(
                        "poi_found"
                    )

                    attempt_reason = (
                        attempt.get(
                            "rejection_reason"
                        )
                        or (
                            attempt.get(
                                "diagnostics",
                                {}
                            ).get(
                                "rejection_reason"
                            )
                            if isinstance(
                                attempt.get(
                                    "diagnostics"
                                ),
                                dict,
                            )
                            else None
                        )
                        or "not_passed"
                    )

                    attempt_parts.append(
                        (
                            f"{attempt_tf}:"
                            f"poi_found={attempt_found}:"
                            f"reason={attempt_reason}"
                        )
                    )

                if attempt_parts:
                    trace_parts.append(
                        "attempts="
                        + "|".join(
                            attempt_parts
                        )
                    )

            if trace_parts:
                event_reason += (
                    ":trace="
                    + ",".join(
                        trace_parts
                    )
                )

        return ConditionEvaluationResult(
            success=True,
            passed=bool(
                result.passed
            ),
            reason=event_reason,
            diagnostics={
                "role": role.value,
                "provider": binding.provider,
                "event_name": event_name,
                "module_data": dict(
                    result.data
                ),
                "module_diagnostics": (
                    module_diagnostics
                ),
            },
        )

    @staticmethod
    def _result_direction(result: Any) -> str:
        data = dict(getattr(result, "data", None) or {})
        diagnostics = dict(getattr(result, "diagnostics", None) or {})
        for value in (
            data.get("direction"),
            data.get("bias"),
            data.get("trend"),
            diagnostics.get("direction"),
            diagnostics.get("bias"),
            diagnostics.get("trend"),
        ):
            normalized = str(value or "").strip().upper()
            if normalized in {"BULLISH", "BEARISH", "NEUTRAL"}:
                return normalized
        return "NEUTRAL"

    def _evaluate_direction_contract(
        self,
        *,
        payload: dict[str, Any],
        event_name: str,
        module: Any,
        result: Any,
        context: StrategyContext,
    ) -> ConditionEvaluationResult | None:
        """Enforce H4 direction and DXY confirmation, never as an entry."""
        if not getattr(result, "success", False):
            return None

        metadata = dict(payload.get("metadata") or {})
        direction = self._result_direction(result)

        if (
            metadata.get("first_tap_required") is True
            and getattr(result, "passed", False)
        ):
            data = dict(getattr(result, "data", None) or {})
            zone = data.get("active_zone")
            if not isinstance(zone, dict):
                return ConditionEvaluationResult(
                    True,
                    False,
                    "first_tap_waiting:active_fvg_missing",
                )
            raw_first_touch_time = zone.get("first_touch_time")
            try:
                first_touch_time = (
                    int(raw_first_touch_time)
                    if raw_first_touch_time is not None
                    else None
                )
                touch_count = int(zone.get("touch_count", 0))
            except (TypeError, ValueError, OverflowError):
                return ConditionEvaluationResult(
                    True,
                    False,
                    "first_tap_waiting:touch_metadata_missing",
                )

            current_time = int(context.current_time)
            semantic_event = str(
                metadata.get("semantic_event") or ""
            ).strip().upper()

            if semantic_event == "FVG_IFVG_CONFIRMATION":
                try:
                    zone_end_time = int(zone.get("end_time"))
                except (TypeError, ValueError, OverflowError):
                    return ConditionEvaluationResult(
                        True,
                        False,
                        "pending_limit_waiting:fvg_end_time_missing",
                    )

                if zone_end_time != current_time:
                    return ConditionEvaluationResult(
                        True,
                        False,
                        "pending_limit_waiting:"
                        f"zone_end_time={zone_end_time}:"
                        f"current_time={current_time}",
                    )

                if first_touch_time is not None or touch_count != 0:
                    return ConditionEvaluationResult(
                        True,
                        False,
                        "pending_limit_waiting:"
                        f"fresh_zone_required:first_touch_time={first_touch_time}:"
                        f"touch_count={touch_count}",
                    )

                try:
                    zone_low = float(zone.get("low"))
                    zone_high = float(zone.get("high"))
                except (TypeError, ValueError, OverflowError):
                    return ConditionEvaluationResult(
                        True,
                        False,
                        "pending_limit_waiting:zone_bounds_missing",
                    )

                if (
                    zone_low <= 0
                    or zone_high <= 0
                    or zone_high <= zone_low
                ):
                    return ConditionEvaluationResult(
                        True,
                        False,
                        "pending_limit_waiting:zone_bounds_invalid",
                    )

                zone_event_type = str(
                    zone.get("event_type") or "FVG"
                ).strip().upper()
                if zone_event_type != "FVG":
                    return ConditionEvaluationResult(
                        True,
                        False,
                        "pending_limit_waiting:entry_zone_must_be_FVG:"
                        f"event_type={zone_event_type}",
                    )

                zone_status = str(
                    zone.get("status") or "FRESH"
                ).strip().upper()
                zone_active = bool(zone.get("active", True))
                if (
                    not zone_active
                    or zone_status in {"INVALIDATED", "MITIGATED"}
                ):
                    return ConditionEvaluationResult(
                        True,
                        False,
                        "pending_limit_waiting:entry_zone_inactive:"
                        f"status={zone_status}:active={zone_active}",
                    )

                zone_direction = str(
                    zone.get("zone_type")
                    or zone.get("direction")
                    or direction
                    or ""
                ).strip().upper()
                if zone_direction not in {"BULLISH", "BEARISH"}:
                    return ConditionEvaluationResult(
                        True,
                        False,
                        "pending_limit_waiting:zone_direction_missing",
                    )

                context.state["pending_limit_contract"] = {
                    "zone_id": zone.get("zone_id"),
                    "zone_low": zone_low,
                    "zone_high": zone_high,
                    "zone_direction": zone_direction,
                    "zone_event_type": zone_event_type,
                    "zone_status": zone_status,
                    "zone_active": zone_active,
                    "entry_price": (
                        zone_high
                        if zone_direction == "BULLISH"
                        else zone_low
                    ),
                    "invalidation_price": (
                        zone_low
                        if zone_direction == "BULLISH"
                        else zone_high
                    ),
                    "setup_time": current_time,
                    "zone_end_time": zone_end_time,
                    "timeframe": str(
                        metadata.get("timeframe") or "M15"
                    ).strip().upper(),
                    "activation_policy": "NEXT_EXECUTION_BAR",
                    "tap_policy": "FIRST_FUTURE_TAP",
                    "detector_touch_time": first_touch_time,
                    "detector_touch_count": touch_count,
                }

                # The setup is ready now; the historical runner owns the
                # pending order and may fill it only on a future bar.
                h4_direction = str(
                    context.state.get("h4_direction") or ""
                ).strip().upper()
                if (
                    h4_direction in {"BULLISH", "BEARISH"}
                    and direction in {"BULLISH", "BEARISH"}
                    and direction != h4_direction
                ):
                    return ConditionEvaluationResult(
                        True,
                        False,
                        "event_direction_contradicts_h4:"
                        f"event={event_name}:h4={h4_direction}:"
                        f"event_direction={direction}",
                    )
                return None

            # FVGDetector intentionally analyzes through the previous closed
            # candle. FVGPOIModule then validates interaction with the current
            # just-closed candle. In that normal closed-bar path, a genuine
            # first tap is represented by no historical touch yet (None/0),
            # while result.passed proves that the current candle touched it.
            # Keep compatibility with detectors that already count the
            # current closed candle as (current_time/1).
            current_tap_not_counted_yet = (
                first_touch_time is None
                and touch_count == 0
            )
            current_tap_already_counted = (
                first_touch_time == current_time
                and touch_count == 1
            )

            if not (
                current_tap_not_counted_yet
                or current_tap_already_counted
            ):
                return ConditionEvaluationResult(
                    True,
                    False,
                    "first_tap_waiting:"
                    f"first_touch_time={first_touch_time}:"
                    f"current_time={current_time}:touch_count={touch_count}",
                )

            context.state["first_tap_contract"] = {
                "zone_id": zone.get("zone_id"),
                "current_time": current_time,
                "detector_touch_time": first_touch_time,
                "detector_touch_count": touch_count,
                "mode": (
                    "CURRENT_CLOSED_BAR_PENDING_COUNT"
                    if current_tap_not_counted_yet
                    else "CURRENT_CLOSED_BAR_ALREADY_COUNTED"
                ),
            }

        if event_name == "DIRECTION_BIAS":
            if getattr(result, "passed", False) and direction in {
                "BULLISH",
                "BEARISH",
            }:
                context.state["h4_direction"] = direction

            if metadata.get("dxy_context_required") is not True:
                return None

            symbol = str(context.symbol or "").strip().upper()
            if "USD" not in symbol:
                context.state["dxy_context"] = {
                    "required": False,
                    "reason": "NON_USD_SYMBOL",
                }
                return None

            dxy_symbol = str(metadata.get("dxy_symbol") or "").strip().upper()
            dxy_timeframe = str(
                metadata.get("dxy_timeframe") or "H4"
            ).strip().upper()
            dxy_rates = context.get_symbol_rates(dxy_symbol, dxy_timeframe)
            rates_missing = dxy_rates is None
            if hasattr(dxy_rates, "empty"):
                rates_missing = bool(dxy_rates.empty)
            else:
                try:
                    rates_missing = len(dxy_rates) == 0
                except TypeError:
                    rates_missing = True

            if rates_missing:
                return ConditionEvaluationResult(
                    False,
                    False,
                    f"dxy_rates_missing:symbol={dxy_symbol}:timeframe={dxy_timeframe}",
                )

            dxy_context = StrategyContext(
                strategy=context.strategy,
                symbol=dxy_symbol,
                current_time=context.current_time,
                rates_by_timeframe={dxy_timeframe: dxy_rates},
                market=dict(context.market_by_symbol.get(dxy_symbol) or {}),
            )
            dxy_result = module.run(dxy_context)
            if not dxy_result.success:
                return ConditionEvaluationResult(
                    False,
                    False,
                    "dxy_context_evaluation_failed:"
                    + str(dxy_result.error or "module_failed"),
                )

            dxy_direction = self._result_direction(dxy_result)
            relation = "SAME" if symbol.startswith("USD") else "INVERSE"
            contradictory = False
            if direction in {"BULLISH", "BEARISH"} and dxy_direction in {
                "BULLISH",
                "BEARISH",
            }:
                if relation == "SAME":
                    contradictory = dxy_direction != direction
                else:
                    contradictory = dxy_direction == direction

            context.state["dxy_context"] = {
                "required": True,
                "symbol": dxy_symbol,
                "timeframe": dxy_timeframe,
                "primary_direction": direction,
                "dxy_direction": dxy_direction,
                "relation": relation,
                "contradictory": contradictory,
            }
            if contradictory:
                return ConditionEvaluationResult(
                    True,
                    False,
                    "dxy_context_contradicts:"
                    f"primary={direction}:dxy={dxy_direction}:relation={relation}",
                    diagnostics=dict(context.state["dxy_context"]),
                )
            return None

        h4_direction = str(
            context.state.get("h4_direction") or ""
        ).strip().upper()
        if (
            getattr(result, "passed", False)
            and h4_direction in {"BULLISH", "BEARISH"}
            and direction in {"BULLISH", "BEARISH"}
            and direction != h4_direction
        ):
            return ConditionEvaluationResult(
                True,
                False,
                "event_direction_contradicts_h4:"
                f"event={event_name}:h4={h4_direction}:event_direction={direction}",
            )

        return None

    def _evaluate_atr_branch(
        self,
        *,
        payload: dict[str, Any],
        context: StrategyContext,
        result: Any | None = None,
    ) -> ConditionEvaluationResult | None:
        """
        Enforce parser-emitted ATR entry branch metadata.

        Structured SMC entries use the final M15 confirmation EVENT to encode
        two mutually exclusive entry branches:

        MARKET -> minimum strong-displacement ATR floor (when configured)
                  <= displacement range < 1.5 * ATR(14)
        LIMIT  -> displacement range >= 1.5 * ATR(14)

        Metadata without atr_branch_required is ignored.
        """
        metadata = dict(
            payload.get("metadata") or {}
        )

        if metadata.get(
            "atr_branch_required"
        ) is not True:
            return None

        timeframe = str(
            metadata.get("atr_timeframe")
            or metadata.get("timeframe")
            or "M15"
        ).strip().upper()

        operator = str(
            metadata.get("atr_operator")
            or ""
        ).strip()

        try:
            period = int(
                metadata.get(
                    "atr_period",
                    14,
                )
            )
            multiplier = float(
                metadata.get(
                    "atr_multiplier",
                    1.5,
                )
            )
            raw_minimum_multiplier = metadata.get(
                "atr_minimum_multiplier"
            )
            minimum_multiplier = (
                None
                if raw_minimum_multiplier in {None, ""}
                else float(raw_minimum_multiplier)
            )
        except (TypeError, ValueError):
            return ConditionEvaluationResult(
                False,
                False,
                "atr_branch_metadata_invalid",
                diagnostics={
                    "timeframe": timeframe,
                    "operator": operator,
                    "period": metadata.get("atr_period"),
                    "multiplier": metadata.get("atr_multiplier"),
                    "minimum_multiplier": metadata.get(
                        "atr_minimum_multiplier"
                    ),
                },
            )

        if (
            period < 1
            or multiplier <= 0
            or (
                minimum_multiplier is not None
                and minimum_multiplier <= 0
            )
            or (
                minimum_multiplier is not None
                and operator in {"<", "<="}
                and minimum_multiplier >= multiplier
            )
            or operator not in {
                "<",
                "<=",
                ">",
                ">=",
                "==",
                "!=",
            }
        ):
            return ConditionEvaluationResult(
                False,
                False,
                "atr_branch_metadata_invalid",
                diagnostics={
                    "timeframe": timeframe,
                    "operator": operator,
                    "period": period,
                    "multiplier": multiplier,
                    "minimum_multiplier": minimum_multiplier,
                },
            )

        rates = context.get_rates(
            timeframe
        )

        timed_candles = self._ohlc_time_rows(
            rates
        )

        if len(timed_candles) < period + 1:
            return ConditionEvaluationResult(
                True,
                False,
                (
                    "atr_branch_waiting:"
                    f"timeframe={timeframe}:"
                    f"required_bars={period + 1}:"
                    f"available_bars={len(timed_candles)}"
                ),
                diagnostics={
                    "timeframe": timeframe,
                    "period": period,
                    "available_bars": len(timed_candles),
                },
            )

        result_data = dict(
            getattr(result, "data", None) or {}
        )
        active_zone = result_data.get("active_zone")

        if not isinstance(active_zone, dict):
            return ConditionEvaluationResult(
                True,
                False,
                "atr_branch_waiting:active_fvg_missing",
                diagnostics={
                    "timeframe": timeframe,
                    "period": period,
                },
            )

        try:
            displacement_time = int(
                active_zone.get("middle_time")
            )
        except (TypeError, ValueError, OverflowError):
            return ConditionEvaluationResult(
                True,
                False,
                "atr_branch_waiting:fvg_displacement_time_missing",
                diagnostics={
                    "timeframe": timeframe,
                    "zone_id": active_zone.get("zone_id"),
                },
            )

        displacement_index: int | None = None

        for index, candle in enumerate(timed_candles):
            candle_time = candle[0]
            if candle_time == displacement_time:
                displacement_index = index
                break

        if displacement_index is None:
            return ConditionEvaluationResult(
                True,
                False,
                (
                    "atr_branch_waiting:"
                    f"fvg_displacement_bar_missing={displacement_time}"
                ),
                diagnostics={
                    "timeframe": timeframe,
                    "zone_id": active_zone.get("zone_id"),
                    "displacement_time": displacement_time,
                    "available_bars": len(timed_candles),
                },
            )

        if displacement_index + 1 < period + 1:
            return ConditionEvaluationResult(
                True,
                False,
                (
                    "atr_branch_waiting:"
                    f"displacement_history_required={period + 1}:"
                    f"available={displacement_index + 1}"
                ),
                diagnostics={
                    "timeframe": timeframe,
                    "period": period,
                    "displacement_time": displacement_time,
                },
            )

        # Do not let tap/confirmation candles that happened after the FVG was
        # created alter the original MARKET-vs-LIMIT decision.
        origin_candles = timed_candles[
            :displacement_index + 1
        ]

        true_ranges: list[float] = []

        previous_close: float | None = None

        for _, high, low, close in origin_candles:
            if previous_close is None:
                true_range = high - low
            else:
                true_range = max(
                    high - low,
                    abs(
                        high
                        - previous_close
                    ),
                    abs(
                        low
                        - previous_close
                    ),
                )

            if true_range < 0:
                return ConditionEvaluationResult(
                    False,
                    False,
                    "atr_branch_invalid_candle_range",
                    diagnostics={
                        "timeframe": timeframe,
                        "high": high,
                        "low": low,
                    },
                )

            true_ranges.append(
                float(true_range)
            )
            previous_close = close

        # Wilder ATR: SMA seed, then recursive smoothing.
        atr = (
            sum(
                true_ranges[:period]
            )
            / float(period)
        )

        for true_range in true_ranges[
            period:
        ]:
            atr = (
                (
                    atr
                    * float(
                        period - 1
                    )
                )
                + true_range
            ) / float(period)

        _, displacement_high, displacement_low, _ = (
            origin_candles[-1]
        )

        displacement_range = (
            displacement_high
            - displacement_low
        )

        threshold = (
            float(multiplier)
            * float(atr)
        )

        minimum_threshold = (
            None
            if minimum_multiplier is None
            else float(minimum_multiplier) * float(atr)
        )

        branch_passed = {
            "<": (
                displacement_range
                < threshold
            ),
            "<=": (
                displacement_range
                <= threshold
            ),
            ">": (
                displacement_range
                > threshold
            ),
            ">=": (
                displacement_range
                >= threshold
            ),
            "==": (
                displacement_range
                == threshold
            ),
            "!=": (
                displacement_range
                != threshold
            ),
        }[operator]

        strong_displacement_passed = (
            minimum_threshold is None
            or displacement_range >= minimum_threshold
        )
        passed = bool(
            branch_passed
            and strong_displacement_passed
        )

        semantic_event = str(
            metadata.get(
                "atr_semantic_event"
            )
            or ""
        ).strip()

        atr_diagnostics = {
            "timeframe": timeframe,
            "period": period,
            "operator": operator,
            "multiplier": multiplier,
            "minimum_multiplier": minimum_multiplier,
            "atr": float(atr),
            "threshold": float(threshold),
            "minimum_threshold": minimum_threshold,
            "displacement_range": float(
                displacement_range
            ),
            "displacement_time": displacement_time,
            "zone_id": active_zone.get("zone_id"),
            "atr_source": "ACTIVE_FVG_MIDDLE_CANDLE",
            "semantic_event": (
                semantic_event
                or None
            ),
            "branch_passed": bool(branch_passed),
            "strong_displacement_passed": bool(
                strong_displacement_passed
            ),
            "passed": bool(passed),
        }

        context.state["atr_entry_contract"] = dict(
            atr_diagnostics
        )

        return ConditionEvaluationResult(
            True,
            bool(passed),
            (
                "atr_branch_passed"
                if passed
                else "atr_branch_not_passed"
            )
            + (
                f":semantic={semantic_event}"
                if semantic_event
                else ""
            )
            + (
                f":range={displacement_range:.10f}"
                f":operator={operator}"
                f":threshold={threshold:.10f}"
                f":atr={atr:.10f}"
            )
            + (
                ""
                if minimum_threshold is None
                else (
                    f":minimum_threshold={minimum_threshold:.10f}"
                    f":minimum_passed={strong_displacement_passed}"
                )
            ),
            diagnostics=atr_diagnostics,
        )

    @staticmethod
    def _ohlc_rows(
        rates: Any,
    ) -> list[
        tuple[
            float,
            float,
            float,
        ]
    ]:
        """Normalize runtime rate containers into (high, low, close) rows."""
        if rates is None:
            return []

        rows: list[
            tuple[
                float,
                float,
                float,
            ]
        ] = []

        # pandas.DataFrame
        if hasattr(
            rates,
            "columns",
        ):
            try:
                required = {
                    "high",
                    "low",
                    "close",
                }

                if not required.issubset(
                    set(rates.columns)
                ):
                    return []

                for high, low, close in zip(
                    rates["high"].tolist(),
                    rates["low"].tolist(),
                    rates["close"].tolist(),
                ):
                    rows.append(
                        (
                            float(high),
                            float(low),
                            float(close),
                        )
                    )

                return rows
            except Exception:
                return []

        try:
            iterable = list(rates)
        except Exception:
            return []

        for row in iterable:
            values: list[float] = []

            for field_name in (
                "high",
                "low",
                "close",
            ):
                value: Any = None

                try:
                    value = row[
                        field_name
                    ]
                except Exception:
                    try:
                        value = getattr(
                            row,
                            field_name,
                        )
                    except Exception:
                        return []

                try:
                    values.append(
                        float(value)
                    )
                except (
                    TypeError,
                    ValueError,
                    OverflowError,
                ):
                    return []

            rows.append(
                (
                    values[0],
                    values[1],
                    values[2],
                )
            )

        return rows

    @staticmethod
    def _ohlc_time_rows(
        rates: Any,
    ) -> list[
        tuple[
            int | None,
            float,
            float,
            float,
        ]
    ]:
        """Normalize runtime rates into (time, high, low, close) rows."""
        if rates is None:
            return []

        if hasattr(rates, "columns"):
            try:
                required = {"time", "high", "low", "close"}
                if not required.issubset(set(rates.columns)):
                    return []

                iterable = rates[
                    ["time", "high", "low", "close"]
                ].itertuples(index=False, name=None)
            except Exception:
                return []
        else:
            try:
                iterable = list(rates)
            except Exception:
                return []

        rows: list[
            tuple[int | None, float, float, float]
        ] = []

        for row in iterable:
            if isinstance(row, tuple) and len(row) == 4:
                raw_time, raw_high, raw_low, raw_close = row
            else:
                values: list[Any] = []
                for field_name in ("time", "high", "low", "close"):
                    try:
                        value = row[field_name]
                    except Exception:
                        try:
                            value = getattr(row, field_name)
                        except Exception:
                            return []
                    values.append(value)
                raw_time, raw_high, raw_low, raw_close = values

            try:
                candle_time = (
                    int(raw_time.timestamp())
                    if hasattr(raw_time, "timestamp")
                    else int(raw_time)
                )
                rows.append(
                    (
                        candle_time,
                        float(raw_high),
                        float(raw_low),
                        float(raw_close),
                    )
                )
            except (TypeError, ValueError, OverflowError):
                return []

        return rows

    def _evaluate_alternative_poi_event(
        self,
        *,
        event_name: str,
        capability: str,
        payload: dict[str, Any],
        context: StrategyContext,
    ) -> ConditionEvaluationResult | None:
        """Treat explicit multiple POI types as OR alternatives."""
        if event_name != "POI_DETECTION":
            return None

        metadata = dict(payload.get("metadata") or {})
        raw_types = metadata.get("poi_types")
        if not isinstance(raw_types, (list, tuple, set)):
            return None

        poi_types = {
            str(item).strip().upper()
            for item in raw_types
            if str(item).strip()
        }
        if len(poi_types) < 2:
            return None

        provider_by_type = {
            "FVG": "fvg_poi",
            "IFVG": "fvg_poi",
            "ORDER_BLOCK": "order_block_poi",
            "OB": "order_block_poi",
        }
        wanted = {
            provider_by_type[item]
            for item in poi_types
            if item in provider_by_type
        }

        candidates = [
            binding
            for binding in self.compiled.module_bindings
            if (
                self._capability_key(binding.capability) == capability
                and str(binding.provider).strip().lower() in wanted
            )
        ]

        diagnostics: dict[str, Any] = {
            "semantic": "POI_ALTERNATIVES",
            "poi_types": sorted(poi_types),
            "attempts": [],
        }

        for binding in sorted(
            candidates,
            key=lambda item: (
                str(item.provider).strip().lower(),
                str(item.version),
            ),
        ):
            try:
                role = ModuleRole(binding.role)
            except ValueError:
                continue

            definition = StrategyModuleDefinition(
                role=role,
                provider=binding.provider,
                enabled=True,
                required=True,
                parameters={
                    "capability": binding.capability,
                    "event_name": event_name,
                    "poi_alternative": True,
                    "event_metadata": dict(
                        payload.get("metadata") or {}
                    ),
                },
                metadata={
                    "compiled_strategy_id": self.compiled.strategy_id,
                    "compilation_id": self.compiled.compilation_id,
                    **dict(
                        payload.get("metadata") or {}
                    ),
                    "poi_types": sorted(poi_types),
                },
            )

            key = (role.value, str(binding.provider).strip().lower())
            module = self._instances.get(key)
            if module is None:
                try:
                    module = self.registry.create(definition)
                except Exception as exc:
                    diagnostics["attempts"].append({
                        "provider": binding.provider,
                        "success": False,
                        "passed": False,
                        "reason": f"module_create_failed:{type(exc).__name__}:{exc}",
                    })
                    continue
                self._instances[key] = module

            self._apply_event_runtime_hints(
                module=module,
                payload=payload,
            )

            dependency_result = self._ensure_module_dependencies(
                module=module,
                context=context,
                stack=set(),
                runtime_payload=payload,
            )
            if dependency_result is not None:
                diagnostics["attempts"].append({
                    "provider": binding.provider,
                    "success": bool(dependency_result.success),
                    "passed": bool(dependency_result.passed),
                    "reason": dependency_result.reason,
                })
                continue

            result = module.run(context)
            context.set_result(result)

            self._record_event_result(
                context=context,
                payload=payload,
                event_name=event_name,
                provider=binding.provider,
                role=role,
                result=result,
            )

            diagnostics["attempts"].append({
                "provider": binding.provider,
                "success": bool(result.success),
                "passed": bool(result.passed),
                "error": result.error,
                "diagnostics": dict(result.diagnostics or {}),
            })
            if result.success and result.passed:
                return ConditionEvaluationResult(
                    True, True,
                    f"poi_alternative_passed:provider={binding.provider}",
                    diagnostics=diagnostics,
                )

        # LIQUIDITY is also an allowed POI type. Evaluate its production module
        # directly instead of requiring an Order Block to exist.
        if "LIQUIDITY" in poi_types:
            binding = self._resolve_dependency_binding(ModuleRole.LIQUIDITY)
            if binding is not None:
                capability_name = getattr(binding, "capability", None) or "liquidity_sweep"
                definition = StrategyModuleDefinition(
                    role=ModuleRole.LIQUIDITY,
                    provider=binding.provider,
                    enabled=True,
                    required=True,
                    parameters={
                        "capability": capability_name,
                        "event_name": event_name,
                        "poi_alternative": True,
                    },
                    metadata={
                        "compiled_strategy_id": self.compiled.strategy_id,
                        "compilation_id": self.compiled.compilation_id,
                        "poi_type": "LIQUIDITY",
                    },
                )
                key = (
                    ModuleRole.LIQUIDITY.value,
                    str(binding.provider).strip().lower(),
                )
                module = self._instances.get(key)
                if module is None:
                    try:
                        module = self.registry.create(definition)
                        self._instances[key] = module
                    except Exception as exc:
                        diagnostics["attempts"].append({
                            "provider": binding.provider,
                            "poi_type": "LIQUIDITY",
                            "success": False,
                            "passed": False,
                            "reason": f"module_create_failed:{type(exc).__name__}:{exc}",
                        })
                        module = None

                if module is not None:
                    dep = self._ensure_module_dependencies(
                        module=module,
                        context=context,
                        stack=set(),
                        runtime_payload=payload,
                    )
                    if dep is None:
                        result = module.run(context)
                        context.set_result(result)

                        self._record_event_result(
                            context=context,
                            payload=payload,
                            event_name=event_name,
                            provider=binding.provider,
                            role=role,
                            result=result,
                        )

                        diagnostics["attempts"].append({
                            "provider": binding.provider,
                            "poi_type": "LIQUIDITY",
                            "success": bool(result.success),
                            "passed": bool(result.passed),
                            "error": result.error,
                            "diagnostics": dict(result.diagnostics or {}),
                        })
                        if result.success and result.passed:
                            return ConditionEvaluationResult(
                                True, True,
                                f"poi_alternative_passed:provider={binding.provider}",
                                diagnostics=diagnostics,
                            )
                    else:
                        diagnostics["attempts"].append({
                            "provider": binding.provider,
                            "poi_type": "LIQUIDITY",
                            "success": bool(dep.success),
                            "passed": bool(dep.passed),
                            "reason": dep.reason,
                        })

        attempt_reasons: list[str] = []

        for attempt in diagnostics.get("attempts", []):
            provider = str(
                attempt.get("provider") or "unknown"
            )

            attempt_diagnostics = (
                dict(attempt.get("diagnostics") or {})
                if isinstance(
                    attempt.get("diagnostics"),
                    dict,
                )
                else {}
            )

            reason = str(
                attempt.get("reason")
                or attempt.get("error")
                or attempt_diagnostics.get(
                    "rejection_reason"
                )
                or attempt_diagnostics.get(
                    "reason"
                )
                or self._diagnostic_reason(
                    attempt_diagnostics
                )
                or "not_passed"
            )

            attempt_reasons.append(
                f"{provider}={reason}"
            )

        summary = (
            "|".join(attempt_reasons)
            if attempt_reasons
            else "no_attempt_details"
        )

        return ConditionEvaluationResult(
            True,
            False,
            (
                "poi_alternatives_not_passed:"
                f"{summary}"
            ),
            diagnostics=diagnostics,
        )

    @staticmethod
    def _record_event_result(
        *,
        context: StrategyContext,
        payload: dict[str, Any],
        event_name: str,
        provider: str,
        role: ModuleRole,
        result: Any,
    ) -> None:
        """
        Persist event-local module snapshots.

        StrategyContext.module_results is keyed by role/provider, so the same
        provider used on H4 and M15 overwrites the earlier result. TradePlan
        resolution needs the exact point-in-time event result that passed.
        """
        metadata = dict(
            payload.get("metadata") or {}
        )

        node_id = str(
            payload.get("node_id")
            or metadata.get("node_id")
            or ""
        ).strip()

        timeframe = str(
            metadata.get("timeframe")
            or payload.get("timeframe")
            or result.data.get("timeframe")
            or result.diagnostics.get("timeframe")
            or result.diagnostics.get("selected_timeframe")
            or ""
        ).strip().upper()

        history = context.state.setdefault(
            "event_result_history",
            []
        )

        if not isinstance(history, list):
            history = []
            context.state[
                "event_result_history"
            ] = history

        snapshot = {
            "event_name": str(
                event_name
            ),
            "node_id": node_id,
            "provider": str(
                provider
            ),
            "role": str(
                role.value
            ),
            "timeframe": timeframe,
            "current_time": int(
                context.current_time
            ),
            "success": bool(
                result.success
            ),
            "passed": bool(
                result.passed
            ),
            "data": dict(
                result.data or {}
            ),
            "diagnostics": dict(
                result.diagnostics or {}
            ),
        }

        history.append(
            snapshot
        )

        # Keep memory bounded in long backtests.
        if len(history) > 200:
            del history[:-200]

        if result.success and result.passed:
            context.state[
                "last_passed_event_result"
            ] = snapshot

    def _ensure_event_timeframe(
        self,
        *,
        payload: dict[str, Any],
        context: StrategyContext,
    ) -> dict[str, Any]:
        """Add a causal timeframe when legacy parser output omitted it."""
        normalized = dict(payload)
        metadata = dict(normalized.get("metadata") or {})

        explicit = str(
            metadata.get("timeframe")
            or normalized.get("timeframe")
            or ""
        ).strip().upper()
        if explicit:
            return normalized

        available = {
            str(timeframe).strip().upper()
            for timeframe, rates in context.rates_by_timeframe.items()
            if rates is not None
        }

        selected = next(
            (
                str(timeframe).strip().upper()
                for timeframe in self.compiled.timeframes
                if str(timeframe).strip().upper() in available
            ),
            None,
        )

        if selected is None and len(available) == 1:
            selected = next(iter(available))

        if selected is None:
            return normalized

        metadata["timeframe"] = selected
        metadata["timeframe_source"] = "COMPILED_STRATEGY_FALLBACK"
        normalized["metadata"] = metadata
        return normalized

    @staticmethod
    def _apply_event_runtime_hints(
        *,
        module: Any,
        payload: dict[str, Any],
    ) -> None:
        """
        Apply condition-local runtime hints to a cached strategy module.

        Important:
        module instances are cached by role/provider, while the same provider
        can be used by several EVENT nodes on different timeframes. Therefore
        the active EVENT timeframe must be re-applied before every run.
        """
        metadata = dict(
            payload.get("metadata") or {}
        )

        timeframe = str(
            metadata.get("timeframe")
            or payload.get("timeframe")
            or ""
        ).strip().upper()

        if not timeframe:
            return

        # Keep the module definition synchronized for modules that read it.
        definition = getattr(
            module,
            "definition",
            None,
        )

        if definition is not None:
            try:
                definition.parameters[
                    "timeframe"
                ] = timeframe
                definition.parameters[
                    "event_metadata"
                ] = dict(metadata)
            except Exception:
                pass

            try:
                definition.metadata.update(
                    metadata
                )
                definition.metadata[
                    "timeframe"
                ] = timeframe
            except Exception:
                pass

        # Existing production adapters (notably FVGPOIModule) wrap a detector
        # whose timeframe currently lives in detector.config. Do not rebuild
        # the detector/service; only switch the requested timeframe.
        detector = getattr(
            module,
            "detector",
            None,
        )

        detector_config = getattr(
            detector,
            "config",
            None,
        )

        if (
            detector_config is not None
            and hasattr(
                detector_config,
                "timeframe",
            )
        ):
            try:
                detector_config.timeframe = (
                    timeframe
                )
            except Exception:
                pass

    def _select_event_binding(
        self,
        *,
        capability: str,
        payload: dict[str, Any],
    ) -> Any | None:
        candidates = [
            binding
            for binding in self.compiled.module_bindings
            if self._capability_key(binding.capability) == capability
        ]

        if not candidates:
            return None

        metadata = dict(payload.get("metadata") or {})
        provider_hint = str(
            metadata.get("provider_hint") or ""
        ).strip().lower()

        if provider_hint:
            for binding in candidates:
                if str(binding.provider).strip().lower() == provider_hint:
                    return binding
            return None

        return sorted(
            candidates,
            key=lambda item: (
                str(item.provider).strip().lower(),
                str(item.version),
            ),
        )[0]

    def _ensure_module_dependencies(
        self,
        *,
        module: Any,
        context: StrategyContext,
        stack: set[str],
        runtime_payload: dict[str, Any] | None = None,
    ) -> ConditionEvaluationResult | None:
        active_payload = dict(runtime_payload or {})
        active_metadata = dict(
            active_payload.get("metadata") or {}
        )
        active_timeframe = str(
            active_metadata.get("timeframe")
            or active_payload.get("timeframe")
            or ""
        ).strip().upper()

        dependencies = tuple(
            getattr(module, "dependencies", ()) or ()
        )

        for dependency_role in dependencies:
            if context.has_succeeded(dependency_role):
                continue

            role = (
                dependency_role
                if isinstance(dependency_role, ModuleRole)
                else ModuleRole(str(dependency_role))
            )
            stack_key = role.value

            if stack_key in stack:
                return ConditionEvaluationResult(
                    False,
                    False,
                    f"module_dependency_cycle:{stack_key}",
                    diagnostics={
                        "dependency_role": stack_key,
                        "stack": sorted(stack),
                    },
                )

            binding = self._resolve_dependency_binding(role)

            if binding is None:
                return ConditionEvaluationResult(
                    False,
                    False,
                    f"dependency_binding_missing:{role.value}",
                    diagnostics={
                        "dependency_role": role.value,
                        "module_provider": getattr(module, "provider", None),
                    },
                )

            dependency_capability = getattr(
                binding,
                "capability",
                None,
            )

            if not dependency_capability:
                dependency_capability = {
                    ModuleRole.TREND: "direction_bias",
                    ModuleRole.LIQUIDITY: "liquidity_sweep",
                }.get(role)

            if not dependency_capability:
                return ConditionEvaluationResult(
                    False,
                    False,
                    f"dependency_capability_missing:{role.value}",
                    diagnostics={
                        "dependency_role": role.value,
                        "provider": getattr(
                            binding,
                            "provider",
                            None,
                        ),
                    },
                )

            definition = StrategyModuleDefinition(
                role=role,
                provider=binding.provider,
                enabled=True,
                required=True,
                parameters={
                    "capability": dependency_capability,
                    "dependency_execution": True,
                    "timeframe": active_timeframe or None,
                    "event_metadata": active_metadata,
                },
                metadata={
                    "compiled_strategy_id": self.compiled.strategy_id,
                    "compilation_id": self.compiled.compilation_id,
                    "dependency_execution": True,
                    **active_metadata,
                    "timeframe": active_timeframe or None,
                },
            )

            key = (
                role.value,
                str(binding.provider).strip().lower(),
            )

            dependency_module = self._instances.get(key)

            if dependency_module is None:
                try:
                    dependency_module = self.registry.create(definition)
                except Exception as exc:
                    return ConditionEvaluationResult(
                        False,
                        False,
                        (
                            "dependency_module_create_failed:"
                            f"{type(exc).__name__}:{exc}"
                        ),
                        diagnostics={
                            "dependency_role": role.value,
                            "provider": binding.provider,
                        },
                    )
                self._instances[key] = dependency_module

            # EVENT metadata belongs to the entire dependency graph, not only
            # to the top-level module.  Without this propagation a M5
            # LIQUIDITY_SWEEP created its TREND dependency with the detector's
            # default H4 timeframe and failed with not_enough_structure_data.
            self._apply_event_runtime_hints(
                module=dependency_module,
                payload=active_payload,
            )

            next_stack = set(stack)
            next_stack.add(stack_key)

            nested = self._ensure_module_dependencies(
                module=dependency_module,
                context=context,
                stack=next_stack,
                runtime_payload=active_payload,
            )
            if nested is not None:
                return nested

            dependency_execution = dependency_module.run(context)
            context.set_result(dependency_execution)

            if not dependency_execution.success:
                return ConditionEvaluationResult(
                    False,
                    False,
                    (
                        dependency_execution.error
                        or f"dependency_module_execution_failed:{role.value}"
                    ),
                    diagnostics={
                        "dependency_role": role.value,
                        "provider": binding.provider,
                        "passed": bool(dependency_execution.passed),
                        "module_diagnostics": dict(
                            dependency_execution.diagnostics or {}
                        ),
                    },
                )

        return None

    def _resolve_dependency_binding(
        self,
        role: ModuleRole,
    ) -> Any | None:
        # Prefer a binding already present in the compiled strategy.
        candidates = [
            binding
            for binding in self.compiled.module_bindings
            if str(binding.role).strip().upper() == role.value.upper()
        ]

        preferred_provider = {
            ModuleRole.TREND: "structure_trend",
            ModuleRole.LIQUIDITY: "liquidity_sweep",
        }.get(role)

        if candidates:
            if preferred_provider:
                for binding in candidates:
                    if (
                        str(binding.provider).strip().lower()
                        == preferred_provider
                    ):
                        return binding
            return sorted(
                candidates,
                key=lambda item: (
                    str(item.provider).strip().lower(),
                    str(item.version),
                ),
            )[0]

        # Technical dependencies do not have to be explicit strategy events.
        # Resolve canonical production dependency from the registry.
        canonical_capability = {
            ModuleRole.TREND: "direction_bias",
            ModuleRole.LIQUIDITY: "liquidity_sweep",
        }.get(role)

        if not canonical_capability:
            return None

        matches = list(
            self.registry.find_by_capability(
                canonical_capability,
                role=role,
            )
        )

        if not matches:
            return None

        if preferred_provider:
            for match in matches:
                if (
                    str(match.provider).strip().lower()
                    == preferred_provider
                ):
                    return match

        return sorted(
            matches,
            key=lambda item: (
                str(item.provider).strip().lower(),
                str(item.version),
            ),
        )[0]

    def _evaluate_and(
        self,
        node: dict[str, Any],
        context: StrategyContext,
    ) -> ConditionEvaluationResult:
        children = list(
            node.get("children") or []
        )

        if not children:
            return ConditionEvaluationResult(
                False,
                False,
                "and_requires_children",
            )

        for child in children:
            result = self.evaluate(
                child,
                context,
            )

            if not result.success:
                return result

            if not result.passed:
                return ConditionEvaluationResult(
                    True,
                    False,
                    "and_child_not_passed",
                )

        return ConditionEvaluationResult(
            True,
            True,
            "and_passed",
        )

    def _evaluate_or(
        self,
        node: dict[str, Any],
        context: StrategyContext,
    ) -> ConditionEvaluationResult:
        children = list(
            node.get("children") or []
        )

        if not children:
            return ConditionEvaluationResult(
                False,
                False,
                "or_requires_children",
            )

        saw_success = False

        for child in children:
            result = self.evaluate(
                child,
                context,
            )

            if not result.success:
                continue

            saw_success = True

            if result.passed:
                return ConditionEvaluationResult(
                    True,
                    True,
                    "or_passed",
                )

        if not saw_success:
            return ConditionEvaluationResult(
                False,
                False,
                "or_all_children_failed",
            )

        return ConditionEvaluationResult(
            True,
            False,
            "or_no_child_passed",
        )

    def _evaluate_not(
        self,
        node: dict[str, Any],
        context: StrategyContext,
    ) -> ConditionEvaluationResult:
        children = list(
            node.get("children") or []
        )

        if len(children) != 1:
            return ConditionEvaluationResult(
                False,
                False,
                "not_requires_one_child",
            )

        result = self.evaluate(
            children[0],
            context,
        )

        if not result.success:
            return result

        return ConditionEvaluationResult(
            True,
            not result.passed,
            "not_evaluated",
        )

    def _evaluate_sequence(
        self,
        node: dict[str, Any],
        context: StrategyContext,
    ) -> ConditionEvaluationResult:
        children = list(
            node.get("children") or []
        )

        if not children:
            return ConditionEvaluationResult(
                False,
                False,
                "sequence_requires_children",
            )

        node_id = str(
            node.get("node_id", "sequence")
        )

        state_key = (
            "compiled_sequence_progress:"
            f"{node_id}"
        )

        try:
            index = int(
                context.get(
                    state_key,
                    0,
                )
            )
        except (
            TypeError,
            ValueError,
        ):
            index = 0

        index = max(
            0,
            min(
                index,
                len(children) - 1,
            ),
        )

        while index < len(children):
            result = self.evaluate(
                children[index],
                context,
            )

            if not result.success:
                return result

            if not result.passed:
                context.put(
                    state_key,
                    index,
                )
                child = children[index]
                child_node = (
                    child.to_dict()
                    if isinstance(child, CompiledCondition)
                    else dict(child)
                )
                child_operation = str(
                    child_node.get("operation", "")
                ).strip().upper() or "EMPTY"
                child_payload = dict(
                    child_node.get("payload") or {}
                )
                child_event_name = str(
                    child_payload.get("event_name", "")
                ).strip().upper()
                child_node_id = str(
                    child_node.get("node_id", "")
                ).strip()

                detail_parts = [
                    f"sequence_waiting:{index}",
                    f"operation={child_operation}",
                ]
                if child_event_name:
                    detail_parts.append(
                        f"event_name={child_event_name}"
                    )
                if child_node_id:
                    detail_parts.append(
                        f"node_id={child_node_id}"
                    )
                if result.reason:
                    detail_parts.append(
                        f"child_reason={result.reason}"
                    )

                return ConditionEvaluationResult(
                    True,
                    False,
                    ":".join(detail_parts),
                    diagnostics={
                        "progress": index,
                        "total": len(children),
                        "waiting_child": {
                            "operation": child_operation,
                            "event_name": child_event_name or None,
                            "node_id": child_node_id or None,
                            "reason": result.reason,
                            "diagnostics": dict(
                                result.diagnostics
                            ),
                        },
                    },
                )

            index += 1
            context.put(
                state_key,
                index,
            )

        context.put(
            state_key,
            0,
        )

        return ConditionEvaluationResult(
            True,
            True,
            "sequence_passed",
            diagnostics={
                "progress": len(children),
                "total": len(children),
            },
        )

    def _evaluate_comparison(
        self,
        node: dict[str, Any],
        context: StrategyContext,
    ) -> ConditionEvaluationResult:
        payload = dict(
            node.get("payload") or {}
        )

        left_ref = payload.get(
            "left"
        )
        right_ref = payload.get(
            "right"
        )
        operator = str(
            payload.get("operator", "")
        ).upper()

        left = self._resolve_value(
            left_ref,
            context,
        )
        right = self._resolve_value(
            right_ref,
            context,
        )

        if left[0] is False:
            return ConditionEvaluationResult(
                False,
                False,
                left[1],
            )

        if right[0] is False:
            return ConditionEvaluationResult(
                False,
                False,
                right[1],
            )

        a = left[2]
        b = right[2]

        if operator in {"CROSS_ABOVE", "CROSS_BELOW"}:
            previous_left = self._resolve_previous_value(left_ref, context)
            previous_right = self._resolve_previous_value(right_ref, context)

            if previous_left[0] is False:
                return ConditionEvaluationResult(False, False, previous_left[1])

            if previous_right[0] is False:
                return ConditionEvaluationResult(False, False, previous_right[1])

            prev_a = previous_left[2]
            prev_b = previous_right[2]

            try:
                if operator == "CROSS_ABOVE":
                    passed = prev_a <= prev_b and a > b
                else:
                    passed = prev_a >= prev_b and a < b
            except Exception as exc:
                return ConditionEvaluationResult(
                    False,
                    False,
                    f"comparison_failed:{type(exc).__name__}:{exc}",
                )

            return ConditionEvaluationResult(
                True,
                bool(passed),
                "comparison_evaluated",
                diagnostics={
                    "previous_left": prev_a,
                    "previous_right": prev_b,
                    "left": a,
                    "operator": operator,
                    "right": b,
                },
            )

        try:
            passed = {
                "==": lambda: a == b,
                "!=": lambda: a != b,
                ">": lambda: a > b,
                ">=": lambda: a >= b,
                "<": lambda: a < b,
                "<=": lambda: a <= b,
            }[operator]()
        except KeyError:
            return ConditionEvaluationResult(
                False,
                False,
                (
                    "unsupported_comparison_operator:"
                    f"{operator}"
                ),
            )
        except Exception as exc:
            return ConditionEvaluationResult(
                False,
                False,
                (
                    "comparison_failed:"
                    f"{type(exc).__name__}:{exc}"
                ),
            )

        return ConditionEvaluationResult(
            True,
            bool(passed),
            "comparison_evaluated",
            diagnostics={
                "left": a,
                "operator": operator,
                "right": b,
            },
        )

    def _resolve_value(
        self,
        reference: Any,
        context: StrategyContext,
    ) -> tuple[
        bool,
        str,
        Any,
    ]:
        if not isinstance(
            reference,
            dict,
        ):
            return (
                False,
                "value_reference_missing",
                None,
            )

        source = str(
            reference.get("source", "")
        ).strip().upper()

        field = reference.get(
            "field"
        )

        if source in {
            "CONSTANT",
            "CONST",
        }:
            return (
                True,
                "",
                reference.get(
                    "constant"
                ),
            )

        if source == "MARKET":
            if field is None:
                return (
                    False,
                    "market_field_missing",
                    None,
                )
            return (
                True,
                "",
                context.market.get(
                    str(field)
                ),
            )

        if source == "INDICATOR":
            return self._resolve_indicator_value(
                reference,
                context,
                previous=False,
            )

        if source == "STATE":
            if field is None:
                return (
                    False,
                    "state_field_missing",
                    None,
                )
            return (
                True,
                "",
                context.get(
                    str(field)
                ),
            )

        if source in {
            "RATE",
            "CANDLE",
        }:
            timeframe = str(
                reference.get(
                    "timeframe",
                    "",
                )
            ).strip()

            if not timeframe:
                return (
                    False,
                    "rate_timeframe_missing",
                    None,
                )

            rates = context.get_rates(
                timeframe
            )

            if rates is None or len(rates) == 0:
                return (
                    False,
                    "rate_data_missing",
                    None,
                )

            if field is None:
                return (
                    False,
                    "rate_field_missing",
                    None,
                )

            last = rates[-1]

            try:
                value = last[
                    str(field)
                ]
            except Exception:
                return (
                    False,
                    (
                        "rate_field_unavailable:"
                        f"{field}"
                    ),
                    None,
                )

            return (
                True,
                "",
                value,
            )

        return (
            False,
            (
                "unsupported_value_source:"
                f"{source or 'EMPTY'}"
            ),
            None,
        )

    def _resolve_previous_value(
        self,
        reference: Any,
        context: StrategyContext,
    ) -> tuple[bool, str, Any]:
        if not isinstance(reference, dict):
            return False, "value_reference_missing", None

        source = str(reference.get("source", "")).strip().upper()
        field = reference.get("field")

        if source == "INDICATOR":
            return self._resolve_indicator_value(
                reference,
                context,
                previous=True,
            )

        if source in {"RATE", "CANDLE"}:
            timeframe = str(reference.get("timeframe", "")).strip()
            if not timeframe:
                return False, "rate_timeframe_missing", None

            rates = context.get_rates(timeframe)
            if rates is None or len(rates) < 2:
                return False, "rate_previous_data_missing", None

            if field is None:
                return False, "rate_field_missing", None

            row = rates[-2]
            try:
                value = row[str(field)]
            except Exception:
                try:
                    value = getattr(row, str(field))
                except Exception:
                    return False, f"rate_field_unavailable:{field}", None

            return True, "", value

        return self._resolve_value(reference, context)

    def _resolve_indicator_value(
        self,
        reference: dict[str, Any],
        context: StrategyContext,
        *,
        previous: bool,
    ) -> tuple[bool, str, Any]:
        field = str(
            reference.get("field", "")
        ).strip().upper()

        timeframe = str(
            reference.get("timeframe", "")
        ).strip()

        if not timeframe:
            return (
                False,
                "indicator_timeframe_missing",
                None,
            )

        if field != "EMA":
            return (
                False,
                f"unsupported_indicator:{field or 'EMPTY'}",
                None,
            )

        parameters = dict(
            reference.get("parameters") or {}
        )

        try:
            period = int(parameters.get("period"))
        except (TypeError, ValueError):
            return (
                False,
                "ema_period_invalid",
                None,
            )

        if period < 1:
            return (
                False,
                "ema_period_invalid",
                None,
            )

        rates = context.get_rates(timeframe)

        if rates is None:
            return (
                False,
                "indicator_rate_data_missing",
                None,
            )

        closes: list[float] = []

        # pandas.DataFrame
        if hasattr(rates, "columns"):
            try:
                if "close" not in rates.columns:
                    return (
                        False,
                        "indicator_close_unavailable",
                        None,
                    )

                closes = [
                    float(value)
                    for value in rates["close"].tolist()
                ]
            except (TypeError, ValueError):
                return (
                    False,
                    "indicator_close_invalid",
                    None,
                )
            except Exception as exc:
                return (
                    False,
                    f"indicator_dataframe_failed:{type(exc).__name__}:{exc}",
                    None,
                )

        # list / tuple / numpy structured array / row objects
        else:
            try:
                iterable = list(rates)
            except Exception:
                return (
                    False,
                    "indicator_rate_data_invalid",
                    None,
                )

            for row in iterable:
                value = None

                try:
                    value = row["close"]
                except Exception:
                    try:
                        value = getattr(row, "close")
                    except Exception:
                        pass

                if value is None:
                    return (
                        False,
                        "indicator_close_unavailable",
                        None,
                    )

                try:
                    closes.append(float(value))
                except (TypeError, ValueError):
                    return (
                        False,
                        "indicator_close_invalid",
                        None,
                    )

        if not closes:
            return (
                False,
                "indicator_rate_data_missing",
                None,
            )

        if previous:
            if len(closes) < 2:
                return (
                    False,
                    "indicator_previous_data_missing",
                    None,
                )
            closes = closes[:-1]

        if len(closes) < period:
            return (
                False,
                f"ema_insufficient_history:{period}",
                None,
            )

        alpha = 2.0 / (period + 1.0)

        # Deterministic EMA seed: SMA of first period.
        ema = sum(closes[:period]) / period

        for close in closes[period:]:
            ema = (
                close * alpha
                + ema * (1.0 - alpha)
            )

        return (
            True,
            "",
            float(ema),
        )

    @staticmethod
    def _diagnostic_reason(
        diagnostics: dict[str, Any],
    ) -> str:
        """Encode useful failed-detector diagnostics into runtime reason."""
        if not diagnostics:
            return ""

        preferred_keys = (
            "accepted",
            "sweep_found",
            "poi_found",
            "bos_found",
            "fvg_found",
            "structure_loaded",
            "liquidity_loaded",
            "require_bos",
            "require_liquidity_sweep",
            "direction",
            "side",
            "quality_score",
            "candidate_count",
            "event_count",
        )

        parts: list[str] = []

        for key in preferred_keys:
            if key not in diagnostics:
                continue

            value = diagnostics.get(key)

            if value is None:
                continue

            if isinstance(value, (dict, list, tuple, set)):
                continue

            parts.append(
                f"{key}={value}"
            )

        if not parts:
            return ""

        return "diagnostics[" + ",".join(parts) + "]"

    @staticmethod
    def _capability_key(
        value: str,
    ) -> str:
        return (
            str(value)
            .strip()
            .lower()
            .replace(" ", "_")
        )
