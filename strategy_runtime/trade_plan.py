from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from core.context import StrategyContext
from concepts.sessions.services import SessionService, SessionServiceConfig
from strategy_compiler import CompiledStrategy


@dataclass(slots=True)
class TradePlan:
    strategy_id: str
    compilation_id: str
    symbol: str
    side: str
    order_type: str
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_percent: float
    risk_money: float
    lot: float
    entry_index: int
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "compilation_id": self.compilation_id,
            "symbol": self.symbol,
            "side": self.side,
            "order_type": self.order_type,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "risk_percent": self.risk_percent,
            "risk_money": self.risk_money,
            "lot": self.lot,
            "entry_index": self.entry_index,
            "diagnostics": dict(self.diagnostics),
        }


@dataclass(slots=True)
class TradePlanResolution:
    success: bool
    plan: TradePlan | None = None
    reason: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)


class TradePlanResolver:
    """
    Day 53 resolver.

    Converts an ENTRY_READY runtime state into concrete prices and size.

    Supported now:
    - MARKET entry from bid/ask/price
    - explicit/fixed entry price
    - SL by PERCENT
    - SL by fixed PRICE
    - TP by R_MULTIPLE
    - TP by PERCENT
    - TP by fixed PRICE
    - BALANCE_PERCENT risk sizing

    Unsupported/ambiguous rules fail closed.
    """

    def __init__(self, compiled: CompiledStrategy) -> None:
        self.compiled = compiled
        self._structure_sl_debug: dict[str, Any] = {}
        self._take_profit_debug: dict[str, Any] = {}

    def resolve(
        self,
        context: StrategyContext,
        *,
        balance: float,
        entry_index: int,
        pip_size: float = 0.0001,
        pip_value_per_lot: float = 10.0,
        minimum_stop_pips: float = 0.0,
        execution_cost_per_lot: float = 0.0,
        lot_step: float = 0.01,
        minimum_lot: float = 0.01,
        maximum_lot: float | None = None,
    ) -> TradePlanResolution:
        entry = self._entry(entry_index)
        if entry is None:
            return self._fail("entry_index_not_found")

        raw_side = entry.get("side")

        # Entry direction may be emitted by different compiler/runtime layers
        # under different canonical names. Normalize them at the TradePlan
        # boundary instead of forcing every strategy module to use one spelling.
        side_key = (
            str(raw_side or "")
            .strip()
            .upper()
            .replace("-", "_")
            .replace(" ", "_")
        )

        side_aliases = {
            "LONG": "LONG",
            "BUY": "LONG",
            "BULLISH": "LONG",
            "BULL": "LONG",
            "UP": "LONG",
            "SHORT": "SHORT",
            "SELL": "SHORT",
            "BEARISH": "SHORT",
            "BEAR": "SHORT",
            "DOWN": "SHORT",
        }

        side = side_aliases.get(side_key)

        # BOTH / AUTO / ANY means the strategy allows either direction.
        # The concrete trade side must come from point-in-time runtime evidence.
        dynamic_side_tokens = {
            "",
            "BOTH",
            "AUTO",
            "ANY",
            "EITHER",
            "BIDIRECTIONAL",
            "TRADE_DIRECTION_ONLY",
        }

        if side is None and side_key in dynamic_side_tokens:
            side = self._resolve_runtime_side(
                context=context,
                side_aliases=side_aliases,
            )

        if side is None:
            return self._fail(
                "unsupported_entry_side:"
                f"raw={raw_side!r}"
            )

        bullish = side == "LONG"
        order_type = str(entry.get("order_type", "")).upper()

        entry_price = self._resolve_entry_price(
            entry,
            context,
            bullish=bullish,
        )
        if entry_price is None:
            return self._fail("entry_price_unresolved")

        sl_result = self._resolve_stop_loss(
            entry_price,
            context=context,
            bullish=bullish,
            pip_size=float(pip_size),
        )
        if sl_result is None:
            debug = dict(
                self._structure_sl_debug
                or {}
            )

            if debug:
                compact = ",".join(
                    f"{key}={value}"
                    for key, value in debug.items()
                    if not isinstance(
                        value,
                        (dict, list, tuple, set),
                    )
                )

                candidate_summary = debug.get(
                    "candidates"
                )

                if isinstance(
                    candidate_summary,
                    list,
                ):
                    compact_candidates = "|".join(
                        str(item)
                        for item in candidate_summary[:8]
                    )

                    if compact_candidates:
                        compact += (
                            ":candidates="
                            + compact_candidates
                        )

                rejected_summary = debug.get(
                    "rejected"
                )

                if isinstance(
                    rejected_summary,
                    list,
                ):
                    compact_rejected = "|".join(
                        str(item)
                        for item in rejected_summary[:8]
                    )

                    if compact_rejected:
                        compact += (
                            ":rejected="
                            + compact_rejected
                        )

                module_summary = debug.get(
                    "modules"
                )

                if isinstance(
                    module_summary,
                    list,
                ):
                    compact_modules = "|".join(
                        str(item)
                        for item in module_summary[:8]
                    )

                    if compact_modules:
                        compact += (
                            ":modules="
                            + compact_modules
                        )

                if compact:
                    return self._fail(
                        "stop_loss_unresolved:"
                        + compact
                    )

            return self._fail(
                "stop_loss_unresolved"
            )
        stop_loss, sl_reason = sl_result

        if bullish and stop_loss >= entry_price:
            return self._fail("invalid_long_stop_loss")
        if not bullish and stop_loss <= entry_price:
            return self._fail("invalid_short_stop_loss")

        try:
            required_stop_pips = max(
                0.0,
                float(minimum_stop_pips),
            )
        except (TypeError, ValueError, OverflowError):
            return self._fail("invalid_minimum_stop_pips")

        actual_stop_pips = (
            abs(entry_price - stop_loss)
            / float(pip_size)
            if pip_size > 0
            else 0.0
        )

        if (
            required_stop_pips > 0
            and actual_stop_pips + 1e-12 < required_stop_pips
        ):
            return self._fail(
                "stop_loss_below_execution_minimum:"
                f"stop_pips={actual_stop_pips:.6f}:"
                f"minimum_stop_pips={required_stop_pips:.6f}"
            )

        tp_result = self._resolve_take_profit(
            entry_price,
            stop_loss,
            context=context,
            bullish=bullish,
            pip_size=float(pip_size),
        )
        if tp_result is None:
            reason = str(
                self._take_profit_debug.get("reason")
                or "take_profit_unresolved"
            )
            return self._fail(reason)
        take_profit, tp_reason = tp_result

        if bullish and take_profit <= entry_price:
            return self._fail("invalid_long_take_profit")
        if not bullish and take_profit >= entry_price:
            return self._fail("invalid_short_take_profit")

        problem_area_allowed, problem_area_diagnostics = (
            self._validate_m1_problem_area_contract(
                context=context,
                entry_price=entry_price,
                take_profit=take_profit,
                bullish=bullish,
            )
        )
        if problem_area_diagnostics:
            context.state["m1_problem_area_contract"] = dict(
                problem_area_diagnostics
            )
        if not problem_area_allowed:
            blocker = dict(problem_area_diagnostics.get("blocking_area") or {})
            return self._fail(
                "first_problem_area_blocks_fixed_rr:"
                f"kind={blocker.get('kind') or '?'}:"
                f"timeframe={blocker.get('timeframe') or '?'}"
            )

        risk_result = self._resolve_risk(
            context=context,
            balance=float(balance),
            entry_price=entry_price,
            stop_loss=stop_loss,
            pip_size=float(pip_size),
            pip_value_per_lot=float(pip_value_per_lot),
            execution_cost_per_lot=float(execution_cost_per_lot),
            lot_step=float(lot_step),
            minimum_lot=float(minimum_lot),
            maximum_lot=(
                float(maximum_lot)
                if maximum_lot is not None
                else None
            ),
        )
        if risk_result is None:
            return self._fail("risk_size_unresolved")

        risk_percent, risk_money, lot, stop_pips, risk_diagnostics = risk_result

        reward_pips = abs(take_profit - entry_price) / float(pip_size)
        gross_reward_per_lot = reward_pips * float(pip_value_per_lot)
        net_reward_per_lot = (
            gross_reward_per_lot - float(execution_cost_per_lot)
        )
        all_in_risk_per_lot = float(
            risk_diagnostics["all_in_risk_per_lot"]
        )
        expected_gross_reward_r = reward_pips / stop_pips
        expected_net_reward_r = (
            net_reward_per_lot / all_in_risk_per_lot
            if all_in_risk_per_lot > 0
            else 0.0
        )

        tp_rule = self.compiled.take_profit
        tp_metadata = (
            dict(tp_rule.get("metadata") or {})
            if isinstance(tp_rule, dict)
            else {}
        )
        raw_minimum_net_r = tp_metadata.get("minimum_r")
        minimum_net_r: float | None = None
        if raw_minimum_net_r is not None:
            try:
                minimum_net_r = float(raw_minimum_net_r)
            except (TypeError, ValueError, OverflowError):
                return self._fail("invalid_minimum_net_reward_r")
            if minimum_net_r <= 0:
                return self._fail("invalid_minimum_net_reward_r")

        reward_validation = {
            "basis": "NET_AFTER_EXECUTION_COSTS",
            "minimum_net_reward_r": minimum_net_r,
            "expected_gross_reward_r": float(expected_gross_reward_r),
            "expected_net_reward_r": float(expected_net_reward_r),
            "gross_reward_per_lot": float(gross_reward_per_lot),
            "net_reward_per_lot": float(net_reward_per_lot),
            "execution_cost_per_lot": float(execution_cost_per_lot),
            "all_in_risk_per_lot": float(all_in_risk_per_lot),
        }
        risk_diagnostics["reward_validation"] = dict(reward_validation)

        if (
            minimum_net_r is not None
            and expected_net_reward_r + 1e-12 < minimum_net_r
        ):
            return self._fail(
                "net_reward_below_minimum_rr:"
                f"net_rr={expected_net_reward_r:.6f}:"
                f"minimum={minimum_net_r:.6f}:"
                f"gross_rr={expected_gross_reward_r:.6f}:"
                f"execution_cost_per_lot={execution_cost_per_lot:.6f}"
            )

        plan = TradePlan(
            strategy_id=self.compiled.strategy_id,
            compilation_id=self.compiled.compilation_id,
            symbol=context.symbol,
            side=side,
            order_type=order_type,
            entry_price=round(entry_price, 10),
            stop_loss=round(stop_loss, 10),
            take_profit=round(take_profit, 10),
            risk_percent=round(risk_percent, 6),
            risk_money=round(risk_money, 2),
            lot=round(lot, 8),
            entry_index=int(entry_index),
            diagnostics={
                "stop_loss_resolution": sl_reason,
                "take_profit_resolution": tp_reason,
                "stop_pips": round(stop_pips, 2),
                "pip_size": pip_size,
                "pip_value_per_lot": pip_value_per_lot,
                "risk_sizing_contract": dict(risk_diagnostics),
                "atr_entry_contract": dict(
                    context.state.get("atr_entry_contract")
                    or {}
                ),
                "first_tap_contract": dict(
                    context.state.get("first_tap_contract")
                    or {}
                ),
                "pending_limit_contract": dict(
                    context.state.get("pending_limit_contract")
                    or {}
                ),
                "scalping_signal_contract": dict(
                    context.state.get("scalping_signal_contract")
                    or {}
                ),
                "m1_problem_area_contract": dict(
                    context.state.get("m1_problem_area_contract")
                    or {}
                ),
            },
        )

        context.trade["resolved_trade_plan"] = plan.to_dict()

        return TradePlanResolution(
            success=True,
            plan=plan,
            reason="trade_plan_resolved",
        )

    @staticmethod
    def _resolve_runtime_side(
        *,
        context: StrategyContext,
        side_aliases: dict[str, str],
    ) -> str | None:
        """
        Resolve concrete LONG/SHORT for generic BOTH/AUTO entries.

        Priority:
        1) explicit trade/state/market direction;
        2) most recent passed entry/POI event snapshot;
        3) other passed event snapshots;
        4) current module_results.

        This prevents a generic TREND result from forcing SHORT while the
        actual M15 reaction/entry POI that triggered ENTRY_READY is BULLISH.
        """

        def normalize(value: Any) -> str | None:
            key = (
                str(value or "")
                .strip()
                .upper()
                .replace("-", "_")
                .replace(" ", "_")
            )
            return side_aliases.get(key)

        direct_candidates: list[Any] = [
            context.state.get("h4_direction"),
            context.trade.get("side"),
            context.trade.get("direction"),
            context.trade.get("bias"),
            context.state.get("side"),
            context.state.get("direction"),
            context.state.get("bias"),
            context.market.get("side"),
            context.market.get("direction"),
            context.market.get("bias"),
        ]

        for candidate in direct_candidates:
            resolved = normalize(candidate)
            if resolved is not None:
                return resolved

        history = context.state.get(
            "event_result_history",
            []
        )

        if isinstance(history, list):
            passed_snapshots = [
                snapshot
                for snapshot in history
                if (
                    isinstance(snapshot, dict)
                    and snapshot.get("success")
                    and snapshot.get("passed")
                )
            ]

            # Entry/POI event that actually passed is the strongest executable
            # direction evidence for a BOTH strategy.
            preferred_snapshots = [
                snapshot
                for snapshot in reversed(
                    passed_snapshots
                )
                if str(
                    snapshot.get("role")
                    or ""
                ).upper()
                in {
                    "ENTRY",
                    "POI",
                }
            ]

            other_snapshots = [
                snapshot
                for snapshot in reversed(
                    passed_snapshots
                )
                if snapshot
                not in preferred_snapshots
            ]

            for snapshot in (
                preferred_snapshots
                + other_snapshots
            ):
                data = dict(
                    snapshot.get("data")
                    or {}
                )
                diagnostics = dict(
                    snapshot.get("diagnostics")
                    or {}
                )

                candidates = [
                    data.get("side"),
                    data.get("direction"),
                    data.get("bias"),
                    data.get("trend"),
                    diagnostics.get("side"),
                    diagnostics.get("direction"),
                    diagnostics.get("bias"),
                    diagnostics.get("trend"),
                ]

                active_zone = data.get(
                    "active_zone"
                )

                if isinstance(
                    active_zone,
                    dict,
                ):
                    candidates.extend(
                        [
                            active_zone.get(
                                "direction"
                            ),
                            active_zone.get(
                                "zone_type"
                            ),
                            active_zone.get(
                                "block_type"
                            ),
                        ]
                    )

                for candidate in candidates:
                    resolved = normalize(
                        candidate
                    )

                    if resolved is not None:
                        return resolved

        # Final fallback: currently retained module results.
        for result in reversed(
            list(
                context.module_results.values()
            )
        ):
            if not (
                result.success
                and result.passed
            ):
                continue

            data = dict(
                result.data or {}
            )
            diagnostics = dict(
                result.diagnostics or {}
            )

            candidates = [
                data.get("side"),
                data.get("direction"),
                data.get("bias"),
                data.get("trend"),
                diagnostics.get("side"),
                diagnostics.get("direction"),
                diagnostics.get("bias"),
                diagnostics.get("trend"),
            ]

            for candidate in candidates:
                resolved = normalize(
                    candidate
                )

                if resolved is not None:
                    return resolved

        return None

    def _entry(self, entry_index: int) -> dict[str, Any] | None:
        for entry in self.compiled.entries:
            if int(entry.get("entry_index", -1)) == int(entry_index):
                return entry
        return None

    @staticmethod
    def _market_number(context: StrategyContext, *keys: str) -> float | None:
        for key in keys:
            value = context.market.get(key)
            if value is None:
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if number > 0:
                return number
        return None

    def _resolve_entry_price(
        self,
        entry: dict[str, Any],
        context: StrategyContext,
        *,
        bullish: bool,
    ) -> float | None:
        order_type = str(entry.get("order_type", "")).upper()
        rule = entry.get("entry_price")

        if order_type == "MARKET":
            if bullish:
                return self._market_number(
                    context, "ask", "price", "close", "bid"
                )
            return self._market_number(
                context, "bid", "price", "close", "ask"
            )

        if isinstance(rule, dict):
            for key in ("value", "price"):
                value = rule.get(key)
                try:
                    if value is not None and float(value) > 0:
                        return float(value)
                except (TypeError, ValueError):
                    pass

            source = str(
                rule.get("source")
                or rule.get("source_type")
                or ""
            ).strip().upper()

            field = str(
                rule.get("field")
                or ""
            ).strip().upper()

            timeframe = str(
                rule.get("timeframe")
                or ""
            ).strip().upper()

            parameters = dict(
                rule.get("parameters")
                or {}
            )

            expression = str(
                parameters.get("expression")
                or rule.get("expression")
                or ""
            ).strip().upper()

            order_block_entry = (
                field in {
                    "ORDER_BLOCK_PROXIMAL_LINE",
                    "FIRST_TAP_ORDER_BLOCK",
                    "ORDER_BLOCK_MIDPOINT",
                }
                or (
                    source == "PARSER_EXPRESSION"
                    and (
                        "ORDER_BLOCK" in expression
                        or "ORDER BLOCK" in expression
                    )
                    and (
                        "PROXIMAL" in expression
                        or "MIDPOINT" in expression
                        or "MID-POINT" in expression
                        or "50%" in expression
                        or "50.0%" in expression
                    )
                )
            )

            order_block_midpoint = bool(
                parameters.get("midpoint")
                or field == "ORDER_BLOCK_MIDPOINT"
                or "MIDPOINT" in expression
                or "MID-POINT" in expression
                or "50%" in expression
                or "50.0%" in expression
            )

            if order_type == "LIMIT" and order_block_entry:
                price = self._resolve_order_block_proximal_entry(
                    context=context,
                    bullish=bullish,
                    timeframe=timeframe,
                    use_midpoint=order_block_midpoint,
                )
                if price is not None:
                    return price

            if (
                order_type == "LIMIT"
                and source == "STRUCTURE"
                and field == "FIRST_TAP_NEW_FVG"
                and str(parameters.get("zone") or "").strip().upper() == "FVG"
                and str(parameters.get("tap") or "").strip().upper() == "FIRST"
            ):
                price = self._resolve_first_tap_fvg_entry(
                    context=context,
                    bullish=bullish,
                    timeframe=timeframe,
                    use_midpoint=bool(parameters.get("midpoint")),
                )

                if price is not None:
                    return price

        return None

    @staticmethod
    def _resolve_order_block_proximal_entry(
        *,
        context: StrategyContext,
        bullish: bool,
        timeframe: str,
        use_midpoint: bool = False,
    ) -> float | None:
        target_direction = "BULLISH" if bullish else "BEARISH"
        zones: list[tuple[str, dict[str, Any]]] = []

        def collect_zones(data: dict[str, Any]) -> list[dict[str, Any]]:
            collected: list[dict[str, Any]] = []
            direct_keys = (
                "active_zone",
                "best_block",
                "order_block",
                "selected_block",
                "block",
                "poi",
                "zone",
            )
            list_keys = (
                "order_blocks",
                "blocks",
                "zones",
                "candidates",
            )

            for key in direct_keys:
                value = data.get(key)
                if isinstance(value, dict):
                    collected.append(dict(value))

            for key in list_keys:
                value = data.get(key)
                if isinstance(value, (list, tuple)):
                    collected.extend(
                        dict(item)
                        for item in value
                        if isinstance(item, dict)
                    )

            raw = data.get("raw")
            if isinstance(raw, dict):
                for zone in collect_zones(dict(raw)):
                    collected.append(zone)

            return collected

        history = context.state.get("event_result_history", [])
        if isinstance(history, list):
            for snapshot in reversed(history):
                if not isinstance(snapshot, dict):
                    continue
                if not (snapshot.get("success") and snapshot.get("passed")):
                    continue

                provider = str(snapshot.get("provider") or "").strip().lower()
                event_name = str(snapshot.get("event_name") or "").strip().upper()
                if provider != "order_block_poi" and event_name != "ORDER_BLOCK":
                    continue

                snapshot_tf = str(snapshot.get("timeframe") or "").strip().upper()
                if timeframe and snapshot_tf and snapshot_tf != timeframe:
                    continue

                zones.append((snapshot_tf, dict(snapshot.get("data") or {})))

        for result in reversed(list(context.module_results.values())):
            if not (result.success and result.passed):
                continue
            if str(result.provider or "").strip().lower() != "order_block_poi":
                continue
            zones.append(("", dict(result.data or {})))

        for zone_timeframe, data in zones:
            if timeframe and zone_timeframe and zone_timeframe != timeframe:
                continue

            candidates = collect_zones(data)

            for zone in candidates:
                direction = str(
                    zone.get("direction")
                    or zone.get("zone_type")
                    or zone.get("block_type")
                    or zone.get("type")
                    or ""
                ).strip().upper()
                if direction and direction not in {
                    target_direction,
                    "LONG" if bullish else "SHORT",
                    "BUY" if bullish else "SELL",
                }:
                    continue

                status = str(zone.get("status") or "").strip().upper()
                if status == "INVALIDATED":
                    continue

                try:
                    low = float(zone.get("low"))
                    high = float(zone.get("high"))
                except (TypeError, ValueError, OverflowError):
                    continue

                if low <= 0 or high <= low:
                    continue

                if use_midpoint:
                    return (low + high) / 2.0

                # Proximal means the boundary closest to current price:
                # upper edge for bullish demand, lower edge for bearish supply.
                return high if bullish else low

        return None

    @staticmethod
    def _resolve_first_tap_fvg_entry(
        *,
        context: StrategyContext,
        bullish: bool,
        timeframe: str,
        use_midpoint: bool,
    ) -> float | None:
        pending_contract = context.state.get(
            "pending_limit_contract",
            {},
        )

        if isinstance(pending_contract, dict) and pending_contract.get(
            "zone_id"
        ):
            contract_timeframe = str(
                pending_contract.get("timeframe") or ""
            ).strip().upper()
            contract_direction = str(
                pending_contract.get("zone_direction") or ""
            ).strip().upper()
            contract_event_type = str(
                pending_contract.get("zone_event_type") or ""
            ).strip().upper()
            contract_status = str(
                pending_contract.get("zone_status") or ""
            ).strip().upper()
            contract_active = bool(
                pending_contract.get("zone_active", True)
            )
            expected_direction = "BULLISH" if bullish else "BEARISH"

            if (
                (not timeframe or not contract_timeframe or contract_timeframe == timeframe)
                and contract_direction == expected_direction
                and contract_event_type == "FVG"
                and contract_status not in {"INVALIDATED", "MITIGATED"}
                and contract_active
            ):
                try:
                    low = float(pending_contract.get("zone_low"))
                    high = float(pending_contract.get("zone_high"))
                except (TypeError, ValueError, OverflowError):
                    low = 0.0
                    high = 0.0

                if low > 0 and high > low:
                    if use_midpoint:
                        return (low + high) / 2.0
                    return high if bullish else low

        history = context.state.get("event_result_history", [])

        if not isinstance(history, list):
            return None

        target_direction = "BULLISH" if bullish else "BEARISH"

        for snapshot in reversed(history):
            if not isinstance(snapshot, dict):
                continue
            if not (snapshot.get("success") and snapshot.get("passed")):
                continue
            if str(snapshot.get("provider") or "").strip().lower() != "fvg_poi":
                continue

            snapshot_tf = str(snapshot.get("timeframe") or "").strip().upper()
            if timeframe and snapshot_tf and snapshot_tf != timeframe:
                continue

            data = dict(snapshot.get("data") or {})
            zones: list[dict[str, Any]] = []

            for key in ("active_zone", "best_fvg"):
                zone = data.get(key)
                if isinstance(zone, dict):
                    zones.append(dict(zone))

            for zone in zones:
                direction = str(
                    zone.get("zone_type")
                    or zone.get("direction")
                    or ""
                ).strip().upper()

                event_type = str(
                    zone.get("event_type")
                    or ""
                ).strip().upper()

                if direction != target_direction:
                    continue
                if event_type and event_type != "FVG":
                    continue

                try:
                    low = float(zone.get("low"))
                    high = float(zone.get("high"))
                except (TypeError, ValueError):
                    continue

                if low <= 0 or high <= 0 or high <= low:
                    continue

                if use_midpoint:
                    return (low + high) / 2.0

                return high if bullish else low

        return None

    @staticmethod
    def _fixed_distance(
        rule: dict[str, Any],
        number: float,
        *,
        pip_size: float,
    ) -> tuple[float, str] | None:
        if number <= 0 or pip_size <= 0:
            return None

        metadata = dict(rule.get("metadata") or {})
        unit = str(metadata.get("unit", "")).strip().upper()

        if unit in {"PIP", "PIPS"}:
            return number * pip_size, "FIXED_DISTANCE_PIPS"

        if unit in {"POINT", "POINTS"}:
            point_size = metadata.get("point_size")
            try:
                point_size = float(point_size)
            except (TypeError, ValueError):
                return None

            if point_size <= 0:
                return None

            return number * point_size, "FIXED_DISTANCE_POINTS"

        # FIXED_DISTANCE without a declared unit is ambiguous.
        return None

    def _resolve_stop_loss(
        self,
        entry_price: float,
        *,
        context: StrategyContext,
        bullish: bool,
        pip_size: float,
    ) -> tuple[float, str] | None:
        rule = self.compiled.stop_loss
        if not isinstance(rule, dict):
            return None

        rule_type = str(rule.get("type", "")).upper()
        value = rule.get("value")

        if rule_type == "STRUCTURE":
            return self._resolve_structure_stop_loss(
                rule=rule,
                context=context,
                entry_price=entry_price,
                bullish=bullish,
                pip_size=pip_size,
            )

        try:
            number = float(value)
        except (TypeError, ValueError):
            return None

        if rule_type == "PERCENT":
            if number <= 0:
                return None
            distance = entry_price * (number / 100.0)
            return (
                entry_price - distance if bullish else entry_price + distance,
                "PERCENT",
            )

        if rule_type in {"PRICE", "FIXED_PRICE", "ABSOLUTE"}:
            if number <= 0:
                return None
            return number, "PRICE"

        if rule_type == "FIXED_DISTANCE":
            resolved = self._fixed_distance(
                rule,
                number,
                pip_size=pip_size,
            )
            if resolved is None:
                return None

            distance, reason = resolved
            return (
                entry_price - distance if bullish else entry_price + distance,
                reason,
            )

        return None

    def _resolve_structure_stop_loss(
        self,
        *,
        rule: dict[str, Any],
        context: StrategyContext,
        entry_price: float,
        bullish: bool,
        pip_size: float,
    ) -> tuple[float, str] | None:
        """
        Resolve STRUCTURE stop loss from point-in-time runtime module results.

        Contract supported:
        - reference.source/source_type == STRUCTURE
        - reference.field == INVALIDATION_LEVEL
        - reference.timeframe (for example M15)
        - parameters.preferred_reference (ENTRY_FVG / ORDER_BLOCK)
        - parameters.fallback_reference
        - optional offset
        """
        self._structure_sl_debug = {
            "rule_type": str(
                rule.get("type") or ""
            ).upper(),
            "entry_price": round(
                float(entry_price),
                10,
            ),
            "bullish": bool(
                bullish
            ),
        }

        scalping_contract = context.state.get(
            "scalping_signal_contract"
        )
        if isinstance(scalping_contract, dict):
            contract_direction = str(
                scalping_contract.get("direction") or ""
            ).strip().upper()
            expected_direction = "BULLISH" if bullish else "BEARISH"
            if contract_direction == expected_direction:
                strategy_model = str(
                    scalping_contract.get("strategy_model") or ""
                ).strip().upper()
                try:
                    contract_stop = float(
                        scalping_contract.get("stop_loss")
                    )
                except (TypeError, ValueError, OverflowError):
                    contract_stop = 0.0
                buffered_contract_model = strategy_model in {
                    "H4_FVG_REJECTION_M15_IFVG_FVG",
                    "NY_ASIA_SWEEP_M5_IFVG_FVG",
                    "ICT_NY_ASIA_SWEEP_M5_MSS_FVG_LIMIT",
                }
                if buffered_contract_model:
                    if strategy_model == "ICT_NY_ASIA_SWEEP_M5_MSS_FVG_LIMIT":
                        try:
                            buffer_ticks = max(
                                0.0,
                                float(
                                    scalping_contract.get("stop_buffer_ticks")
                                    or 0.0
                                ),
                            )
                        except (TypeError, ValueError, OverflowError):
                            buffer_ticks = 0.0
                        try:
                            tick_size = float(
                                context.market.get("tick_size")
                                or pip_size
                            )
                        except (TypeError, ValueError, OverflowError):
                            tick_size = float(pip_size)
                        buffer_distance = buffer_ticks * max(
                            tick_size,
                            0.0,
                        )
                    else:
                        try:
                            buffer_pips = max(
                                0.0,
                                float(
                                    scalping_contract.get("stop_buffer_pips")
                                    or 0.0
                                ),
                            )
                        except (TypeError, ValueError, OverflowError):
                            buffer_pips = 0.0
                        buffer_distance = buffer_pips * float(pip_size)
                    contract_stop = (
                        contract_stop - buffer_distance
                        if bullish
                        else contract_stop + buffer_distance
                    )
                valid_stop = (
                    contract_stop > 0
                    and (
                        contract_stop < entry_price
                        if bullish
                        else contract_stop > entry_price
                    )
                )
                if valid_stop:
                    stop_reference = str(
                        scalping_contract.get("stop_reference") or ""
                    ).strip().upper()
                    immediate_model = (
                        stop_reference == "FIRST_PROBLEM_AREA"
                    )
                    h4_rejection_model = (
                        strategy_model == "H4_FVG_REJECTION_M15_IFVG_FVG"
                    )
                    ny_asia_sweep_model = (
                        strategy_model in {
                            "NY_ASIA_SWEEP_M5_IFVG_FVG",
                            "ICT_NY_ASIA_SWEEP_M5_MSS_FVG_LIMIT",
                        }
                    )
                    self._structure_sl_debug.update({
                        "reason": (
                            "NY_ASIA_SWEEP_M5_EXTREME_CONTRACT"
                            if ny_asia_sweep_model
                            else (
                                "H4_REJECTION_M15_ZONE_CONTRACT"
                                if h4_rejection_model
                                else (
                                    "M1_FIRST_PROBLEM_AREA_CONTRACT"
                                    if immediate_model
                                    else "M1_REJECTION_FRACTAL_CONTRACT"
                                )
                            )
                        ),
                        "signal_time": scalping_contract.get("signal_time"),
                        "confirmation_type": scalping_contract.get(
                            "confirmation_type"
                        ),
                    })
                    return (
                        contract_stop,
                        (
                            "STRUCTURE:M5:ASIA_SWEEP_EXTREME"
                            if ny_asia_sweep_model
                            else (
                                "STRUCTURE:M15:FARTHEST_IFVG_OR_ENTRY_FVG_BOUNDARY"
                                if h4_rejection_model
                                else (
                                    "STRUCTURE:M1:FIRST_PROBLEM_AREA"
                                    if immediate_model
                                    else "STRUCTURE:M1:REJECTION_FRACTAL"
                                )
                            )
                        ),
                    )

        reference = rule.get("reference")

        if not isinstance(reference, dict):
            self._structure_sl_debug[
                "reason"
            ] = "reference_missing"
            return None

        field = str(
            reference.get("field") or ""
        ).strip().upper()

        source = str(
            reference.get("source")
            or reference.get("source_type")
            or ""
        ).strip().upper()

        if (
            source != "STRUCTURE"
            or field != "INVALIDATION_LEVEL"
        ):
            return None

        target_timeframe = str(
            reference.get("timeframe") or ""
        ).strip().upper()

        # Older generic parser versions assigned M15 to every structural SL,
        # even when the complete strategy and the passed Order Block event
        # were M5.  If that timeframe has no causal rates in this context,
        # use the first compiled strategy timeframe that actually does.
        original_target_timeframe = target_timeframe
        if target_timeframe and not self._context_has_rates(
            context,
            target_timeframe,
        ):
            target_timeframe = next(
                (
                    str(candidate).strip().upper()
                    for candidate in self.compiled.timeframes
                    if self._context_has_rates(
                        context,
                        str(candidate).strip().upper(),
                    )
                ),
                "",
            )

        parameters = dict(
            reference.get("parameters") or {}
        )

        preferred = str(
            parameters.get("preferred_reference")
            or ""
        ).strip().upper()

        fallback = str(
            parameters.get("fallback_reference")
            or ""
        ).strip().upper()

        requested_refs = [
            value
            for value in (
                preferred,
                fallback,
                "ORDER_BLOCK",
                "ENTRY_FVG",
            )
            if value
        ]

        # Keep order but remove duplicates.
        requested_refs = list(
            dict.fromkeys(requested_refs)
        )

        self._structure_sl_debug.update(
            {
                "field": field,
                "source": source,
                "target_timeframe": (
                    target_timeframe
                    or "ANY"
                ),
                "original_target_timeframe": (
                    original_target_timeframe
                    or "ANY"
                ),
                "timeframe_fallback_applied": bool(
                    original_target_timeframe
                    and target_timeframe != original_target_timeframe
                ),
                "preferred": (
                    preferred
                    or "NONE"
                ),
                "fallback": (
                    fallback
                    or "NONE"
                ),
            }
        )

        offset_raw = rule.get("offset", 0.0)

        try:
            offset = float(
                0.0
                if offset_raw is None
                else offset_raw
            )
        except (TypeError, ValueError):
            return None

        if offset < 0:
            return None

        # Treat STRUCTURE offset as price distance unless metadata explicitly
        # declares pips/points.
        metadata = dict(
            rule.get("metadata") or {}
        )
        unit = str(
            metadata.get("unit")
            or reference.get("metadata", {}).get("unit")
            if isinstance(reference.get("metadata"), dict)
            else ""
        ).strip().upper()

        if unit in {"PIP", "PIPS"}:
            offset_distance = offset * pip_size
        elif unit in {"POINT", "POINTS"}:
            point_size = metadata.get("point_size")
            try:
                point_size = float(point_size)
            except (TypeError, ValueError):
                point_size = None

            if point_size is None or point_size <= 0:
                return None

            offset_distance = offset * point_size
        else:
            offset_distance = offset

        candidates: list[
            tuple[
                int,
                str,
                dict[str, Any],
            ]
        ] = []

        module_summaries: list[str] = []
        rejected_candidates: list[str] = []

        # First use event-local snapshots. Unlike module_results, these preserve
        # separate H4/H1/M15 executions of the same provider.
        event_history = context.state.get(
            "event_result_history",
            []
        )

        if isinstance(event_history, list):
            for snapshot in reversed(
                event_history
            ):
                if not isinstance(
                    snapshot,
                    dict,
                ):
                    continue

                if not (
                    snapshot.get("success")
                    and snapshot.get("passed")
                ):
                    continue

                snapshot_tf = str(
                    snapshot.get("timeframe")
                    or ""
                ).strip().upper()

                if (
                    target_timeframe
                    and snapshot_tf
                    and snapshot_tf != target_timeframe
                ):
                    continue

                provider = str(
                    snapshot.get("provider")
                    or ""
                ).strip().lower()

                data = dict(
                    snapshot.get("data")
                    or {}
                )

                module_summaries.append(
                    (
                        "EVENT_HISTORY/"
                        f"{provider}"
                        f":passed=True"
                        f":tf={snapshot_tf or '?'}"
                        f":node={snapshot.get('node_id') or '?'}"
                        f":keys={';'.join(sorted(data.keys())[:8])}"
                    )
                )

                zones: list[
                    tuple[str, dict[str, Any]]
                ] = []

                for key, ref_name in (
                    ("active_zone", "ENTRY_FVG"),
                    ("best_fvg", "ENTRY_FVG"),
                    ("best_ifvg", "ENTRY_FVG"),
                    ("best_block", "ORDER_BLOCK"),
                ):
                    value = data.get(
                        key
                    )

                    if isinstance(
                        value,
                        dict,
                    ):
                        zones.append(
                            (
                                ref_name,
                                dict(value),
                            )
                        )

                raw = data.get(
                    "raw"
                )

                if isinstance(
                    raw,
                    dict,
                ):
                    for key, ref_name in (
                        ("active_zone", "ENTRY_FVG"),
                        ("best_fvg", "ENTRY_FVG"),
                        ("best_ifvg", "ENTRY_FVG"),
                        ("best_block", "ORDER_BLOCK"),
                    ):
                        value = raw.get(
                            key
                        )

                        if isinstance(
                            value,
                            dict,
                        ):
                            zones.append(
                                (
                                    ref_name,
                                    dict(value),
                                )
                            )

                if provider == "fvg_poi":
                    active = data.get(
                        "active_zone"
                    )
                    if isinstance(
                        active,
                        dict,
                    ):
                        zones.append(
                            (
                                "ENTRY_FVG",
                                dict(active),
                            )
                        )

                if provider == "order_block_poi":
                    active = data.get(
                        "active_zone"
                    )
                    if isinstance(
                        active,
                        dict,
                    ):
                        zones.append(
                            (
                                "ORDER_BLOCK",
                                dict(active),
                            )
                        )

                for ref_name, zone in zones:
                    try:
                        low = float(
                            zone.get("low")
                        )
                        high = float(
                            zone.get("high")
                        )
                    except (
                        TypeError,
                        ValueError,
                    ):
                        continue

                    if (
                        low <= 0
                        or high <= 0
                        or high <= low
                    ):
                        continue

                    zone_direction = str(
                        zone.get("direction")
                        or zone.get("zone_type")
                        or zone.get("block_type")
                        or ""
                    ).strip().upper()

                    if bullish and zone_direction in {
                        "BEARISH",
                        "SHORT",
                        "SELL",
                    }:
                        rejected_candidates.append(
                            (
                                f"EVENT_HISTORY/{ref_name}"
                                f":reason=direction_mismatch"
                                f":trade=LONG"
                                f":zone={zone_direction or '?'}"
                                f":low={low}"
                                f":high={high}"
                            )
                        )
                        continue

                    if (
                        not bullish
                        and zone_direction in {
                            "BULLISH",
                            "LONG",
                            "BUY",
                        }
                    ):
                        rejected_candidates.append(
                            (
                                f"EVENT_HISTORY/{ref_name}"
                                f":reason=direction_mismatch"
                                f":trade=SHORT"
                                f":zone={zone_direction or '?'}"
                                f":low={low}"
                                f":high={high}"
                            )
                        )
                        continue

                    try:
                        rank = (
                            requested_refs.index(
                                ref_name
                            )
                        )
                    except ValueError:
                        rank = len(
                            requested_refs
                        )

                    candidates.append(
                        (
                            rank,
                            ref_name,
                            zone,
                        )
                    )

        for result in context.module_results.values():
            result_data = dict(
                result.data or {}
            )
            result_diagnostics = dict(
                result.diagnostics or {}
            )

            summary_tf = str(
                result_data.get("timeframe")
                or result_diagnostics.get("timeframe")
                or result_diagnostics.get("selected_timeframe")
                or "?"
            ).upper()

        for result in context.module_results.values():
            result_data = dict(
                result.data or {}
            )
            result_diagnostics = dict(
                result.diagnostics or {}
            )

            summary_tf = str(
                result_data.get("timeframe")
                or result_diagnostics.get("timeframe")
                or result_diagnostics.get("selected_timeframe")
                or "?"
            ).upper()

            module_summaries.append(
                (
                    f"{getattr(result.role, 'value', result.role)}"
                    f"/{result.provider}"
                    f":success={bool(result.success)}"
                    f":passed={bool(result.passed)}"
                    f":tf={summary_tf}"
                    f":keys={';'.join(sorted(result_data.keys())[:8])}"
                )
            )

            if not (
                result.success
                and result.passed
            ):
                continue

            provider = str(
                result.provider or ""
            ).strip().lower()

            data = dict(
                result.data or {}
            )
            diagnostics = dict(
                result.diagnostics or {}
            )

            result_timeframe = str(
                data.get("timeframe")
                or diagnostics.get("timeframe")
                or diagnostics.get("selected_timeframe")
                or ""
            ).strip().upper()

            if (
                target_timeframe
                and result_timeframe
                and result_timeframe != target_timeframe
            ):
                continue

            zones: list[
                tuple[str, dict[str, Any]]
            ] = []

            for key, ref_name in (
                ("active_zone", "ENTRY_FVG"),
                ("best_fvg", "ENTRY_FVG"),
                ("best_ifvg", "ENTRY_FVG"),
                ("best_block", "ORDER_BLOCK"),
            ):
                value = data.get(key)

                if isinstance(value, dict):
                    zones.append(
                        (
                            ref_name,
                            dict(value),
                        )
                    )

            raw = data.get("raw")

            if isinstance(raw, dict):
                for key, ref_name in (
                    ("active_zone", "ENTRY_FVG"),
                    ("best_fvg", "ENTRY_FVG"),
                    ("best_ifvg", "ENTRY_FVG"),
                    ("best_block", "ORDER_BLOCK"),
                ):
                    value = raw.get(key)

                    if isinstance(value, dict):
                        zones.append(
                            (
                                ref_name,
                                dict(value),
                            )
                        )

            # Provider identity is useful when normalized data omitted best_*.
            if provider == "order_block_poi":
                active = data.get("active_zone")
                if isinstance(active, dict):
                    zones.append(
                        (
                            "ORDER_BLOCK",
                            dict(active),
                        )
                    )

            if provider == "fvg_poi":
                active = data.get("active_zone")
                if isinstance(active, dict):
                    zones.append(
                        (
                            "ENTRY_FVG",
                            dict(active),
                        )
                    )

            for ref_name, zone in zones:
                try:
                    low = float(
                        zone.get("low")
                    )
                    high = float(
                        zone.get("high")
                    )
                except (TypeError, ValueError):
                    continue

                if (
                    low <= 0
                    or high <= 0
                    or high <= low
                ):
                    continue

                # Direction must agree with the concrete trade when available.
                zone_direction = str(
                    zone.get("direction")
                    or zone.get("zone_type")
                    or zone.get("block_type")
                    or ""
                ).strip().upper()

                if bullish and zone_direction in {
                    "BEARISH",
                    "SHORT",
                    "SELL",
                }:
                    rejected_candidates.append(
                        (
                            f"MODULE_RESULT/{ref_name}"
                            f":reason=direction_mismatch"
                            f":trade=LONG"
                            f":zone={zone_direction or '?'}"
                            f":low={low}"
                            f":high={high}"
                        )
                    )
                    continue

                if (
                    not bullish
                    and zone_direction in {
                        "BULLISH",
                        "LONG",
                        "BUY",
                    }
                ):
                    rejected_candidates.append(
                        (
                            f"MODULE_RESULT/{ref_name}"
                            f":reason=direction_mismatch"
                            f":trade=SHORT"
                            f":zone={zone_direction or '?'}"
                            f":low={low}"
                            f":high={high}"
                        )
                    )
                    continue

                try:
                    rank = (
                        requested_refs.index(
                            ref_name
                        )
                    )
                except ValueError:
                    rank = len(
                        requested_refs
                    )

                candidates.append(
                    (
                        rank,
                        ref_name,
                        zone,
                    )
                )

        self._structure_sl_debug[
            "candidate_count"
        ] = len(
            candidates
        )

        self._structure_sl_debug[
            "modules"
        ] = module_summaries

        candidate_summaries: list[str] = []

        for rank, ref_name, zone in candidates[:8]:
            candidate_summaries.append(
                (
                    f"{ref_name}"
                    f":rank={rank}"
                    f":type={zone.get('zone_type') or zone.get('direction') or zone.get('block_type') or '?'}"
                    f":low={zone.get('low')}"
                    f":high={zone.get('high')}"
                    f":status={zone.get('status') or '?'}"
                    f":active={zone.get('active')}"
                )
            )

        self._structure_sl_debug[
            "candidates"
        ] = candidate_summaries

        self._structure_sl_debug[
            "rejected"
        ] = rejected_candidates

        if not candidates:
            self._structure_sl_debug[
                "reason"
            ] = "no_structure_candidates"
            return None

        candidates.sort(
            key=lambda item: item[0]
        )

        for _rank, ref_name, zone in candidates:
            low = float(
                zone["low"]
            )
            high = float(
                zone["high"]
            )

            if bullish:
                stop = (
                    low
                    - offset_distance
                )

                if stop <= 0 or stop >= entry_price:
                    continue

            else:
                stop = (
                    high
                    + offset_distance
                )

                if stop <= entry_price:
                    continue

            return (
                stop,
                (
                    "STRUCTURE:"
                    f"{ref_name}:"
                    f"{target_timeframe or 'ANY'}:"
                    "INVALIDATION_LEVEL"
                ),
            )

        return None

    @staticmethod
    def _context_has_rates(
        context: StrategyContext,
        timeframe: str,
    ) -> bool:
        rates = context.rates_by_timeframe.get(
            str(timeframe or "").strip().upper()
        )
        if rates is None:
            return False

        empty = getattr(rates, "empty", None)
        if empty is not None:
            try:
                return not bool(empty)
            except Exception:
                return False

        try:
            return len(rates) > 0
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _validate_m1_problem_area_contract(
        *,
        context: StrategyContext,
        entry_price: float,
        take_profit: float,
        bullish: bool,
    ) -> tuple[bool, dict[str, Any]]:
        contract = context.state.get("scalping_signal_contract")
        if not isinstance(contract, dict):
            return True, {}
        if str(contract.get("strategy_model") or "").upper() != (
            "M1_IFVG_FVG_IMMEDIATE_ENTRY"
        ):
            return True, {}

        expected_direction = "BULLISH" if bullish else "BEARISH"
        htf_context = dict(contract.get("htf_context") or {})
        htf_direction = str(htf_context.get("direction") or "").upper()
        policy = dict(contract.get("problem_area_policy") or {})
        htf_timeframes = {
            str(item).upper()
            for item in (policy.get("htf_timeframes") or ("H1", "M30", "M15"))
        }

        obstacles: list[dict[str, Any]] = []
        for raw in contract.get("problem_areas") or []:
            if not isinstance(raw, dict):
                continue
            area = dict(raw)
            try:
                low = float(area.get("low"))
                high = float(area.get("high"))
            except (TypeError, ValueError, OverflowError):
                continue
            if high < low:
                low, high = high, low

            kind = str(area.get("kind") or "").upper()
            direction = str(area.get("direction") or "").upper()
            is_opposing = (
                (bullish and (kind == "SWING_HIGH" or direction == "BEARISH"))
                or (
                    not bullish
                    and (kind == "SWING_LOW" or direction == "BULLISH")
                )
            )
            if not is_opposing:
                continue

            # A problem area must be strictly ahead of the actual MARKET
            # entry and must begin before the fixed 1R target.
            if bullish:
                if low <= entry_price or low >= take_profit:
                    continue
                distance = low - entry_price
            else:
                if high >= entry_price or high <= take_profit:
                    continue
                distance = entry_price - high

            area.update({
                "low": low,
                "high": high,
                "distance_from_entry": float(distance),
            })
            obstacles.append(area)

        obstacles.sort(key=lambda item: float(item["distance_from_entry"]))
        first_area = dict(obstacles[0]) if obstacles else None
        opposing_htf_zones = [
            dict(area)
            for area in obstacles
            if (
                str(area.get("timeframe") or "").upper() in htf_timeframes
                and str(area.get("kind") or "").upper()
                in {"FVG", "ORDER_BLOCK"}
            )
        ]
        direction_matches = htf_direction == expected_direction
        allowed = (
            not obstacles
            or (direction_matches and not opposing_htf_zones)
        )
        blocking_area = (
            dict(opposing_htf_zones[0])
            if opposing_htf_zones
            else (dict(first_area) if first_area and not direction_matches else None)
        )
        return allowed, {
            "policy": "FIXED_1R_WITH_HTF_PERMISSION",
            "expected_direction": expected_direction,
            "htf_direction": htf_direction,
            "htf_direction_matches": direction_matches,
            "entry_price": float(entry_price),
            "take_profit": float(take_profit),
            "first_problem_area": first_area,
            "opposing_htf_zones_before_tp": opposing_htf_zones,
            "blocking_area": blocking_area,
            "allowed": bool(allowed),
        }

    def _resolve_take_profit(
        self,
        entry_price: float,
        stop_loss: float,
        *,
        context: StrategyContext,
        bullish: bool,
        pip_size: float,
    ) -> tuple[float, str] | None:
        self._take_profit_debug = {}
        rule = self.compiled.take_profit
        if not isinstance(rule, dict):
            return None

        rule_type = str(rule.get("type", "")).upper()
        value = rule.get("value")

        try:
            number = float(value)
        except (TypeError, ValueError):
            return None

        if rule_type == "R_MULTIPLE":
            if number <= 0:
                return None
            risk_distance = abs(entry_price - stop_loss)
            if risk_distance <= 0:
                return None

            metadata = dict(rule.get("metadata") or {})
            if metadata.get("target_policy") == "SESSION_LIQUIDITY":
                return self._resolve_session_liquidity_take_profit(
                    context=context,
                    metadata=metadata,
                    entry_price=entry_price,
                    risk_distance=risk_distance,
                    bullish=bullish,
                )

            target_distance = risk_distance * number
            return (
                entry_price + target_distance
                if bullish
                else entry_price - target_distance,
                "R_MULTIPLE",
            )

        if rule_type == "PERCENT":
            if number <= 0:
                return None
            distance = entry_price * (number / 100.0)
            return (
                entry_price + distance if bullish else entry_price - distance,
                "PERCENT",
            )

        if rule_type in {"PRICE", "FIXED_PRICE", "ABSOLUTE"}:
            if number <= 0:
                return None
            return number, "PRICE"

        if rule_type == "FIXED_DISTANCE":
            resolved = self._fixed_distance(
                rule,
                number,
                pip_size=pip_size,
            )
            if resolved is None:
                return None

            distance, reason = resolved
            return (
                entry_price + distance if bullish else entry_price - distance,
                reason,
            )

        return None

    def _resolve_session_liquidity_take_profit(
        self,
        *,
        context: StrategyContext,
        metadata: dict[str, Any],
        entry_price: float,
        risk_distance: float,
        bullish: bool,
    ) -> tuple[float, str] | None:
        try:
            minimum_r = float(metadata.get("minimum_r"))
            base_r = float(metadata.get("base_r"))
            maximum_r = float(metadata.get("maximum_r"))
        except (TypeError, ValueError):
            self._take_profit_debug["reason"] = (
                "take_profit_session_rr_contract_invalid"
            )
            return None

        if not (0 < minimum_r <= base_r <= maximum_r <= 2.0):
            self._take_profit_debug["reason"] = (
                "take_profit_session_rr_contract_invalid"
            )
            return None

        rates = context.get_rates("M15")
        if rates is None or (hasattr(rates, "empty") and bool(rates.empty)):
            self._take_profit_debug["reason"] = "session_liquidity_rates_missing"
            return None

        state = SessionService(
            SessionServiceConfig(use_last_closed_candle=False)
        ).analyze(rates=rates)
        allowed_sources = {
            str(item or "").strip().upper()
            for item in (metadata.get("liquidity_sources") or [])
        }
        completed_only = bool(metadata.get("completed_sessions_only", True))
        candidates: list[tuple[str, float]] = []

        for name, zone in (
            ("ASIA", state.asia),
            ("LONDON", state.london),
            ("NEW_YORK", state.new_york),
        ):
            if zone is None or (completed_only and zone.active):
                continue
            for suffix, price in (("HIGH", zone.high), ("LOW", zone.low)):
                source = f"{name}_{suffix}"
                if source in allowed_sources:
                    candidates.append((source, float(price)))

        if state.previous_day is not None:
            for source, price in (
                ("PREVIOUS_DAY_HIGH", state.previous_day.high),
                ("PREVIOUS_DAY_LOW", state.previous_day.low),
            ):
                if source in allowed_sources:
                    candidates.append((source, float(price)))

        directional = [
            (source, price)
            for source, price in candidates
            if (
                (
                    source.endswith("_HIGH")
                    and price > entry_price
                )
                if bullish
                else (
                    source.endswith("_LOW")
                    and price < entry_price
                )
            )
        ]
        if not directional:
            self._take_profit_debug["reason"] = (
                "session_liquidity_directional_target_missing"
            )
            return None

        source, liquidity_price = min(
            directional,
            key=lambda item: abs(item[1] - entry_price),
        )
        liquidity_r = abs(liquidity_price - entry_price) / risk_distance
        self._take_profit_debug.update(
            {
                "source": source,
                "liquidity_price": liquidity_price,
                "liquidity_r": liquidity_r,
                "minimum_r": minimum_r,
                "maximum_r": maximum_r,
            }
        )

        if liquidity_r < minimum_r:
            self._take_profit_debug["reason"] = (
                "session_liquidity_below_minimum_rr:"
                f"source={source}:rr={liquidity_r:.6f}:minimum={minimum_r:.6f}"
            )
            return None

        selected_r = min(liquidity_r, base_r, maximum_r)
        take_profit = (
            entry_price + risk_distance * selected_r
            if bullish
            else entry_price - risk_distance * selected_r
        )
        return (
            take_profit,
            "SESSION_LIQUIDITY:"
            f"{source}:available_r={liquidity_r:.6f}:selected_r={selected_r:.6f}",
        )

    def _resolve_risk(
        self,
        *,
        context: StrategyContext,
        balance: float,
        entry_price: float,
        stop_loss: float,
        pip_size: float,
        pip_value_per_lot: float,
        execution_cost_per_lot: float,
        lot_step: float,
        minimum_lot: float,
        maximum_lot: float | None,
    ) -> tuple[float, float, float, float, dict[str, Any]] | None:
        rule = self.compiled.risk
        if not isinstance(rule, dict):
            return None

        sizing_type = str(
            rule.get("sizing_type", rule.get("type", ""))
        ).upper()

        try:
            risk_percent = float(rule.get("value"))
        except (TypeError, ValueError):
            return None

        supported_balance_types = {
            "BALANCE_PERCENT",
            "PERCENT",
            "BALANCE_PCT",
        }

        supported_equity_types = {
            "EQUITY_PERCENT",
            "EQUITY_PCT",
        }

        if (
            sizing_type not in supported_balance_types
            and sizing_type not in supported_equity_types
        ):
            return None

        risk_base = float(balance)
        risk_base_source = "BALANCE"

        if sizing_type in supported_equity_types:
            equity_candidates = [
                context.statistics.get("equity"),
                context.state.get("equity"),
                context.trade.get("equity"),
                context.market.get("equity"),
                context.statistics.get("current_equity"),
                context.state.get("current_equity"),
            ]

            resolved_equity: float | None = None

            for candidate in equity_candidates:
                try:
                    number = float(candidate)
                except (TypeError, ValueError):
                    continue

                if number > 0:
                    resolved_equity = number
                    break

            if resolved_equity is not None:
                risk_base = resolved_equity
                risk_base_source = "EQUITY"
            else:
                # Historical runner supplies current account balance. With no
                # unrealized P/L exposed in StrategyContext, this is the safe
                # point-in-time proxy for equity.
                risk_base = float(balance)
                risk_base_source = "EQUITY_FALLBACK_BALANCE"

        if (
            risk_base <= 0
            or risk_percent <= 0
            or pip_size <= 0
            or pip_value_per_lot <= 0
            or execution_cost_per_lot < 0
            or lot_step <= 0
            or minimum_lot <= 0
            or (maximum_lot is not None and maximum_lot < minimum_lot)
        ):
            return None

        stop_distance = abs(entry_price - stop_loss)
        if stop_distance <= 0:
            return None

        stop_pips = stop_distance / pip_size
        if stop_pips <= 0:
            return None

        # `risk_money` is the complete loss budget at Stop Loss. Execution
        # costs must be included in that budget instead of being added after
        # sizing; otherwise a nominal 1% trade can lose materially more than
        # 1% when the structural stop is narrow.
        risk_money = risk_base * (risk_percent / 100.0)
        price_risk_per_lot = stop_pips * pip_value_per_lot
        all_in_risk_per_lot = price_risk_per_lot + execution_cost_per_lot
        if all_in_risk_per_lot <= 0:
            return None

        raw_lot = risk_money / all_in_risk_per_lot
        lot_steps = math.floor((raw_lot + 1e-12) / lot_step)
        lot = lot_steps * lot_step

        if maximum_lot is not None:
            maximum_steps = math.floor((maximum_lot + 1e-12) / lot_step)
            lot = min(lot, maximum_steps * lot_step)

        if lot + 1e-12 < minimum_lot:
            return None

        price_risk_money = price_risk_per_lot * lot
        estimated_cost_money = execution_cost_per_lot * lot
        all_in_stop_risk_money = price_risk_money + estimated_cost_money
        all_in_stop_risk_percent = (
            all_in_stop_risk_money / risk_base * 100.0
        )

        risk_diagnostics = {
            "policy": "ALL_IN_STOP_INCLUDES_EXECUTION_COSTS",
            "lot_rounding": "DOWN_TO_BROKER_STEP",
            "risk_budget_money": float(risk_money),
            "price_risk_per_lot": float(price_risk_per_lot),
            "execution_cost_per_lot": float(execution_cost_per_lot),
            "all_in_risk_per_lot": float(all_in_risk_per_lot),
            "raw_lot": float(raw_lot),
            "lot_step": float(lot_step),
            "minimum_lot": float(minimum_lot),
            "maximum_lot": (
                float(maximum_lot)
                if maximum_lot is not None
                else None
            ),
            "resolved_lot": float(lot),
            "price_risk_money": float(price_risk_money),
            "estimated_cost_money": float(estimated_cost_money),
            "all_in_stop_risk_money": float(all_in_stop_risk_money),
            "all_in_stop_risk_percent": float(all_in_stop_risk_percent),
        }

        context.trade["risk_resolution"] = {
            "sizing_type": sizing_type,
            "risk_base": float(risk_base),
            "risk_base_source": risk_base_source,
            "risk_percent": float(risk_percent),
            "risk_money": float(risk_money),
            "stop_pips": float(stop_pips),
            "risk_sizing_contract": dict(risk_diagnostics),
        }

        if lot <= 0:
            return None

        return risk_percent, risk_money, lot, stop_pips, risk_diagnostics

    @staticmethod
    def _fail(reason: str) -> TradePlanResolution:
        return TradePlanResolution(
            success=False,
            plan=None,
            reason=reason,
        )
