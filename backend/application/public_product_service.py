from __future__ import annotations

from copy import deepcopy
from typing import Any


class PublicProductService:
    """
    Stable public product payload for landing/pricing UI.

    Public marketing copy describes only capabilities that exist in the
    product architecture. Prices are intentionally not hard-coded yet.
    """

    def __init__(self, *, plan_entitlement_service: Any) -> None:
        self.plan_entitlement_service = plan_entitlement_service

    def landing_payload(self) -> dict[str, Any]:
        plans = []
        for code in ("STARTER", "PRO", "SCALE"):
            plan = self.plan_entitlement_service.public_plan_payload(code)
            plans.append({
                "code": plan["code"],
                "max_strategies": plan["max_strategies"],
                "max_backtests_per_month": plan["max_backtests_per_month"],
                "max_broker_connections": plan["max_broker_connections"],
                "max_active_bots": plan["max_active_bots"],
                "live_trading": plan["live_trading"],
                "price": None,
                "price_status": "TBD",
            })

        payload = {
            "product": {
                "name": "Trading Automation Platform",
                "tagline": "Describe. Clarify. Backtest. Automate.",
                "description": (
                    "Turn a natural-language trading strategy into a reviewed, "
                    "versioned strategy workflow with backtesting and controlled "
                    "MT5 automation."
                ),
            },
            "workflow": [
                {
                    "step": 1,
                    "title": "Describe your strategy",
                    "description": "Write the trading system in normal language.",
                },
                {
                    "step": 2,
                    "title": "Clarify missing rules",
                    "description": (
                        "The AI flow surfaces unresolved execution details "
                        "instead of silently guessing them."
                    ),
                },
                {
                    "step": 3,
                    "title": "Review and approve",
                    "description": (
                        "Inspect entry, stop-loss, take-profit, risk rules and "
                        "the exact immutable strategy version."
                    ),
                },
                {
                    "step": 4,
                    "title": "Backtest",
                    "description": (
                        "Run the version-pinned strategy and inspect statistics, "
                        "equity curve and trades."
                    ),
                },
                {
                    "step": 5,
                    "title": "Connect and automate",
                    "description": (
                        "Use PAPER first or explicitly authorize eligible LIVE "
                        "automation through the protected runtime boundary."
                    ),
                },
            ],
            "features": [
                "Natural-language strategy builder",
                "AI clarification flow",
                "Human strategy review",
                "Immutable strategy versions",
                "Backtest statistics and equity curve",
                "Strategy version comparison",
                "MT5 connection flow",
                "PAPER / LIVE separation",
                "Bot control dashboard",
                "Strategy improvement requests",
            ],
            "plans": plans,
            "faq": [
                {
                    "question": "Does the AI guess missing strategy rules?",
                    "answer": (
                        "No. Unresolved execution details remain blockers until "
                        "they are clarified."
                    ),
                },
                {
                    "question": "Can a strategy go LIVE automatically?",
                    "answer": (
                        "No. LIVE requires the applicable plan entitlement, "
                        "verified connection, reviewed strategy, safety readiness "
                        "and explicit LIVE confirmation."
                    ),
                },
                {
                    "question": "Can I improve a strategy later?",
                    "answer": (
                        "Yes. Improvement requests create a separate proposal and "
                        "a new immutable version instead of silently changing the "
                        "active strategy."
                    ),
                },
            ],
            "cta": {
                "primary": "Build a strategy",
                "secondary": "See how it works",
            },
            "disclaimer": (
                "Backtests and automated execution do not guarantee future "
                "performance. Trading involves risk."
            ),
        }
        return deepcopy(payload)
