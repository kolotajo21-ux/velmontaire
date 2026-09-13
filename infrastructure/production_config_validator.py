from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


@dataclass(slots=True)
class ProductionConfigValidationResult:
    valid: bool
    mode: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": bool(self.valid),
            "mode": self.mode,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "diagnostics": dict(self.diagnostics),
        }


class ProductionConfigValidator:
    """
    Day 95 production configuration / environment gate.

    This component NEVER initializes MT5 and NEVER calls a broker.

    Fail-closed rules:
    - execution mode must be PAPER or LIVE;
    - LIVE requires explicit ALLOW_LIVE_TRADING=true;
    - LIVE requires MT5_LOGIN / MT5_PASSWORD / MT5_SERVER;
    - MT5 terminal path must be configured;
    - account/risk limits must be numerically sane;
    - soft loss/DD limits must be below hard limits;
    - strategy protection flags that would increase risk must stay disabled;
    - invalid configuration never becomes production-ready.
    """

    def validate(
        self,
        config: Any,
        *,
        env: Mapping[str, str] | None = None,
        check_terminal_exists: bool = False,
    ) -> ProductionConfigValidationResult:
        env_map = {
            str(k): str(v)
            for k, v in dict(env or {}).items()
        }

        mode = (
            env_map.get("BOT_EXECUTION_MODE", "PAPER")
            .strip()
            .upper()
        )

        errors: list[str] = []
        warnings: list[str] = []

        if mode not in {"PAPER", "LIVE"}:
            errors.append("EXECUTION_MODE_INVALID")

        mt5_path = str(
            getattr(config, "MT5_PATH", "")
            or ""
        ).strip()

        if not mt5_path:
            errors.append("MT5_PATH_MISSING")
        elif check_terminal_exists and not Path(mt5_path).is_file():
            errors.append("MT5_TERMINAL_NOT_FOUND")

        if mode == "LIVE":
            live_allowed = (
                env_map.get("ALLOW_LIVE_TRADING", "")
                .strip()
                .lower()
                in {"1", "true", "yes", "on"}
            )

            if not live_allowed:
                errors.append(
                    "LIVE_TRADING_NOT_EXPLICITLY_AUTHORIZED"
                )

            required_credentials = {
                "MT5_LOGIN": env_map.get("MT5_LOGIN", "").strip(),
                "MT5_PASSWORD": env_map.get("MT5_PASSWORD", "").strip(),
                "MT5_SERVER": env_map.get("MT5_SERVER", "").strip(),
            }

            for name, value in required_credentials.items():
                if not value:
                    errors.append(f"{name}_MISSING")

            login = required_credentials["MT5_LOGIN"]
            if login:
                try:
                    if int(login) <= 0:
                        raise ValueError
                except (TypeError, ValueError):
                    errors.append("MT5_LOGIN_INVALID")

        self._positive(
            config,
            "ACCOUNT_SIZE",
            errors,
        )

        self._range(
            config,
            "RISK_PERCENT",
            minimum=0.0,
            maximum=1.0,
            errors=errors,
            exclusive_minimum=True,
        )

        self._range(
            config,
            "MAX_OPEN_RISK_PERCENT",
            minimum=0.0,
            maximum=5.0,
            errors=errors,
            exclusive_minimum=True,
        )

        self._positive_integer(
            config,
            "MAX_SIMULTANEOUS_TRADES",
            errors,
        )
        self._positive_integer(
            config,
            "MAX_TRADES_PER_DAY",
            errors,
        )
        self._positive_integer(
            config,
            "MAX_LOSSES_PER_DAY",
            errors,
        )

        risk = self._number(config, "RISK_PERCENT")
        open_risk = self._number(
            config,
            "MAX_OPEN_RISK_PERCENT",
        )

        if (
            risk is not None
            and open_risk is not None
            and open_risk < risk
        ):
            errors.append(
                "MAX_OPEN_RISK_BELOW_SINGLE_TRADE_RISK"
            )

        self._ordered_limits(
            config,
            "SOFT_DAILY_LOSS_PERCENT",
            "HARD_DAILY_LOSS_PERCENT",
            errors,
        )

        self._ordered_limits(
            config,
            "SOFT_TOTAL_DRAWDOWN_PERCENT",
            "HARD_TOTAL_DRAWDOWN_PERCENT",
            errors,
        )

        minimum_rr = self._number(
            config,
            "MINIMUM_RR",
        )
        maximum_rr = self._number(
            config,
            "MAXIMUM_RR",
        )

        if minimum_rr is None or minimum_rr <= 0:
            errors.append("MINIMUM_RR_INVALID")

        if maximum_rr is None or maximum_rr <= 0:
            errors.append("MAXIMUM_RR_INVALID")

        if (
            minimum_rr is not None
            and maximum_rr is not None
            and maximum_rr < minimum_rr
        ):
            errors.append("RR_RANGE_INVALID")

        for flag_name in (
            "ALLOW_MARTINGALE",
            "ALLOW_AVERAGING_DOWN",
            "ALLOW_POSITION_STACKING",
        ):
            if getattr(config, flag_name, None) is not False:
                errors.append(
                    f"{flag_name}_MUST_BE_FALSE"
                )

        if getattr(
            config,
            "INTRABAR_PRIORITY",
            None,
        ) not in {
            "STOP_FIRST",
            "TP_FIRST",
        }:
            errors.append(
                "INTRABAR_PRIORITY_INVALID"
            )

        timezone = str(
            getattr(
                config,
                "PLATFORM_TIMEZONE",
                "",
            )
            or ""
        ).strip()

        if not timezone:
            errors.append(
                "PLATFORM_TIMEZONE_MISSING"
            )

        symbols = getattr(
            config,
            "SYMBOLS",
            None,
        )

        if not isinstance(symbols, list) or not symbols:
            errors.append("SYMBOLS_EMPTY")
        else:
            normalized = [
                str(item).strip().upper()
                for item in symbols
                if str(item).strip()
            ]

            if len(normalized) != len(set(normalized)):
                errors.append("SYMBOLS_DUPLICATED")

            if not normalized:
                errors.append("SYMBOLS_EMPTY")

        if mode == "PAPER":
            warnings.append(
                "PAPER_MODE_BROKER_SUBMISSION_MUST_REMAIN_DISABLED"
            )

        return ProductionConfigValidationResult(
            valid=not errors,
            mode=mode,
            errors=errors,
            warnings=warnings,
            diagnostics={
                "broker_call_performed": False,
                "mt5_initialized": False,
                "terminal_path": mt5_path,
                "terminal_exists_checked": bool(
                    check_terminal_exists
                ),
                "live_authorized": (
                    mode == "LIVE"
                    and "LIVE_TRADING_NOT_EXPLICITLY_AUTHORIZED"
                    not in errors
                ),
            },
        )

    @staticmethod
    def _number(
        config: Any,
        name: str,
    ) -> float | None:
        raw = getattr(
            config,
            name,
            None,
        )

        try:
            return float(raw)
        except (
            TypeError,
            ValueError,
            OverflowError,
        ):
            return None

    def _positive(
        self,
        config: Any,
        name: str,
        errors: list[str],
    ) -> None:
        value = self._number(
            config,
            name,
        )

        if value is None or value <= 0:
            errors.append(f"{name}_INVALID")

    def _positive_integer(
        self,
        config: Any,
        name: str,
        errors: list[str],
    ) -> None:
        raw = getattr(
            config,
            name,
            None,
        )

        try:
            value = int(raw)
        except (
            TypeError,
            ValueError,
            OverflowError,
        ):
            errors.append(f"{name}_INVALID")
            return

        if value <= 0:
            errors.append(f"{name}_INVALID")

    def _range(
        self,
        config: Any,
        name: str,
        *,
        minimum: float,
        maximum: float,
        errors: list[str],
        exclusive_minimum: bool = False,
    ) -> None:
        value = self._number(
            config,
            name,
        )

        if value is None:
            errors.append(f"{name}_INVALID")
            return

        lower_bad = (
            value <= minimum
            if exclusive_minimum
            else value < minimum
        )

        if lower_bad or value > maximum:
            errors.append(f"{name}_INVALID")

    def _ordered_limits(
        self,
        config: Any,
        soft_name: str,
        hard_name: str,
        errors: list[str],
    ) -> None:
        soft = self._number(
            config,
            soft_name,
        )
        hard = self._number(
            config,
            hard_name,
        )

        if soft is None or soft <= 0:
            errors.append(
                f"{soft_name}_INVALID"
            )

        if hard is None or hard <= 0:
            errors.append(
                f"{hard_name}_INVALID"
            )

        if (
            soft is not None
            and hard is not None
            and soft >= hard
        ):
            errors.append(
                f"{soft_name}_MUST_BE_BELOW_{hard_name}"
            )