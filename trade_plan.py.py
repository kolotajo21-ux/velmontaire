from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.context import StrategyContext
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

    def resolve(
        self,
        context: StrategyContext,
        *,
        balance: float,
        entry_index: int,
        pip_size: float = 0.0001,
        pip_value_per_lot: float = 10.0,
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

        # Some generic entries intentionally leave side unresolved until the
        # signal pipeline determines direction. Recover it from point-in-time
        # runtime state/results rather than failing on an empty compiled field.
        if side is None:
            candidates: list[Any] = [
                context.trade.get("side"),
                context.trade.get("direction"),
                context.state.get("side"),
                context.state.get("direction"),
                context.market.get("side"),
                context.market.get("direction"),
            ]

            for result in reversed(
                list(context.module_results.values())
            ):
                if not (
                    result.success
                    and result.passed
                ):
                    continue

                candidates.extend(
                    (
                        result.data.get("side"),
                        result.data.get("direction"),
                        result.diagnostics.get("side"),
                        result.diagnostics.get("direction"),
                    )
                )

            for candidate in candidates:
                candidate_key = (
                    str(candidate or "")
                    .strip()
                    .upper()
                    .replace("-", "_")
                    .replace(" ", "_")
                )

                resolved = side_aliases.get(
                    candidate_key
                )

                if resolved is not None:
                    side = resolved
                    break

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
            bullish=bullish,
            pip_size=float(pip_size),
        )
        if sl_result is None:
            return self._fail("stop_loss_unresolved")
        stop_loss, sl_reason = sl_result

        if bullish and stop_loss >= entry_price:
            return self._fail("invalid_long_stop_loss")
        if not bullish and stop_loss <= entry_price:
            return self._fail("invalid_short_stop_loss")

        tp_result = self._resolve_take_profit(
            entry_price,
            stop_loss,
            bullish=bullish,
            pip_size=float(pip_size),
        )
        if tp_result is None:
            return self._fail("take_profit_unresolved")
        take_profit, tp_reason = tp_result

        if bullish and take_profit <= entry_price:
            return self._fail("invalid_long_take_profit")
        if not bullish and take_profit >= entry_price:
            return self._fail("invalid_short_take_profit")

        risk_result = self._resolve_risk(
            balance=float(balance),
            entry_price=entry_price,
            stop_loss=stop_loss,
            pip_size=float(pip_size),
            pip_value_per_lot=float(pip_value_per_lot),
        )
        if risk_result is None:
            return self._fail("risk_size_unresolved")

        risk_percent, risk_money, lot, stop_pips = risk_result

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
            lot=round(lot, 2),
            entry_index=int(entry_index),
            diagnostics={
                "stop_loss_resolution": sl_reason,
                "take_profit_resolution": tp_reason,
                "stop_pips": round(stop_pips, 2),
                "pip_size": pip_size,
                "pip_value_per_lot": pip_value_per_lot,
            },
        )

        context.trade["resolved_trade_plan"] = plan.to_dict()

        return TradePlanResolution(
            success=True,
            plan=plan,
            reason="trade_plan_resolved",
        )

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
        bullish: bool,
        pip_size: float,
    ) -> tuple[float, str] | None:
        rule = self.compiled.stop_loss
        if not isinstance(rule, dict):
            return None

        rule_type = str(rule.get("type", "")).upper()
        value = rule.get("value")

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

    def _resolve_take_profit(
        self,
        entry_price: float,
        stop_loss: float,
        *,
        bullish: bool,
        pip_size: float,
    ) -> tuple[float, str] | None:
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

    def _resolve_risk(
        self,
        *,
        balance: float,
        entry_price: float,
        stop_loss: float,
        pip_size: float,
        pip_value_per_lot: float,
    ) -> tuple[float, float, float, float] | None:
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

        if sizing_type not in {
            "BALANCE_PERCENT",
            "PERCENT",
            "BALANCE_PCT",
        }:
            return None

        if (
            balance <= 0
            or risk_percent <= 0
            or pip_size <= 0
            or pip_value_per_lot <= 0
        ):
            return None

        stop_distance = abs(entry_price - stop_loss)
        if stop_distance <= 0:
            return None

        stop_pips = stop_distance / pip_size
        if stop_pips <= 0:
            return None

        risk_money = balance * (risk_percent / 100.0)
        lot = risk_money / (stop_pips * pip_value_per_lot)

        if lot <= 0:
            return None

        return risk_percent, risk_money, lot, stop_pips

    @staticmethod
    def _fail(reason: str) -> TradePlanResolution:
        return TradePlanResolution(
            success=False,
            plan=None,
            reason=reason,
        )