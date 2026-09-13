from __future__ import annotations

from typing import Any

from core.context import ModuleExecutionResult, StrategyContext
from core.interfaces import StrategyModule
from core.strategy import ModuleRole, StrategyModuleDefinition

from concepts.sessions.services import SessionService, SessionServiceConfig


class SessionContextModule(StrategyModule):
    provider = "session_context"
    role = ModuleRole.MARKET
    version = "1.0.0"

    capabilities = (
        "session_analysis",
        "asia_session",
        "london_session",
        "new_york_session",
        "session_high_low",
        "previous_day_high_low",
        "premium_discount",
    )

    dependencies = ()

    def __init__(
        self,
        definition: StrategyModuleDefinition | None = None,
    ) -> None:
        super().__init__(definition=definition)

        parameters = dict(self.definition.parameters or {})

        self.timeframe = str(
            self.definition.timeframe
            or parameters.get("timeframe", "M15")
        ).upper()

        self.service = SessionService(
            SessionServiceConfig(
                asia_start_utc=int(parameters.get("asia_start_utc", 0)),
                asia_end_utc=int(parameters.get("asia_end_utc", 7)),
                london_start_utc=int(parameters.get("london_start_utc", 7)),
                london_end_utc=int(parameters.get("london_end_utc", 12)),
                new_york_start_utc=int(parameters.get("new_york_start_utc", 12)),
                new_york_end_utc=int(parameters.get("new_york_end_utc", 21)),
                use_last_closed_candle=bool(
                    parameters.get("use_last_closed_candle", True)
                ),
                premium_discount_source=str(
                    parameters.get(
                        "premium_discount_source",
                        "PREVIOUS_DAY",
                    )
                ).upper(),
            )
        )

    def execute(
        self,
        context: StrategyContext,
    ) -> ModuleExecutionResult:
        rates = context.get_rates(self.timeframe)

        if not rates:
            return self.failure(
                error=f"session_rates_missing:{self.timeframe}",
                diagnostics={"timeframe": self.timeframe},
            )

        state = self.service.analyze(rates=rates)
        state_data = self._state_to_dict(state)

        active_session = self._active_session(state_data)
        best_range = self.service.best_session_range(state)

        best_session = None
        if best_range is not None:
            best_session = {
                "session": best_range[0],
                "high": float(best_range[1]),
                "low": float(best_range[2]),
            }

        normalized_data = {
            "active_session": active_session,
            "asia": state_data.get("asia"),
            "london": state_data.get("london"),
            "new_york": state_data.get("new_york"),
            "previous_day": state_data.get("previous_day"),
            "premium_discount": state_data.get("premium_discount"),
            "best_session_range": best_session,
            "raw": state_data,
        }

        context.put("session_context", normalized_data)
        context.market["sessions"] = normalized_data

        diagnostics = dict(
            state_data.get("diagnostics", {})
            if isinstance(state_data.get("diagnostics"), dict)
            else {}
        )

        diagnostics.update(
            {
                "adapter": "SessionContextModule",
                "provider": self.provider,
                "timeframe": self.timeframe,
                "active_session": active_session,
                "best_session_found": best_session is not None,
            }
        )

        passed = any(
            normalized_data.get(key) is not None
            for key in (
                "asia",
                "london",
                "new_york",
                "previous_day",
            )
        )

        return self.success(
            passed=passed,
            data=normalized_data,
            diagnostics=diagnostics,
        )

    @staticmethod
    def _state_to_dict(state: Any) -> dict[str, Any]:
        to_dict = getattr(state, "to_dict", None)

        if callable(to_dict):
            value = to_dict()
            if isinstance(value, dict):
                return dict(value)

        result: dict[str, Any] = {}

        for key in (
            "asia",
            "london",
            "new_york",
            "previous_day",
            "premium_discount",
            "diagnostics",
        ):
            value = getattr(state, key, None)

            if value is None:
                result[key] = None
                continue

            item_to_dict = getattr(value, "to_dict", None)

            if callable(item_to_dict):
                result[key] = item_to_dict()
            elif isinstance(value, dict):
                result[key] = dict(value)
            else:
                result[key] = value

        return result

    @staticmethod
    def _active_session(
        state_data: dict[str, Any],
    ) -> str | None:
        for key, name in (
            ("asia", "ASIA"),
            ("london", "LONDON"),
            ("new_york", "NEW_YORK"),
        ):
            session = state_data.get(key)

            if isinstance(session, dict) and bool(
                session.get("active", False)
            ):
                return name

        return None