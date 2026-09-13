from __future__ import annotations
from datetime import datetime, timezone
from prop_rules.news_models import EconomicEvent, NewsComplianceDecision


class NewsComplianceEngine:
    HIGH_IMPACT = {"HIGH", "RED"}

    # Conservative symbol/currency mapping. Stage 14 is extensible; unknown
    # mappings fail closed only when a ruleset requires related-news filtering.
    INDEX_CURRENCY = {
        "US30": "USD", "DJ30": "USD", "NAS100": "USD", "USTEC": "USD",
        "SPX500": "USD", "US500": "USD", "GER40": "EUR", "DE40": "EUR",
        "UK100": "GBP", "JP225": "JPY",
    }
    METAL_CURRENCY = {"XAUUSD": ("USD",), "XAGUSD": ("USD",)}

    def evaluate(
        self,
        *,
        rules: dict,
        symbol: str,
        action: str,
        now_utc: str,
        events: list[EconomicEvent],
    ) -> NewsComplianceDecision:
        action = str(action).strip().upper()
        if action not in {"OPEN", "CLOSE", "HOLD", "MODIFY", "PENDING_TRIGGER"}:
            return NewsComplianceDecision(False, action, "news_action_unknown", policy_status="UNRESOLVED")

        policy = str(rules.get("news_policy", "")).strip().upper()
        if not policy:
            # Backward-compatible Stage 13 fields.
            if rules.get("news_trading") is True:
                policy = "ALLOW"
            elif "news_execution_window_minutes" in rules:
                policy = "BLOCK_EXECUTION_WINDOW"
            else:
                return NewsComplianceDecision(False, action, "news_policy_unresolved", policy_status="UNRESOLVED")

        if policy == "ALLOW":
            return NewsComplianceDecision(True, action, "news_trading_allowed")

        if policy == "REWARD_ADJUSTMENT_ONLY":
            return NewsComplianceDecision(True, action, "news_execution_allowed_reward_rule_applies")

        before = self._number(rules.get("news_before_minutes", rules.get("news_execution_window_minutes")))
        after = self._number(rules.get("news_after_minutes", rules.get("news_execution_window_minutes")))
        if before is None or after is None:
            return NewsComplianceDecision(False, action, "news_window_unresolved", policy_status="UNRESOLVED")

        affected = self._symbol_currencies(symbol)
        if not affected:
            return NewsComplianceDecision(False, action, "symbol_news_mapping_unresolved", policy_status="UNRESOLVED")

        now = self._dt(now_utc)
        relevant = []
        for event in events:
            if str(event.impact).upper() not in self.HIGH_IMPACT:
                continue
            if not set(x.upper() for x in event.currencies).intersection(affected):
                continue
            event_time = self._dt(event.timestamp_utc)
            delta = (now - event_time).total_seconds() / 60.0
            if -before <= delta <= after:
                relevant.append((abs(delta), delta, event))

        if not relevant:
            return NewsComplianceDecision(True, action, "outside_restricted_news_window")

        relevant.sort(key=lambda x: (x[0], x[2].event_id))
        _, delta, event = relevant[0]

        if action == "HOLD":
            holding = rules.get("news_holding")
            if holding is True:
                return NewsComplianceDecision(True, action, "news_holding_allowed", event.event_id, round(delta, 4))
            if holding is False:
                return NewsComplianceDecision(False, action, "news_holding_blocked", event.event_id, round(delta, 4))
            return NewsComplianceDecision(False, action, "news_holding_policy_unresolved", event.event_id, round(delta, 4), "UNRESOLVED")

        if policy in {"BLOCK_EXECUTION_WINDOW", "BLOCK_OPEN_CLOSE_WINDOW"}:
            if action in {"OPEN", "CLOSE", "PENDING_TRIGGER"}:
                return NewsComplianceDecision(False, action, "restricted_high_impact_news_window", event.event_id, round(delta, 4))
            return NewsComplianceDecision(True, action, "non_execution_action_allowed", event.event_id, round(delta, 4))

        if policy == "BLOCK_OPEN_HOLD_CLOSE_WINDOW":
            if action in {"OPEN", "CLOSE", "HOLD", "PENDING_TRIGGER"}:
                return NewsComplianceDecision(False, action, "restricted_high_impact_news_window", event.event_id, round(delta, 4))

        return NewsComplianceDecision(False, action, "news_policy_unknown", event.event_id, round(delta, 4), "UNRESOLVED")

    @classmethod
    def _symbol_currencies(cls, symbol: str) -> set[str]:
        s = "".join(ch for ch in str(symbol).upper() if ch.isalnum())
        if s in cls.METAL_CURRENCY:
            return set(cls.METAL_CURRENCY[s])
        if s in cls.INDEX_CURRENCY:
            return {cls.INDEX_CURRENCY[s]}
        if len(s) >= 6:
            a, b = s[:3], s[3:6]
            known = {"USD","EUR","GBP","JPY","CHF","CAD","AUD","NZD"}
            if a in known and b in known:
                return {a, b}
        return set()

    @staticmethod
    def _number(value):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None
        return value if value >= 0 else None

    @staticmethod
    def _dt(value: str) -> datetime:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("news_timestamp_invalid") from exc
        if dt.tzinfo is None:
            raise ValueError("news_timestamp_timezone_required")
        return dt.astimezone(timezone.utc)
