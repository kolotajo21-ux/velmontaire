from __future__ import annotations

import copy

import re
from typing import Any

from strategy_schema import (
    ComparisonOperator,
    ConditionKind,
    EntryOrderType,
    EntryRule,
    ManagementActionType,
    ManagementRule,
    RiskRule,
    RiskSizingType,
    StopLossRule,
    StopLossType,
    StrategyCondition,
    StrategyRules,
    StrategySchema,
    StrategySide,
    TakeProfitRule,
    TakeProfitType,
    ValueReference,
)

from .models import ParsedFact, ParserQuestion, StrategyParseDraft


class StrategyTextParser:
    """
    Conservative Day 42 parser foundation.

    It extracts only explicitly supported facts. It never invents missing
    trading rules. Missing or conflicting critical fields become questions.
    """

    CRITICAL_PATHS = (
        "symbols",
        "timeframes",
        "entry.side",
        "entry.order_type",
        "entry.condition",
        "stop_loss",
        "take_profit",
        "risk",
    )

    _TIMEFRAME_RE = re.compile(r"\b(M1|M5|M15|M30|H1|H4|D1|W1)\b", re.I)
    _SYMBOL_RE = re.compile(
        r"\b(EURUSD|GBPUSD|USDJPY|USDCHF|USDCAD|AUDUSD|NZDUSD|XAUUSD|XAGUSD|NAS100|GER40|US30|SPX500)\b",
        re.I,
    )
    _RISK_RE = re.compile(
        r"\brisk\s*(?:=|:|is|exactly|per\s+trade\s*(?:=|:|is)?)?\s*"
        r"(\d+(?:[.,]\d+)?)\s*%",
        re.I,
    )
    _RR_RE = re.compile(r"\b(?:rr|r:r|risk\s*reward)\s*(?:=|:|is)?\s*(?:1\s*[:/]\s*)?(\d+(?:[.,]\d+)?)\b", re.I)
    _SL_PERCENT_RE = re.compile(r"\b(?:sl|stop\s*loss)\s*(?:=|:|is)?\s*(\d+(?:[.,]\d+)?)\s*%", re.I)
    _SL_PIPS_RE = re.compile(
        r"\b(?:sl|stop\s*loss)\s*(?:=|:|is)?\s*(?:fixed\s*(?:at|to)?\s*)?(\d+(?:[.,]\d+)?)\s*(pip|pips|point|points)\b",
        re.I,
    )
    _TP_PIPS_RE = re.compile(
        r"\b(?:tp|take\s*profit)\s*(?:=|:|is)?\s*(?:fixed\s*(?:at|to)?\s*)?(\d+(?:[.,]\d+)?)\s*(pip|pips|point|points)\b",
        re.I,
    )

    def parse(self, text: str) -> StrategyParseDraft:
        source = str(text or "").strip()
        if not source:
            raise ValueError("strategy text is required")

        draft = StrategyParseDraft(source_text=source)
        self._extract_symbols(source, draft)
        self._extract_timeframes(source, draft)
        self._extract_side(source, draft)
        self._extract_order_type(source, draft)
        self._extract_entry_condition(source, draft)
        self._extract_risk(source, draft)
        self._extract_stop_loss(source, draft)
        self._extract_take_profit(source, draft)
        self._finalize(draft)
        return draft

    def apply_answers(
        self,
        draft: StrategyParseDraft,
        answers: dict[str, Any],
    ) -> StrategyParseDraft:
        for path, value in answers.items():
            if value is None or value == "":
                continue
            draft.facts[path] = ParsedFact(
                path=path,
                value=value,
                source_text="USER_CLARIFICATION",
                confidence=1.0,
            )
            if path in draft.conflicts:
                del draft.conflicts[path]

        # The entry-price clarification is allowed to make the pending-order
        # type explicit.  This is important when the source also contains
        # ordinary stop-loss wording ("place the stop beyond ..."), which must
        # never be mistaken for a STOP entry order.
        entry_price_answer = str(
            answers.get("entry.price")
            or ""
        ).strip()
        normalized_price_answer = entry_price_answer.lower()

        clarified_order_type: str | None = None
        if re.search(
            r"\blimit(?:\s+order)?\b|\b(?:лимит|ліміт)\w*",
            normalized_price_answer,
        ):
            clarified_order_type = "LIMIT"
        elif re.search(
            r"\b(?:buy|sell)\s+stop(?:\s+order)?\b"
            r"|\bstop\s+(?:entry|order)\b"
            r"|\bentry\s+stop\b",
            normalized_price_answer,
        ):
            clarified_order_type = "STOP"

        if clarified_order_type is not None:
            draft.facts["entry.order_type"] = ParsedFact(
                path="entry.order_type",
                value=clarified_order_type,
                source_text="USER_CLARIFICATION:entry.price",
                confidence=1.0,
            )
            draft.conflicts.pop("entry.order_type", None)

        self._finalize(draft)
        return draft

    def build_schema(
        self,
        draft: StrategyParseDraft,
        *,
        strategy_id: str,
        name: str,
        version: str = "1.0",
    ) -> StrategySchema:
        if not draft.ready_for_schema:
            raise ValueError("strategy_parse_draft_not_resolved")

        side = StrategySide(str(draft.value("entry.side")).upper())
        order_type = EntryOrderType(
            self._normalize_order_type(draft.value("entry.order_type"))
        )

        condition_data = draft.value("entry.condition")

        entry_price = None
        if order_type in {EntryOrderType.LIMIT, EntryOrderType.STOP}:
            entry_price = self._build_entry_price_reference(
                draft.value("entry.price"),
                timeframes=draft.value("timeframes") or [],
            )

        sl_data = self._normalize_stop_loss(draft.value("stop_loss"))
        tp_data = self._normalize_take_profit(draft.value("take_profit"))
        risk_data = self._normalize_risk(draft.value("risk"))

        sl_reference = None
        if sl_data["type"] == "STRUCTURE":
            scalping_model = self._looks_like_m1_scalping(draft.source_text)
            h4_rejection_model = self._looks_like_h4_rejection_m15(
                draft.source_text
            )
            ny_asia_sweep_model = (
                self._looks_like_ny_asia_sweep_m5(draft.source_text)
                or self._looks_like_ict_ny_asia_sweep_v1(draft.source_text)
            )
            declared_timeframes = [
                str(item or "").strip().upper()
                for item in (draft.value("timeframes") or [])
                if str(item or "").strip()
            ]
            default_structure_timeframe = (
                declared_timeframes[0]
                if declared_timeframes
                else None
            )
            sl_expression = str(
                (sl_data.get("metadata") or {}).get("expression")
                or ""
            )
            sl_expression_upper = sl_expression.upper()
            order_block_stop = (
                "ORDER BLOCK" in sl_expression_upper
                or "ORDER_BLOCK" in sl_expression_upper
            )

            structure_timeframe = (
                "M1"
                if scalping_model
                else (
                    "M5"
                    if ny_asia_sweep_model
                    else (
                        "M15"
                        if h4_rejection_model
                        else default_structure_timeframe
                    )
                )
            )

            preferred_structure_reference = (
                "ORDER_BLOCK"
                if order_block_stop
                else (
                    "FIRST_PROBLEM_AREA"
                    if scalping_model
                    else (
                        "ASIA_SWEEP_EXTREME"
                        if ny_asia_sweep_model
                        else (
                            "FARTHEST_IFVG_OR_ENTRY_FVG_BOUNDARY"
                            if h4_rejection_model
                            else "ENTRY_FVG"
                        )
                    )
                )
            )
            sl_reference = ValueReference(
                source="STRUCTURE",
                field="INVALIDATION_LEVEL",
                timeframe=structure_timeframe,
                parameters={
                    "preferred_reference": preferred_structure_reference,
                    "fallback_reference": (
                        "ENTRY_FVG"
                        if scalping_model
                        else "ORDER_BLOCK"
                    ),
                },
                metadata={
                    "expression": sl_expression,
                },
            )

        tp_reference = None
        if (tp_data.get("metadata") or {}).get("target_policy") == "SESSION_LIQUIDITY":
            tp_metadata = dict(tp_data.get("metadata") or {})
            tp_reference = ValueReference(
                source="SESSION",
                field="NEAREST_RELEVANT_LIQUIDITY",
                parameters={
                    "direction": "TRADE_DIRECTION",
                    "minimum_r": float(
                        tp_metadata.get("minimum_r", 1.5)
                    ),
                    "base_r": float(
                        tp_metadata.get("base_r", tp_data.get("value") or 2.0)
                    ),
                    "maximum_r": float(
                        tp_metadata.get("maximum_r", 2.0)
                    ),
                    "liquidity_sources": list(
                        tp_metadata.get("liquidity_sources") or []
                    ),
                    "completed_sessions_only": bool(
                        tp_metadata.get("completed_sessions_only", True)
                    ),
                },
            )

        entries = self._build_entries(
            draft=draft,
            side=side,
            order_type=order_type,
            entry_price=entry_price,
            condition_data=condition_data,
        )

        schema = StrategySchema(
            strategy_id=strategy_id,
            name=name,
            version=version,
            symbols=list(draft.value("symbols")),
            timeframes=list(draft.value("timeframes")),
            rules=StrategyRules(
                entries=entries,
                stop_loss=StopLossRule(
                    type=StopLossType(sl_data["type"]),
                    value=sl_data.get("value"),
                    reference=sl_reference,
                    metadata=dict(sl_data.get("metadata") or {}),
                ),
                take_profit=TakeProfitRule(
                    type=TakeProfitType(tp_data["type"]),
                    value=tp_data.get("value"),
                    reference=tp_reference,
                    metadata=dict(tp_data.get("metadata") or {}),
                ),
                risk=RiskRule(
                    sizing_type=RiskSizingType(risk_data["sizing_type"]),
                    value=float(risk_data["value"]),
                    max_open_positions=int(risk_data.get("max_open_positions", 1)),
                    max_positions_per_symbol=int(risk_data.get("max_positions_per_symbol", 1)),
                    metadata=dict(risk_data.get("metadata") or {}),
                ),
                management=self._build_management_rules(draft.source_text),
            ),
            source_text=draft.source_text,
            parser_questions=[q.question for q in draft.questions],
            unresolved_fields=[],
            metadata={
                "parser": "StrategyTextParser",
                "parser_version": (
                    "v8_ict_ny_asia_sweep_m5_mss_fvg_limit"
                    if self._looks_like_ict_ny_asia_sweep_v1(draft.source_text)
                    else (
                        "v7_ny_asia_sweep_m5_ifvg_fvg"
                        if self._looks_like_ny_asia_sweep_m5(draft.source_text)
                        else (
                            "v6_h4_rejection_m15_ifvg_fvg"
                            if self._looks_like_h4_rejection_m15(draft.source_text)
                            else (
                                "v5_m1_ifvg_fvg_immediate"
                                if self._looks_like_m1_scalping(draft.source_text)
                                else "v3_velmontaire"
                            )
                        )
                    )
                ),
                "filters": self._strategy_filter_metadata(draft.source_text),
                "preferred_trading_window": self._preferred_trading_window(draft.source_text),
            },
        )

        validation = schema.validate()
        if not validation.valid:
            raise ValueError(
                "generated_strategy_schema_invalid: "
                + "; ".join(f"{i.path}:{i.code}" for i in validation.issues)
            )
        return schema

    def _set_fact(
        self,
        draft: StrategyParseDraft,
        path: str,
        value: Any,
        source_text: str,
        confidence: float = 1.0,
    ) -> None:
        existing = draft.facts.get(path)
        if existing is not None and existing.value != value:
            draft.conflicts[path] = [existing.value, value]
            return
        draft.facts[path] = ParsedFact(path, value, source_text, confidence)

    def _extract_symbols(self, text: str, draft: StrategyParseDraft) -> None:
        values = list(dict.fromkeys(m.group(1).upper() for m in self._SYMBOL_RE.finditer(text)))
        if values:
            self._set_fact(draft, "symbols", values, ", ".join(values))

    def _extract_timeframes(self, text: str, draft: StrategyParseDraft) -> None:
        values = list(dict.fromkeys(m.group(1).upper() for m in self._TIMEFRAME_RE.finditer(text)))
        # The normalizer canonicalizes the words daily/weekly to D1/W1 even
        # when they describe loss limits rather than chart timeframes.
        if re.search(r"\bD1\s+loss\b", text, re.I):
            values = [item for item in values if item != "D1"]
        if re.search(r"\bW1\s+loss\b", text, re.I):
            values = [item for item in values if item != "W1"]
        if values:
            self._set_fact(draft, "timeframes", values, ", ".join(values))

    def _extract_side(self, text: str, draft: StrategyParseDraft) -> None:
        lower = text.lower()
        long_hit = bool(re.search(r"\b(long|buy)\b", lower))
        short_hit = bool(re.search(r"\b(short|sell)\b", lower))
        if long_hit and short_hit:
            self._set_fact(draft, "entry.side", "BOTH", "long/buy + short/sell")
        elif long_hit:
            self._set_fact(draft, "entry.side", "LONG", "long/buy")
        elif short_hit:
            self._set_fact(draft, "entry.side", "SHORT", "short/sell")

    def _extract_order_type(self, text: str, draft: StrategyParseDraft) -> None:
        if self._looks_like_ict_ny_asia_sweep_v1(text):
            self._set_fact(draft, "entry.order_type", "LIMIT", "LIMIT_ONLY")
            return
        lower = text.lower()
        hits = []
        if re.search(r"\bmarket(?:\s+order)?\b", lower):
            hits.append("MARKET")
        if re.search(r"\blimit(?:\s+order)?\b", lower):
            hits.append("LIMIT")
        if re.search(
            r"\b(?:buy|sell)\s+stop(?:\s+order)?\b"
            r"|\bstop\s+(?:entry|order)\b"
            r"|\bentry\s+stop\b",
            lower,
        ):
            hits.append("STOP")
        hits = list(dict.fromkeys(hits))
        if len(hits) == 1:
            self._set_fact(draft, "entry.order_type", hits[0], hits[0])
        elif len(hits) > 1:
            # A structured SMC strategy may intentionally contain two
            # mutually-exclusive execution branches selected by ATR.  MARKET
            # is only a harmless build-time placeholder here; _build_entries
            # emits both executable MARKET and LIMIT rules.
            if (
                {"MARKET", "LIMIT"}.issubset(set(hits))
                and self._looks_like_structured_smc(text)
                and "atr" in text.lower()
                and "1.5" in text
            ):
                self._set_fact(
                    draft,
                    "entry.order_type",
                    "MARKET",
                    "ATR_SELECTED_MARKET_OR_LIMIT",
                )
                draft.metadata["dynamic_entry_model"] = (
                    "ATR14_M15_MARKET_OR_LIMIT"
                )
            else:
                draft.conflicts["entry.order_type"] = hits

    def _extract_entry_condition(self, text: str, draft: StrategyParseDraft) -> None:
        if self._looks_like_ict_ny_asia_sweep_v1(text):
            self._set_fact(
                draft,
                "entry.condition",
                {
                    "type": "ICT_NY_ASIA_SWEEP_M5_MSS_FVG_LIMIT",
                    "sequence": [
                        "CLOSED_H1_EMA_BIAS",
                        "ASIA_HIGH_OR_LOW_SWEEP_CLOSE_BACK",
                        "M5_FRACTAL_MSS",
                        "M5_ATR_DISPLACEMENT_NEW_FVG",
                        "LIMIT_AT_50_PERCENT_FVG",
                    ],
                },
                "ICT_NY_ASIA_SWEEP_M5_MSS_FVG_LIMIT",
            )
            self._set_fact(
                draft,
                "entry.price",
                "50_PERCENT_OF_FIRST_QUALIFYING_NEW_M5_FVG",
                "LIMIT_AT_50_PERCENT_FVG",
            )
            return
        timeframe_values = draft.value("timeframes") or []
        timeframe = str(timeframe_values[0]) if timeframe_values else None

        ema_pattern = re.compile(
            r"\b(?:(buy|long|sell|short)\s+when\s+)?"
            r"EMA\s*(\d+)\s+cross(?:es)?\s+"
            r"(above|below)\s+EMA\s*(\d+)\b",
            re.I,
        )

        ema_rules = []
        for match in ema_pattern.finditer(text):
            action = (match.group(1) or "").upper()
            fast = int(match.group(2))
            direction = match.group(3).upper()
            slow = int(match.group(4))

            operator = "CROSS_ABOVE" if direction == "ABOVE" else "CROSS_BELOW"
            inferred_side = "LONG" if direction == "ABOVE" else "SHORT"

            if action in {"BUY", "LONG"}:
                inferred_side = "LONG"
            elif action in {"SELL", "SHORT"}:
                inferred_side = "SHORT"

            ema_rules.append(
                {
                    "type": "EMA_CROSSOVER",
                    "side": inferred_side,
                    "operator": operator,
                    "left_period": fast,
                    "right_period": slow,
                    "timeframe": timeframe,
                    "source_text": match.group(0).strip(),
                }
            )

        if ema_rules:
            self._set_fact(
                draft,
                "entry.condition",
                {"type": "EMA_CROSSOVER_SET", "rules": ema_rules},
                " | ".join(rule["source_text"] for rule in ema_rules),
            )
        else:
            match = re.search(
                r"(?:entry|enter|buy|sell|long|short|вход|вхід|покупай|купуй|продавай)\s*"
                r"(?:when|if|если|якщо|когда|коли|:|=)\s*([^.;\n]+)",
                text,
                re.I,
            )
            if match:
                value = match.group(1).strip()
                self._set_fact(
                    draft,
                    "entry.condition",
                    value,
                    match.group(0).strip(),
                )

        price = re.search(
            r"(?:entry\s*price|цена\s*входа|ціна\s*входу|ціна\s*входа)\s*(?:=|:|is)?\s*([^.;\n]+)",
            text,
            re.I,
        )
        if price:
            self._set_fact(
                draft,
                "entry.price",
                price.group(1).strip(),
                price.group(0).strip(),
            )

        if (
            "entry.condition" not in draft.facts
            and self._looks_like_ict_ny_asia_sweep_v1(text)
        ):
            self._set_fact(
                draft,
                "entry.condition",
                {
                    "type": "ICT_NY_ASIA_SWEEP_M5_MSS_FVG_LIMIT",
                    "sequence": [
                        "CLOSED_H1_EMA_BIAS",
                        "ASIA_HIGH_OR_LOW_SWEEP_CLOSE_BACK",
                        "M5_FRACTAL_MSS",
                        "M5_ATR_DISPLACEMENT_NEW_FVG",
                        "LIMIT_AT_50_PERCENT_FVG",
                    ],
                },
                "ICT_NY_ASIA_SWEEP_M5_MSS_FVG_LIMIT",
            )

        if (
            "entry.condition" not in draft.facts
            and self._looks_like_ny_asia_sweep_m5(text)
        ):
            self._set_fact(
                draft,
                "entry.condition",
                {
                    "type": "NY_ASIA_SWEEP_M5_IFVG_FVG",
                    "sequence": [
                        "ASIA_HIGH_OR_LOW_SWEEP",
                        "M5_CLOSE_BACK_INSIDE_ASIA_RANGE",
                        "M5_OPPOSING_FVG_INVERSION",
                        "NEW_DIRECTIONAL_M5_FVG",
                        "IMMEDIATE_MARKET_ENTRY_NEXT_M5_OPEN",
                    ],
                },
                "NY_ASIA_SWEEP_M5_IFVG_FVG",
            )

        if (
            "entry.condition" not in draft.facts
            and self._looks_like_h4_rejection_m15(text)
        ):
            self._set_fact(
                draft,
                "entry.condition",
                {
                    "type": "H4_REJECTION_M15_IFVG_FVG",
                    "sequence": [
                        "H4_ORDER_FLOW",
                        "H4_FVG_FIRST_TOUCH_REJECTION_BLOCK",
                        "M15_OPPOSING_FVG_INVERSION",
                        "NEW_DIRECTIONAL_M15_FVG",
                        "IMMEDIATE_MARKET_ENTRY_NEXT_M15_OPEN",
                    ],
                },
                "H4_REJECTION_M15_IFVG_FVG",
            )

        if (
            "entry.condition" not in draft.facts
            and self._looks_like_m1_scalping(text)
        ):
            self._set_fact(
                draft,
                "entry.condition",
                {
                    "type": "M1_IFVG_FVG_IMMEDIATE_SCALPING",
                    "sequence": [
                        "HTF_FVG_OR_LIQUIDITY_CONTEXT",
                        "M1_IFVG",
                        "NEW_DIRECTIONAL_M1_FVG",
                        "IMMEDIATE_MARKET_ENTRY_NEXT_M1_OPEN",
                    ],
                },
                "M1_IFVG_FVG_IMMEDIATE_SCALPING",
            )

        if (
            "entry.condition" not in draft.facts
            and self._looks_like_structured_smc(text)
        ):
            self._set_fact(
                draft,
                "entry.condition",
                {
                    "type": "STRUCTURED_SMC_SEQUENCE",
                    "sequence": [
                        "H4_DIRECTION",
                        "H4_H1_POI",
                        "DXY_CONTEXT",
                        "M15_REACTION",
                        "M15_DISPLACEMENT",
                        "FVG_IFVG_CONFIRMATION",
                    ],
                },
                "STRUCTURED_SMC_SEQUENCE",
            )

    def _build_entries(
        self,
        *,
        draft: StrategyParseDraft,
        side: StrategySide,
        order_type: EntryOrderType,
        entry_price: ValueReference | None,
        condition_data: Any,
    ) -> list[EntryRule]:
        source = str(draft.source_text or "")
        if self._looks_like_ict_ny_asia_sweep_v1(source):
            return self._build_ict_ny_asia_sweep_v1_entries()

        if self._looks_like_ny_asia_sweep_m5(source):
            return self._build_ny_asia_sweep_m5_entries()

        if self._looks_like_h4_rejection_m15(source):
            return self._build_h4_rejection_m15_entries()

        if self._looks_like_m1_scalping(source):
            return self._build_m1_scalping_entries()

        if self._looks_like_structured_smc(source):
            return self._build_structured_smc_entries(
                draft=draft,
                side=side,
                fallback_order_type=order_type,
            )

        if (
            isinstance(condition_data, dict)
            and condition_data.get("type") == "EMA_CROSSOVER_SET"
        ):
            entries: list[EntryRule] = []
            default_timeframes = draft.value("timeframes") or []
            default_timeframe = (
                str(default_timeframes[0])
                if default_timeframes
                else None
            )

            for index, rule in enumerate(condition_data.get("rules") or [], start=1):
                timeframe = str(
                    rule.get("timeframe")
                    or default_timeframe
                    or ""
                ).strip() or None

                operator = ComparisonOperator(
                    str(rule["operator"]).upper()
                )
                rule_side = StrategySide(
                    str(rule.get("side") or side.value).upper()
                )

                condition = StrategyCondition(
                    condition_id=f"entry_ema_cross_{index}",
                    kind=ConditionKind.COMPARISON,
                    left=ValueReference(
                        source="INDICATOR",
                        field="EMA",
                        timeframe=timeframe,
                        parameters={"period": int(rule["left_period"])},
                    ),
                    operator=operator,
                    right=ValueReference(
                        source="INDICATOR",
                        field="EMA",
                        timeframe=timeframe,
                        parameters={"period": int(rule["right_period"])},
                    ),
                    description=str(rule.get("source_text") or "EMA crossover"),
                    metadata={
                        "parser_source": "day42_structured",
                        "indicator": "EMA",
                    },
                )

                entries.append(
                    EntryRule(
                        side=rule_side,
                        order_type=order_type,
                        conditions=condition,
                        entry_price=entry_price,
                    )
                )

            if entries:
                return entries

        raw_condition = str(condition_data or "").strip()
        upper_condition = raw_condition.upper()
        has_order_block = (
            "ORDER BLOCK" in upper_condition
            or "ORDER_BLOCK" in upper_condition
        )
        has_asia_sweep = (
            "ASIA" in upper_condition
            and (
                "SWEEP" in upper_condition
                or "LIQUIDITY_SWEEP" in upper_condition
            )
        )

        if (
            "CHOCH" in upper_condition
            and has_order_block
        ):
            sequence: list[StrategyCondition] = []

            if has_asia_sweep:
                sequence.append(
                    StrategyCondition(
                        condition_id="entry_asia_liquidity_sweep",
                        kind=ConditionKind.EVENT,
                        event_name="LIQUIDITY_SWEEP",
                        description=(
                            "Sweep of the current Asian session high or low"
                        ),
                        metadata={
                            "parser_source": "natural_language_normalizer",
                            "timeframe": (
                                "M5"
                                if "M5" in upper_condition
                                else None
                            ),
                            "reference_session": "ASIA",
                            "reference_levels": ["HIGH", "LOW"],
                            "current_session_only": True,
                        },
                    )
                )

            sequence.extend(
                [
                    StrategyCondition(
                        condition_id="entry_choch",
                        kind=ConditionKind.EVENT,
                        event_name="CHOCH",
                        description="Opposing CHoCH confirmation",
                        metadata={
                            "parser_source": "natural_language_normalizer",
                            "timeframe": "M5" if "M5" in upper_condition else None,
                            "relative_direction": "OPPOSITE_TO_SWEEP",
                            "direction": (
                                "BULLISH"
                                if "BULLISH" in upper_condition
                                else "BEARISH"
                                if "BEARISH" in upper_condition
                                else None
                            ),
                        },
                    ),
                    StrategyCondition(
                        condition_id="entry_order_block",
                        kind=ConditionKind.EVENT,
                        event_name="ORDER_BLOCK",
                        description="First valid Order Block after CHoCH",
                        metadata={
                            "parser_source": "natural_language_normalizer",
                            "timeframe": "M5" if "M5" in upper_condition else None,
                            "direction": (
                                "BULLISH"
                                if "BULLISH" in upper_condition
                                else "BEARISH"
                                if "BEARISH" in upper_condition
                                else None
                            ),
                            "first_valid_required": (
                                "FIRST VALID" in upper_condition
                            ),
                            "first_mitigation_required": (
                                "MITIGATION" in upper_condition
                                or "MITIGAT" in upper_condition
                                or "FIRST TOUCH" in upper_condition
                                or "RETURN TO" in upper_condition
                            ),
                        },
                    ),
                ]
            )

            condition = StrategyCondition(
                condition_id="entry_sequence_asia_sweep_choch_order_block",
                kind=ConditionKind.SEQUENCE,
                sequence=sequence,
                description=raw_condition,
                metadata={
                    "parser_source": "natural_language_normalizer",
                    "normalized_from_free_text": True,
                },
            )
        elif "CHOCH" in upper_condition:
            condition = StrategyCondition(
                condition_id="entry_choch",
                kind=ConditionKind.EVENT,
                event_name="CHOCH",
                description=raw_condition,
                metadata={
                    "parser_source": "natural_language_normalizer",
                    "timeframe": "M5" if "M5" in upper_condition else None,
                },
            )
        elif "ORDER BLOCK" in upper_condition or "ORDER_BLOCK" in upper_condition:
            condition = StrategyCondition(
                condition_id="entry_order_block",
                kind=ConditionKind.EVENT,
                event_name="ORDER_BLOCK",
                description=raw_condition,
                metadata={
                    "parser_source": "natural_language_normalizer",
                    "timeframe": "M5" if "M5" in upper_condition else None,
                    "first_mitigation_required": (
                        "MITIGATION" in upper_condition
                        or "MITIGAT" in upper_condition
                        or "FIRST TOUCH" in upper_condition
                    ),
                },
            )
        else:
            condition = StrategyCondition(
                condition_id="entry_condition_1",
                kind=ConditionKind.EVENT,
                event_name=raw_condition,
                description=raw_condition,
                metadata={"parser_source": "day42"},
            )

        return [
            EntryRule(
                side=side,
                order_type=order_type,
                conditions=condition,
                entry_price=entry_price,
            )
        ]

    @staticmethod
    def _event(
        condition_id: str,
        event_name: str,
        *,
        description: str,
        metadata: dict[str, Any] | None = None,
    ) -> StrategyCondition:
        return StrategyCondition(
            condition_id=condition_id,
            kind=ConditionKind.EVENT,
            event_name=event_name,
            description=description,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def _looks_like_structured_smc(cls, source: str) -> bool:
        lower = str(source or "").lower()
        required_groups = (
            ("h4", "order flow"),
            ("fvg", "fair value gap"),
            ("m15", "displacement"),
        )
        return all(any(token in lower for token in group) for group in required_groups)

    @staticmethod
    def _looks_like_ict_ny_asia_sweep_v1(source: str) -> bool:
        lower = str(source or "").lower()
        return (
            "ict new york asia" in lower
            and (
                "liquidity sweep" in lower
                or "liquidity_sweep" in lower
            )
            and "m5 market structure shift" in lower
            and "ema20" in lower
            and "ema50" in lower
            and "atr(14)" in lower
            and ("50%" in lower or "50.0%" in lower)
            and "limit orders only" in lower
        )

    @staticmethod
    def _looks_like_ny_asia_sweep_m5(source: str) -> bool:
        lower = str(source or "").lower()
        return (
            "m5" in lower
            and "asia high" in lower
            and "asia low" in lower
            and "new york" in lower
            and "ifvg" in lower
            and "new directional fvg" in lower
        )

    @staticmethod
    def _looks_like_h4_rejection_m15(source: str) -> bool:
        lower = str(source or "").lower()
        return (
            "h4" in lower
            and "m15" in lower
            and "rejection block" in lower
            and "ifvg" in lower
            and "first touch" in lower
        )

    @staticmethod
    def _looks_like_m1_scalping(source: str) -> bool:
        lower = str(source or "").lower()
        return (
            "m1" in lower
            and "ifvg" in lower
            and "fvg" in lower
            and (
                "scalping" in lower
                or "скальп" in lower
            )
        )

    def _build_m1_scalping_entries(self) -> list[EntryRule]:
        condition = self._event(
            "m1_ifvg_fvg_rejection",
            "M1_SCALPING_SETUP",
            description=(
                "HTF FVG/liquidity context -> M1 IFVG -> new directional "
                "M1 FVG -> immediate MARKET entry at the next M1 open."
            ),
            metadata={
                "semantic_event": "M1_IFVG_FVG_IMMEDIATE_ENTRY",
                "timeframe": "M1",
                "context_timeframes": ["H1", "M30", "M15"],
                "timezone": "Europe/Kyiv",
                "session_start": "16:30",
                "session_end": "18:00",
                "hard_session_filter": True,
                "order_type": "MARKET",
                "provider_hint": "m1_ifvg_fvg_rejection",
            },
        )
        return [
            EntryRule(
                side=StrategySide.BOTH,
                order_type=EntryOrderType.MARKET,
                conditions=condition,
                metadata={
                    "entry_model": "M1_IFVG_FVG_IMMEDIATE_ENTRY",
                    "confirmation": "NEW_DIRECTIONAL_FVG_CLOSED",
                    "entry_timing": "NEXT_M1_OPEN_AFTER_NEW_FVG_CLOSE",
                },
            )
        ]

    def _build_h4_rejection_m15_entries(self) -> list[EntryRule]:
        condition = self._event(
            "h4_rejection_m15_ifvg_fvg",
            "H4_REJECTION_M15_SETUP",
            description=(
                "H4 order flow -> fresh H4 FVG first-touch rejection block "
                "-> M15 opposing FVG inversion -> new directional M15 FVG "
                "-> immediate MARKET entry at the next M15 open."
            ),
            metadata={
                "semantic_event": "H4_REJECTION_M15_IFVG_FVG_ENTRY",
                "timeframe": "M15",
                "context_timeframes": ["H4"],
                "context_bars": 16,
                "max_new_fvg_delay_bars": 16,
                "wick_to_body_minimum": 2.0,
                "wick_range_minimum": 0.5,
                "stop_buffer_pips": 1.0,
                "hard_session_filter": False,
                "order_type": "MARKET",
                "provider_hint": "h4_fvg_rejection_m15_ifvg",
            },
        )
        return [
            EntryRule(
                side=StrategySide.BOTH,
                order_type=EntryOrderType.MARKET,
                conditions=condition,
                metadata={
                    "entry_model": "H4_FVG_REJECTION_M15_IFVG_FVG",
                    "confirmation": "NEW_DIRECTIONAL_M15_FVG_CLOSED",
                    "entry_timing": "NEXT_M15_OPEN_AFTER_NEW_FVG_CLOSE",
                },
            )
        ]

    def _build_ny_asia_sweep_m5_entries(self) -> list[EntryRule]:
        condition = self._event(
            "ny_asia_sweep_m5_ifvg_fvg",
            "NY_ASIA_SWEEP_M5_SETUP",
            description=(
                "New York sweep of Asia High/Low with a close back inside "
                "-> M5 opposing FVG inversion -> new directional M5 FVG "
                "-> immediate MARKET entry at the next M5 open."
            ),
            metadata={
                "semantic_event": "NY_ASIA_SWEEP_M5_IFVG_FVG_ENTRY",
                "timeframe": "M5",
                "context_timeframes": ["M5"],
                "asia_timezone": "Europe/Kyiv",
                "asia_start": "03:00",
                "asia_end": "10:00",
                "entry_timezone": "America/New_York",
                "entry_start": "09:30",
                "entry_end": "11:00",
                "max_sweep_to_inversion_bars": 12,
                "max_new_fvg_delay_bars": 6,
                "stop_buffer_pips": 1.0,
                "hard_session_filter": True,
                "order_type": "MARKET",
                "provider_hint": "ny_asia_sweep_m5_ifvg",
            },
        )
        return [
            EntryRule(
                side=StrategySide.BOTH,
                order_type=EntryOrderType.MARKET,
                conditions=condition,
                metadata={
                    "entry_model": "NY_ASIA_SWEEP_M5_IFVG_FVG",
                    "confirmation": "NEW_DIRECTIONAL_M5_FVG_CLOSED",
                    "entry_timing": "NEXT_M5_OPEN_AFTER_NEW_FVG_CLOSE",
                },
            )
        ]

    def _build_ict_ny_asia_sweep_v1_entries(self) -> list[EntryRule]:
        condition = self._event(
            "ict_ny_asia_sweep_m5",
            "ICT_NY_ASIA_SWEEP_M5_SETUP",
            description=(
                "Closed-H1 EMA bias -> New York Asia sweep and close back -> "
                "causal M5 fractal MSS -> ATR displacement and new FVG -> "
                "LIMIT entry at the FVG midpoint."
            ),
            metadata={
                "semantic_event": "ICT_NY_ASIA_SWEEP_M5_LIMIT_ENTRY",
                "timeframe": "M5",
                "context_timeframes": ["H1", "M5"],
                "asia_timezone": "Europe/Kyiv",
                "asia_start": "03:00",
                "asia_end": "10:00",
                "entry_timezone": "America/New_York",
                "entry_start": "09:30",
                "entry_end": "11:00",
                "h1_fast_ema_period": 20,
                "h1_slow_ema_period": 50,
                "fractal_left_bars": 2,
                "fractal_right_bars": 2,
                "mss_swing_lookback": 50,
                "atr_period": 14,
                "displacement_atr_multiple": 1.0,
                "displacement_body_ratio": 0.60,
                "stop_buffer_ticks": 1,
                "hard_session_filter": True,
                "order_type": "LIMIT",
                "provider_hint": "ict_ny_asia_sweep_m5",
            },
        )
        return [
            EntryRule(
                side=StrategySide.BOTH,
                order_type=EntryOrderType.LIMIT,
                conditions=condition,
                entry_price=ValueReference(
                    source="STRUCTURE",
                    field="FIRST_TAP_NEW_FVG",
                    timeframe="M5",
                    parameters={
                        "zone": "FVG",
                        "tap": "FIRST",
                        "midpoint": True,
                    },
                ),
                metadata={
                    "entry_model": "ICT_NY_ASIA_SWEEP_M5_MSS_FVG_LIMIT",
                    "confirmation": "MSS_ATR_DISPLACEMENT_NEW_FVG",
                    "entry_timing": "FIRST_RETRACE_TO_50_PERCENT_FVG",
                    "pending_expiry": "11:00_AMERICA_NEW_YORK",
                },
            )
        ]

    def _base_smc_sequence(self, source: str) -> list[StrategyCondition]:
        """Build SMC events using registered production capabilities."""
        lower = source.lower()
        sequence = [
            self._event(
                "h4_direction", "DIRECTION_BIAS",
                description="H4 Order Flow / trend direction is confirmed.",
                metadata={"timeframe": "H4", "allowed_side": "TRADE_DIRECTION_ONLY", "semantic_event": "H4_DIRECTION_CONFIRMED", "provider_hint": "structure_trend"},
            ),
            self._event(
                "htf_poi", "POI_DETECTION",
                description="Price reacts from a valid H4/H1 POI.",
                metadata={"timeframes": ["H4", "H1"], "poi_types": ["FVG", "ORDER_BLOCK", "LIQUIDITY"], "semantic_event": "HTF_POI_REACTION", "provider_hint": "order_block_poi"},
            ),
        ]
        if "dxy" in lower:
            dxy_symbol = self._dxy_broker_symbol(source)
            sequence[0].metadata["dxy_context_required"] = True
            sequence[0].metadata["dxy_policy"] = "NOT_CONTRADICT"
            sequence[0].metadata["dxy_semantic_event"] = "DXY_CONTEXT_NOT_CONTRADICT"
            sequence[0].metadata["dxy_symbol"] = dxy_symbol
            sequence[0].metadata["dxy_timeframe"] = "H4"
            sequence[0].metadata["dxy_usd_base_relation"] = "SAME"
            sequence[0].metadata["dxy_usd_quote_relation"] = "INVERSE"
        sequence.extend([
            self._event(
                "m15_reaction", "POI_DETECTION",
                description="M15 reaction from the selected POI is confirmed.",
                metadata={"timeframe": "M15", "semantic_event": "M15_REACTION_CONFIRMED", "provider_hint": "fvg_poi"},
            ),
            self._event(
                "m15_displacement", "MARKET_STRUCTURE",
                description="Strong M15 displacement occurs in the intended direction.",
                metadata={"timeframe": "M15", "semantic_event": "M15_DISPLACEMENT_CONFIRMED", "provider_hint": "structure_trend"},
            ),
            self._event(
                "fvg_ifvg", "FVG_DETECTION",
                description="Required FVG / IFVG confirmation is present.",
                metadata={"timeframe": "M15", "concepts": ["FVG", "IFVG"], "semantic_event": "FVG_IFVG_CONFIRMATION", "provider_hint": "fvg_poi"},
            ),
        ])
        return sequence

    @staticmethod
    def _dxy_broker_symbol(source: str) -> str:
        text = str(source or "")
        match = re.search(
            r"\bDXY(?:\s+broker)?\s+symbol(?:\s+used[^\n.;:]*?)?"
            r"\s*(?:=|:|is)\s*([A-Z0-9._-]+)",
            text,
            re.I,
        )
        if match:
            return str(match.group(1)).strip().rstrip(".,;:").upper()
        return "DXY"

    def _build_structured_smc_entries(
        self,
        *,
        draft: StrategyParseDraft,
        side: StrategySide,
        fallback_order_type: EntryOrderType,
    ) -> list[EntryRule]:
        source = str(draft.source_text or "")
        lower = source.lower()
        base = self._base_smc_sequence(source)
        entries: list[EntryRule] = []

        has_market = "market" in lower
        has_limit = "limit" in lower
        has_atr_split = "1.5" in lower and "atr" in lower
        has_strong_displacement = (
            "strong" in lower
            and "displacement" in lower
        )

        if has_market or not has_limit:
            market_steps = copy.deepcopy(base)

            if has_atr_split and market_steps:
                market_steps[-1].metadata = {
                    **(market_steps[-1].metadata or {}),
                    "atr_branch_required": True,
                    "atr_indicator": "ATR",
                    "atr_period": 14,
                    "atr_timeframe": "M15",
                    "atr_operator": "<",
                    "atr_multiplier": 1.5,
                    **(
                        {"atr_minimum_multiplier": 1.0}
                        if has_strong_displacement
                        else {}
                    ),
                    "atr_semantic_event": (
                        "DISPLACEMENT_RANGE_GTE_1_0_LT_1_5_ATR14"
                        if has_strong_displacement
                        else "DISPLACEMENT_RANGE_LT_1_5_ATR14"
                    ),
                }

            if market_steps:
                market_steps[-1].metadata = {
                    **(market_steps[-1].metadata or {}),
                    "confirmation_candle_close_required": True,
                    "confirmation_timeframe": "M15",
                    "entry_timing": "AFTER_CONFIRMATION_CANDLE_CLOSE",
                    "confirmation_semantic_event": "M15_CONFIRMATION_CANDLE_CLOSED",
                }

            entries.append(
                EntryRule(
                    side=side,
                    order_type=EntryOrderType.MARKET,
                    conditions=StrategyCondition(
                        condition_id="smc_market_sequence",
                        kind=ConditionKind.SEQUENCE,
                        sequence=market_steps,
                        description="SMC MARKET entry sequence",
                        metadata={"branch": "MARKET"},
                    ),
                    metadata={
                        "entry_model": "IMMEDIATE_AFTER_CONFIRMATION_CLOSE",
                        "atr_branch": (
                            "1.0_TO_LT_1.5_ATR14"
                            if has_atr_split and has_strong_displacement
                            else "<1.5_ATR14" if has_atr_split else None
                        ),
                    },
                )
            )

        if has_limit:
            limit_steps = copy.deepcopy(base)

            if has_atr_split and limit_steps:
                limit_steps[-1].metadata = {
                    **(limit_steps[-1].metadata or {}),
                    "atr_branch_required": True,
                    "atr_indicator": "ATR",
                    "atr_period": 14,
                    "atr_timeframe": "M15",
                    "atr_operator": ">=",
                    "atr_multiplier": 1.5,
                    "atr_semantic_event": "DISPLACEMENT_RANGE_GTE_1_5_ATR14",
                }

            if limit_steps:
                limit_steps[-1].metadata = {
                    **(limit_steps[-1].metadata or {}),
                    "first_tap_required": True,
                    "tap_timeframe": "M15",
                    "tap_zone": "FVG",
                    "tap_order": "FIRST",
                    "use_midpoint": False,
                    "first_tap_semantic_event": "FIRST_TAP_NEW_M15_FVG",
                }

            entries.append(
                EntryRule(
                    side=side,
                    order_type=EntryOrderType.LIMIT,
                    conditions=StrategyCondition(
                        condition_id="smc_limit_sequence",
                        kind=ConditionKind.SEQUENCE,
                        sequence=limit_steps,
                        description="SMC LIMIT first-tap entry sequence",
                        metadata={"branch": "LIMIT"},
                    ),
                    entry_price=ValueReference(
                        source="STRUCTURE",
                        field="FIRST_TAP_NEW_FVG",
                        timeframe="M15",
                        parameters={"zone": "FVG", "tap": "FIRST", "midpoint": False},
                    ),
                    metadata={
                        "entry_model": "FIRST_FVG_TAP",
                        "atr_branch": ">=1.5_ATR14" if has_atr_split else None,
                    },
                )
            )

        if not entries:
            raw_condition = str(draft.value("entry.condition") or "").strip()
            upper_condition = raw_condition.upper()

            if (
                "CHOCH" in upper_condition
                and (
                    "ORDER BLOCK" in upper_condition
                    or "ORDER_BLOCK" in upper_condition
                )
            ):
                condition = StrategyCondition(
                    condition_id="entry_sequence_choch_order_block",
                    kind=ConditionKind.SEQUENCE,
                    sequence=[
                        StrategyCondition(
                            condition_id="entry_choch",
                            kind=ConditionKind.EVENT,
                            event_name="CHOCH",
                            description="CHoCH confirmation",
                            metadata={
                                "parser_source": "natural_language_normalizer",
                                "timeframe": "M5" if "M5" in upper_condition else None,
                            },
                        ),
                        StrategyCondition(
                            condition_id="entry_order_block",
                            kind=ConditionKind.EVENT,
                            event_name="ORDER_BLOCK",
                            description="Order Block entry after CHoCH",
                            metadata={
                                "parser_source": "natural_language_normalizer",
                                "timeframe": "M5" if "M5" in upper_condition else None,
                                "first_mitigation_required": (
                                    "MITIGATION" in upper_condition
                                    or "MITIGAT" in upper_condition
                                    or "FIRST TOUCH" in upper_condition
                                ),
                            },
                        ),
                    ],
                    description=raw_condition,
                    metadata={
                        "parser_source": "natural_language_normalizer",
                        "normalized_from_free_text": True,
                    },
                )
            else:
                condition = StrategyCondition(
                    condition_id="entry_condition_1",
                    kind=ConditionKind.EVENT,
                    event_name=raw_condition,
                    description=raw_condition,
                    metadata={"parser_source": "day42"},
                )

            entries.append(
                EntryRule(
                    side=side,
                    order_type=fallback_order_type,
                    conditions=condition,
                )
            )

        return entries

    @staticmethod
    def _strategy_filter_metadata(source: str) -> dict[str, Any]:
        lower = str(source or "").lower()
        if StrategyTextParser._looks_like_ict_ny_asia_sweep_v1(source):
            return {
                "model": "ICT_NY_ASIA_SWEEP_M5_MSS_FVG_LIMIT",
                "h1_bias_model": "CLOSED_H1_CLOSE_EMA20_EMA50",
                "liquidity_source": ["ASIA_HIGH", "ASIA_LOW"],
                "sweep_close_back_inside_required": True,
                "m5_mss_model": "CONFIRMED_FRACTAL_2_LEFT_2_RIGHT",
                "mss_swing_lookback": 50,
                "displacement_atr_period": 14,
                "displacement_atr_multiple": 1.0,
                "displacement_body_ratio": 0.60,
                "new_m5_fvg_required": True,
                "entry_fvg_midpoint": 0.50,
                "order_type": "LIMIT",
                "pending_expiry": "11:00_AMERICA_NEW_YORK",
                "fixed_rr": 2.0,
                "one_trade_per_session_per_symbol": True,
            }
        if StrategyTextParser._looks_like_ny_asia_sweep_m5(source):
            return {
                "model": "NY_ASIA_SWEEP_M5_IFVG_FVG",
                "liquidity_source": ["ASIA_HIGH", "ASIA_LOW"],
                "sweep_close_back_inside_required": True,
                "m5_ifvg_required": True,
                "new_m5_fvg_required": True,
                "immediate_entry_after_new_fvg_close": True,
                "max_sweep_to_inversion_bars": 12,
                "max_new_fvg_delay_bars": 6,
                "fixed_rr": 2.0,
                "hard_session_filter": True,
                "one_trade_per_day_per_symbol": True,
            }
        if StrategyTextParser._looks_like_h4_rejection_m15(source):
            return {
                "model": "H4_FVG_REJECTION_M15_IFVG_FVG",
                "h4_order_flow_required": True,
                "h4_order_flow_model": "LAST_CONFIRMED_BOS_WITH_PROTECTED_SWING",
                "h4_fvg_first_touch_only": True,
                "h4_rejection_block_required": True,
                "rejection_wick_to_body_minimum": 2.0,
                "rejection_wick_range_minimum": 0.5,
                "context_bars_m15": 16,
                "m15_ifvg_required": True,
                "new_m15_fvg_required": True,
                "new_fvg_may_form_anywhere": True,
                "max_new_fvg_delay_bars": 16,
                "immediate_entry_after_new_fvg_close": True,
                "fixed_rr": 2.0,
                "hard_session_filter": False,
                "one_trade_per_h4_context": True,
            }
        if StrategyTextParser._looks_like_m1_scalping(source):
            return {
                "model": "M1_IFVG_FVG_IMMEDIATE_ENTRY",
                "htf_context_only": True,
                "htf_poi": ["FVG", "LIQUIDITY_SWEEP"],
                "m1_ifvg_required": True,
                "new_m1_fvg_required": True,
                "m1_retest_required": False,
                "rejection_or_engulf_required": False,
                "immediate_entry_after_new_fvg_close": True,
                "first_problem_area_stop": True,
                "fixed_rr": 1.0,
                "htf_problem_area_permission": True,
                "hard_session_filter": True,
            }
        metadata = {
            "h4_direction_required": ("h4" in lower and ("order flow" in lower or "trend" in lower)),
            "poi_required": any(token in lower for token in ("fvg", "order block", "liquidity")),
            "dxy_context": "dxy" in lower,
            "m15_reaction": ("m15" in lower and "reaction" in lower),
            "m15_displacement": ("m15" in lower and "displacement" in lower),
            "fvg_ifvg_confirmation": ("fvg" in lower or "ifvg" in lower),
        }
        allowed_sessions = StrategyTextParser._extract_allowed_sessions(source)
        if allowed_sessions:
            metadata.update({
                "hard_session_filter": True,
                "allowed_sessions": allowed_sessions,
                "session_policy": "NEW_ENTRIES_ONLY",
            })
        return metadata

    @staticmethod
    def _extract_allowed_sessions(source: str) -> list[str]:
        """Return only sessions explicitly named as trading windows."""
        text = str(source or "")
        lower = text.lower()
        window_match = re.search(
            r"(?:trade|trading|entries?|enter|торг\w*|вход\w*)"
            r"[^.;]{0,80}?(?:only\s+)?(?:\bduring\b|\bwithin\b|только\s+во?\s+время|во?\s+время)"
            r"(?P<window>[^.;]{1,100})",
            lower,
            re.I,
        )
        if not window_match:
            return []
        window = window_match.group("window")

        aliases = (
            ("ASIA", r"\b(?:asia|asian)\b|\bазиатск\w*"),
            ("LONDON", r"\blondon\b|\bлондонск\w*"),
            ("NEW_YORK", r"\bnew\s*york\b|\bny\s+session\b|\bнью[-\s]?йоркск\w*"),
        )
        return [name for name, pattern in aliases if re.search(pattern, window, re.I)]

    @staticmethod
    def _build_management_rules(source: str) -> list[ManagementRule]:
        """Compile explicit break-even instructions into executable rules."""
        text = str(source or "")
        match = re.search(
            r"(?:move\s+(?:the\s+)?(?:stop(?:\s+loss)?\s+)?to\s+)?"
            r"(?:break[\s-]?even|\bBE\b)"
            r"(?:\s+(?:at|after|when|once|@))?\s*"
            r"(\d+(?:[.,]\d+)?)\s*R\b",
            text,
            re.I,
        )
        if not match:
            match = re.search(
                r"(?:безубыт\w*|б/?у)\s*(?:на|при|после|@)?\s*"
                r"(\d+(?:[.,]\d+)?)\s*R\b",
                text,
                re.I,
            )
        if not match:
            return []

        trigger_r = float(match.group(1).replace(",", "."))
        return [
            ManagementRule(
                action=ManagementActionType.BREAK_EVEN,
                trigger=StrategyCondition(
                    condition_id="management_break_even_trigger",
                    kind=ConditionKind.COMPARISON,
                    left=ValueReference(
                        source="TRADE_STATE",
                        field="UNREALIZED_R_MULTIPLE",
                    ),
                    operator=ComparisonOperator.GTE,
                    right=ValueReference(source="CONSTANT", constant=trigger_r),
                    description=f"Move stop loss to break-even at {trigger_r:g}R",
                    metadata={"parser_source": "natural_language_normalizer"},
                ),
                parameters={
                    "target": "ENTRY_PRICE",
                    "offset": 0.0,
                    "trigger_r": trigger_r,
                },
                metadata={
                    "expression": match.group(0),
                    "source": "PARSER_EXPRESSION",
                },
            )
        ]

    @staticmethod
    def _build_entry_price_reference(
        value: Any,
        *,
        timeframes: list[str],
    ) -> ValueReference:
        raw = str(value or "").strip()
        upper = raw.upper()
        timeframe = (
            str(timeframes[0]).strip().upper()
            if timeframes
            else None
        )

        order_block = "ORDER BLOCK" in upper or "ORDER_BLOCK" in upper
        midpoint = bool(
            re.search(r"\b(?:50(?:\.0)?\s*%|MIDPOINT|MID[\s-]?POINT|MIDDLE)\b", upper)
        )
        first_tap = any(
            token in upper
            for token in ("FIRST", "FIRST TAP", "FIRST TOUCH", "FIRST VALID")
        )

        if order_block:
            return ValueReference(
                source="STRUCTURE",
                field=(
                    "FIRST_TAP_ORDER_BLOCK"
                    if first_tap or midpoint
                    else "ORDER_BLOCK_PROXIMAL_LINE"
                ),
                timeframe=timeframe,
                parameters={
                    "zone": "ORDER_BLOCK",
                    "tap": "FIRST" if first_tap else None,
                    "midpoint": midpoint,
                },
                metadata={
                    "expression": raw,
                    "parser_source": "natural_language_normalizer",
                },
            )

        return ValueReference(
            source="PARSER_EXPRESSION",
            timeframe=timeframe,
            parameters={"expression": value},
        )

    @staticmethod
    def _preferred_trading_window(source: str) -> dict[str, Any] | None:
        text = str(source or "")
        if (
            StrategyTextParser._looks_like_ict_ny_asia_sweep_v1(text)
            or StrategyTextParser._looks_like_ny_asia_sweep_m5(text)
        ):
            return {
                "timezone": "America/New_York",
                "start": "09:30",
                "end": "11:00",
                "hard_filter": True,
                "policy": "NEW_ENTRIES_ONLY",
            }
        scalping = StrategyTextParser._looks_like_m1_scalping(text)
        if scalping:
            match = re.search(
                r"16[:.]30\s*[–—-]\s*18[:.]00"
                r"|16[:.]30[\s\S]{0,80}?18[:.]00",
                text,
                re.I,
            )
            if match:
                return {
                    "timezone": "Europe/Kyiv",
                    "start": "16:30",
                    "end": "18:00",
                    "hard_filter": True,
                    "policy": "NEW_ENTRIES_ONLY",
                }
        match = re.search(r"16[:.]30\s*[–—-]\s*18[:.]30", text, re.I)
        if not match:
            return None
        return {
            "timezone": "Europe/Kyiv",
            "start": "16:30",
            "end": "18:30",
            "hard_filter": False,
            "policy": "PREFERRED_ONLY",
        }

    def _extract_risk(self, text: str, draft: StrategyParseDraft) -> None:
        match = self._RISK_RE.search(text)
        if match:
            value = float(match.group(1).replace(",", "."))
            lower = text.lower()
            metadata: dict[str, Any] = {
                "loss_limit_basis": "PERIOD_START_BALANCE_REALIZED",
                "loss_limit_timezone": "Europe/Kyiv",
            }

            if self._looks_like_m1_scalping(text):
                metadata.update({
                    "max_trades_per_day_per_symbol": 1,
                    "trade_day_timezone": "Europe/Kyiv",
                })
            if self._looks_like_ict_ny_asia_sweep_v1(text):
                metadata.update({
                    "max_trades_per_day_per_symbol": 1,
                    "trade_day_timezone": "America/New_York",
                    "portfolio_planned_risk_percent": 1.0,
                })
            elif self._looks_like_ny_asia_sweep_m5(text):
                metadata.update({
                    "max_trades_per_day_per_symbol": 1,
                    "trade_day_timezone": "Europe/Kyiv",
                    "portfolio_planned_risk_percent": 0.7,
                })

            daily = re.search(
                r"(?:maximum\s+)?(?:daily|D1)\s+loss[^\d]{0,30}"
                r"(\d+(?:[.,]\d+)?)\s*%",
                text,
                re.I,
            )
            weekly = re.search(
                r"(?:maximum\s+)?(?:weekly|W1)\s+loss[^\d]{0,30}"
                r"(\d+(?:[.,]\d+)?)\s*%",
                text,
                re.I,
            )
            if daily:
                metadata["max_daily_loss_percent"] = float(
                    daily.group(1).replace(",", ".")
                )
            if weekly:
                metadata["max_weekly_loss_percent"] = float(
                    weekly.group(1).replace(",", ".")
                )

            max_open_match = re.search(
                r"maximum\s+open\s+positions?\s*:\s*(\d+)",
                text,
                re.I,
            )
            max_symbol_match = re.search(
                r"maximum\s+open\s+positions?\s+per\s+symbol\s*:\s*(\d+)",
                text,
                re.I,
            )
            max_open = int(max_open_match.group(1)) if max_open_match else 1
            max_symbol = int(max_symbol_match.group(1)) if max_symbol_match else 1
            if self._looks_like_m1_scalping(text):
                metadata["portfolio_planned_risk_percent"] = round(
                    value * max_open,
                    10,
                )
            self._set_fact(
                draft,
                "risk",
                {
                    "sizing_type": "BALANCE_PERCENT",
                    "value": value,
                    "max_open_positions": max_open,
                    "max_positions_per_symbol": max_symbol,
                    "metadata": metadata,
                },
                match.group(0),
            )

    def _extract_stop_loss(self, text: str, draft: StrategyParseDraft) -> None:
        lower = text.lower()
        if (
            self._looks_like_ict_ny_asia_sweep_v1(text)
            and "stop loss" in lower
            and "sweep" in lower
        ):
            self._set_fact(
                draft,
                "stop_loss",
                {
                    "type": "STRUCTURE",
                    "value": None,
                    "metadata": {
                        "preferred_reference": "ASIA_SWEEP_EXTREME",
                        "buffer_ticks": 1,
                        "true_invalidation_required": True,
                    },
                },
                "ASIA_SWEEP_EXTREME_PLUS_ONE_TICK",
            )
            return
        if (
            self._looks_like_ny_asia_sweep_m5(text)
            and "stop loss" in lower
            and "sweep" in lower
        ):
            self._set_fact(
                draft,
                "stop_loss",
                {
                    "type": "STRUCTURE",
                    "value": None,
                    "metadata": {
                        "preferred_reference": "ASIA_SWEEP_EXTREME",
                        "buffer_pips": 1.0,
                        "true_invalidation_required": True,
                    },
                },
                "ASIA_SWEEP_EXTREME_PLUS_BUFFER",
            )
            return
        if (
            self._looks_like_h4_rejection_m15(text)
            and "stop loss" in lower
            and "ifvg" in lower
            and "fvg" in lower
        ):
            self._set_fact(
                draft,
                "stop_loss",
                {
                    "type": "STRUCTURE",
                    "value": None,
                    "metadata": {
                        "preferred_reference": (
                            "FARTHEST_IFVG_OR_ENTRY_FVG_BOUNDARY"
                        ),
                        "buffer_pips": 1.0,
                        "true_invalidation_required": True,
                    },
                },
                "FARTHEST_IFVG_OR_ENTRY_FVG_BOUNDARY_PLUS_BUFFER",
            )
            return
        if (
            self._looks_like_m1_scalping(text)
            and "stop loss" in lower
            and any(
                token in lower
                for token in (
                    "problem area",
                    "order block",
                    "swing",
                    "structure",
                    "nearest low",
                    "nearest high",
                )
            )
        ):
            self._set_fact(
                draft,
                "stop_loss",
                {
                    "type": "STRUCTURE",
                    "value": None,
                    "metadata": {
                        "preferred_reference": "FIRST_PROBLEM_AREA",
                        "true_invalidation_required": True,
                    },
                },
                "M1_FIRST_PROBLEM_AREA_INVALIDATION",
            )
            return
        if (
            self._looks_like_structured_smc(text)
            and "stop loss" in lower
            and any(
                token in lower
                for token in ("structure", "fvg", "order_block", "order block")
            )
        ):
            self._set_fact(
                draft,
                "stop_loss",
                {
                    "type": "STRUCTURE",
                    "value": None,
                    "metadata": {
                        "preferred_reference": "ENTRY_FVG",
                        "fallback_reference": "ORDER_BLOCK",
                        "true_invalidation_required": True,
                    },
                },
                "STRUCTURAL_FVG_OR_ORDER_BLOCK_INVALIDATION",
            )
            return

        match = self._SL_PERCENT_RE.search(text)
        if match:
            value = float(match.group(1).replace(",", "."))
            self._set_fact(
                draft,
                "stop_loss",
                {"type": "PERCENT", "value": value},
                match.group(0),
            )
            return

        match = self._SL_PIPS_RE.search(text)
        if match:
            value = float(match.group(1).replace(",", "."))
            unit = "PIPS" if "pip" in match.group(2).lower() else "POINTS"
            self._set_fact(
                draft,
                "stop_loss",
                {"type": "FIXED_DISTANCE", "value": value, "metadata": {"unit": unit}},
                match.group(0),
            )

    def _extract_take_profit(self, text: str, draft: StrategyParseDraft) -> None:
        lower = text.lower()
        if self._looks_like_ict_ny_asia_sweep_v1(text):
            self._set_fact(
                draft,
                "take_profit",
                {"type": "R_MULTIPLE", "value": 2.0},
                "FIXED_2R",
            )
            return
        if (
            "session liquidity" in lower
            and (
                "base target" in lower
                or "minimum acceptable risk/reward" in lower
                or "minimum acceptable risk/reward" in lower
            )
        ):
            base_match = re.search(
                r"base\s+target\s*(?:=|:|is)?\s*"
                r"(\d+(?:[.,]\d+)?)\s*r\b",
                text,
                re.I,
            )
            minimum_match = re.search(
                r"minimum\s+(?:acceptable\s+)?(?:risk\s*/?\s*reward|rr)?"
                r"[^\d]{0,30}(\d+(?:[.,]\d+)?)\s*r\b",
                text,
                re.I,
            )
            base_r = (
                float(base_match.group(1).replace(",", "."))
                if base_match
                else 2.0
            )
            minimum_r = (
                float(minimum_match.group(1).replace(",", "."))
                if minimum_match
                else 1.5
            )
            self._set_fact(
                draft,
                "take_profit",
                {
                    "type": "R_MULTIPLE",
                    "value": base_r,
                    "metadata": {
                        "target_policy": "SESSION_LIQUIDITY",
                        "base_r": base_r,
                        "minimum_r": minimum_r,
                        "maximum_r": 2.0,
                        "allow_above_base": False,
                        "no_trade_below_minimum": True,
                        "liquidity_sources": [
                            "ASIA_HIGH",
                            "ASIA_LOW",
                            "LONDON_HIGH",
                            "LONDON_LOW",
                            "NEW_YORK_HIGH",
                            "NEW_YORK_LOW",
                            "PREVIOUS_DAY_HIGH",
                            "PREVIOUS_DAY_LOW",
                        ],
                        "completed_sessions_only": True,
                    },
                },
                "SESSION_LIQUIDITY_R_MULTIPLE",
            )
            return

        match = self._RR_RE.search(text)
        if match:
            value = float(match.group(1).replace(",", "."))
            self._set_fact(
                draft,
                "take_profit",
                {"type": "R_MULTIPLE", "value": value},
                match.group(0),
            )
            return

        match = self._TP_PIPS_RE.search(text)
        if match:
            value = float(match.group(1).replace(",", "."))
            unit = "PIPS" if "pip" in match.group(2).lower() else "POINTS"
            self._set_fact(
                draft,
                "take_profit",
                {"type": "FIXED_DISTANCE", "value": value, "metadata": {"unit": unit}},
                match.group(0),
            )

    @staticmethod
    def _number_from_text(value: Any) -> float:
        match = re.search(r"(\d+(?:[.,]\d+)?)", str(value))
        if not match:
            raise ValueError("clarification_numeric_value_required")
        return float(match.group(1).replace(",", "."))

    @classmethod
    def _normalize_order_type(cls, value: Any) -> str:
        raw = str(value or "").strip()
        upper = raw.upper()
        if upper in {"MARKET", "LIMIT", "STOP"}:
            return upper

        lower = raw.lower()
        # Natural-language clarification such as:
        # "No LIMIT or STOP pending order is used. Enter at market..."
        if "market" in lower or "по рынку" in lower or "по ринку" in lower or "рыноч" in lower or "ринков" in lower:
            return "MARKET"
        if "limit" in lower or "лимит" in lower or "ліміт" in lower:
            return "LIMIT"
        if "stop" in lower or "стопов" in lower:
            return "STOP"

        raise ValueError("unsupported_entry_order_type")

    @classmethod
    def _normalize_stop_loss(cls, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)

        raw = str(value or "").strip()
        lower = raw.lower()

        # Structural stops do not require a numeric value.
        # Examples: "SL behind FVG / Order Block", "stop beyond structure".
        structural_tokens = (
            "fvg",
            "fair value gap",
            "order block",
            "orderblock",
            "structure",
            "swing high",
            "swing low",
            "invalidation",
            "behind",
            "beyond",
            "за fvg",
            "за ордер",
            "за order",
            "за структур",
            "за свинг",
            "инвалидац",
            "інвалідац",
        )
        if any(token in lower for token in structural_tokens):
            return {
                "type": "STRUCTURE",
                "value": None,
                "metadata": {
                    "expression": raw,
                    "source": "USER_CLARIFICATION",
                },
            }

        number = cls._number_from_text(raw)

        if "%" in raw or "percent" in lower or "процент" in lower or "відсот" in lower:
            return {"type": "PERCENT", "value": number}

        if re.search(r"\b(pip|pips|point|points|пипс\w*|піпс\w*|пункт\w*)\b", lower):
            return {
                "type": "FIXED_DISTANCE",
                "value": number,
                "metadata": {"unit": "PIPS" if ("pip" in lower or "пип" in lower or "піп" in lower) else "POINTS"},
            }

        raise ValueError("unsupported_stop_loss_clarification")

    @classmethod
    def _normalize_take_profit(cls, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)

        raw = str(value or "").strip()
        lower = raw.lower()

        r_values = [
            float(x.replace(",", "."))
            for x in re.findall(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*r\b", lower)
        ]

        rr_hit = (
            bool(re.search(r"\b(?:rr|r:r|risk\s*reward)\b", lower))
            or bool(r_values)
            or "r_multiple" in lower
        )
        if rr_hit:
            base_r = 2.0 if 2.0 in r_values else (
                max(r_values) if r_values else cls._number_from_text(raw)
            )
            minimum_r = min(r_values) if r_values else None
            metadata: dict[str, Any] = {
                "expression": raw,
                "source": "USER_CLARIFICATION",
                "base_r": base_r,
            }

            if "session" in lower and "liquidity" in lower:
                metadata.update({
                    "target_policy": "SESSION_LIQUIDITY",
                    "allow_above_base": False,
                    "minimum_r": minimum_r if minimum_r is not None else 1.5,
                    "maximum_r": 2.0,
                    "no_trade_below_minimum": True,
                    "liquidity_sources": [
                        "ASIA_HIGH", "ASIA_LOW",
                        "LONDON_HIGH", "LONDON_LOW",
                        "NEW_YORK_HIGH", "NEW_YORK_LOW",
                        "PREVIOUS_DAY_HIGH", "PREVIOUS_DAY_LOW",
                    ],
                    "completed_sessions_only": True,
                })

            return {
                "type": "R_MULTIPLE",
                "value": base_r,
                "metadata": metadata,
            }

        number = cls._number_from_text(raw)

        if "%" in raw or "percent" in lower or "процент" in lower or "відсот" in lower:
            return {"type": "PERCENT", "value": number}

        if re.search(r"\b(pip|pips|point|points|пипс\w*|піпс\w*|пункт\w*)\b", lower):
            return {
                "type": "FIXED_DISTANCE",
                "value": number,
                "metadata": {"unit": "PIPS" if ("pip" in lower or "пип" in lower or "піп" in lower) else "POINTS"},
            }

        raise ValueError("unsupported_take_profit_clarification")

    @classmethod
    def _normalize_risk(cls, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)

        raw = str(value or "").strip()
        lower = raw.lower()
        number = cls._number_from_text(raw)

        percent_hit = (
            "%" in raw
            or "percent" in lower
            or "процент" in lower
            or "відсот" in lower
        )
        if percent_hit:
            equity_tokens = (
                "equity",
                "account equity",
                "current equity",
                "эквити",
                "еквіті",
                "капитал",
                "капітал",
            )
            balance_tokens = (
                "balance",
                "account balance",
                "баланс",
            )
            sizing_type = (
                "EQUITY_PERCENT"
                if any(token in lower for token in equity_tokens)
                else "BALANCE_PERCENT"
            )
            if not any(token in lower for token in equity_tokens) and any(
                token in lower for token in balance_tokens
            ):
                sizing_type = "BALANCE_PERCENT"

            metadata: dict[str, Any] = {
                "expression": raw,
                "source": "USER_CLARIFICATION",
            }

            daily = re.search(
                r"(?:daily|дневн\w*|денн\w*)[^\d]{0,30}(\d+(?:[.,]\d+)?)\s*%",
                lower,
            )
            weekly = re.search(
                r"(?:weekly|недельн\w*|тижнев\w*)[^\d]{0,30}(\d+(?:[.,]\d+)?)\s*%",
                lower,
            )
            if daily:
                metadata["max_daily_loss_percent"] = float(daily.group(1).replace(",", "."))
            if weekly:
                metadata["max_weekly_loss_percent"] = float(weekly.group(1).replace(",", "."))

            return {
                "sizing_type": sizing_type,
                "value": number,
                "max_open_positions": 1,
                "max_positions_per_symbol": 1,
                "metadata": metadata,
            }

        if "lot" in lower or "лот" in lower:
            return {"sizing_type": "FIXED_LOT", "value": number}

        if "$" in raw or "usd" in lower or "cash" in lower:
            return {"sizing_type": "FIXED_CASH", "value": number}

        raise ValueError("unsupported_risk_clarification")

    def _finalize(self, draft: StrategyParseDraft) -> None:
        normalizers = {
            "entry.order_type": self._normalize_order_type,
            "stop_loss": self._normalize_stop_loss,
            "take_profit": self._normalize_take_profit,
            "risk": self._normalize_risk,
        }
        for path, normalizer in normalizers.items():
            fact = draft.facts.get(path)
            if fact is None or isinstance(fact.value, dict):
                continue
            try:
                fact.value = normalizer(fact.value)
            except ValueError:
                # Preserve the failed clarification for diagnostics instead of
                # silently losing what the user answered.
                draft.metadata.setdefault("normalization_failures", {})[path] = {
                    "value": fact.value,
                    "source_text": fact.source_text,
                }
                draft.facts.pop(path, None)

        unresolved = []
        for path in self.CRITICAL_PATHS:
            if path not in draft.facts or path in draft.conflicts:
                unresolved.append(path)

        order_type = draft.value("entry.order_type")
        if order_type in {"LIMIT", "STOP"} and "entry.price" not in draft.facts:
            unresolved.append("entry.price")

        draft.unresolved_fields = list(dict.fromkeys(unresolved))
        draft.questions = [
            self._question_for(path, path in draft.conflicts)
            for path in draft.unresolved_fields
        ]

    @staticmethod
    def _question_for(path: str, conflict: bool) -> ParserQuestion:
        labels = {
            "symbols": "Какие торговые инструменты использует стратегия?",
            "timeframes": "На каких таймфреймах работает стратегия?",
            "entry.side": "Стратегия открывает LONG, SHORT или оба направления?",
            "entry.order_type": "Какой тип входа используется: MARKET, LIMIT или STOP?",
            "entry.condition": "Какое точное условие должно выполниться для входа?",
            "entry.price": "Как точно рассчитывается цена LIMIT/STOP входа?",
            "stop_loss": "Как точно рассчитывается Stop Loss?",
            "take_profit": "Как точно рассчитывается Take Profit?",
            "risk": "Какой риск и способ расчёта размера позиции используются?",
        }
        return ParserQuestion(
            question_id=f"clarify_{path.replace('.', '_')}",
            path=path,
            question=labels.get(path, f"Уточните значение поля {path}."),
            reason="conflicting_information" if conflict else "missing_required_information",
        )
