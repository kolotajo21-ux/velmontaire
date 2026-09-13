from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class RiskEngineError(ValueError):
    """Fail-closed risk/position-sizing error."""


class RiskMode(str, Enum):
    BALANCE_PERCENT = "BALANCE_PERCENT"
    EQUITY_PERCENT = "EQUITY_PERCENT"
    FIXED_MONEY = "FIXED_MONEY"
    FIXED_LOT = "FIXED_LOT"


@dataclass(frozen=True, slots=True)
class RiskRequest:
    mode: RiskMode | str
    value: float
    balance: float
    equity: float
    entry_price: float
    stop_price: float
    pip_size: float | None = None
    pip_value_per_lot: float | None = None
    tick_size: float | None = None
    tick_value_per_lot: float | None = None
    min_lot: float = 0.01
    max_lot: float = 100.0
    lot_step: float = 0.01


@dataclass(frozen=True, slots=True)
class RiskLimits:
    max_daily_risk_percent: float | None = None
    max_total_open_risk_percent: float | None = None
    max_positions: int | None = None
    max_positions_per_symbol: int | None = None


@dataclass(frozen=True, slots=True)
class RiskState:
    daily_risk_money: float = 0.0
    total_open_risk_money: float = 0.0
    open_positions: int = 0
    open_positions_for_symbol: int = 0


@dataclass(frozen=True, slots=True)
class PositionSize:
    risk_money: float
    lot: float
    stop_distance: float
    stop_distance_pips: float | None
    money_risk_per_lot: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk_money": self.risk_money,
            "lot": self.lot,
            "stop_distance": self.stop_distance,
            "stop_distance_pips": self.stop_distance_pips,
            "money_risk_per_lot": self.money_risk_per_lot,
        }


@dataclass(frozen=True, slots=True)
class RiskDecision:
    allowed: bool
    reason: str
    projected_daily_risk_money: float
    projected_total_open_risk_money: float


class UniversalRiskEngine:
    """
    Universal position sizing and portfolio risk gates.

    Risk is computed from the actual SL distance. Monetary loss per lot can be
    supplied through pip_size + pip_value_per_lot or tick_size +
    tick_value_per_lot. Unsupported/missing contract data fails closed.
    """

    def calculate(self, request: RiskRequest) -> PositionSize:
        if not isinstance(request, RiskRequest):
            raise RiskEngineError("invalid_risk_request")

        mode = self._mode(request.mode)
        value = self._positive(request.value, "risk_value")
        balance = self._positive(request.balance, "balance")
        equity = self._positive(request.equity, "equity")
        entry = self._positive(request.entry_price, "entry_price")
        stop = self._positive(request.stop_price, "stop_price")
        distance = abs(entry - stop)
        if distance <= 0:
            raise RiskEngineError("stop_distance_must_be_positive")

        if mode == RiskMode.BALANCE_PERCENT:
            risk_money = balance * value / 100.0
        elif mode == RiskMode.EQUITY_PERCENT:
            risk_money = equity * value / 100.0
        elif mode == RiskMode.FIXED_MONEY:
            risk_money = value
        else:
            risk_money = 0.0  # calculated after lot validation

        money_per_lot, stop_pips = self._money_risk_per_lot(
            distance=distance,
            pip_size=request.pip_size,
            pip_value_per_lot=request.pip_value_per_lot,
            tick_size=request.tick_size,
            tick_value_per_lot=request.tick_value_per_lot,
        )

        min_lot = self._positive(request.min_lot, "min_lot")
        max_lot = self._positive(request.max_lot, "max_lot")
        step = self._positive(request.lot_step, "lot_step")
        if max_lot < min_lot:
            raise RiskEngineError("max_lot_below_min_lot")

        if mode == RiskMode.FIXED_LOT:
            lot = self._normalize_lot(value, min_lot, max_lot, step)
            risk_money = lot * money_per_lot
        else:
            raw_lot = risk_money / money_per_lot
            lot = self._normalize_lot(raw_lot, min_lot, max_lot, step)
            # Fail closed if minimum tradable lot would exceed requested risk.
            if raw_lot < min_lot - 1e-12:
                raise RiskEngineError(
                    f"risk_below_minimum_lot:{raw_lot}:{min_lot}"
                )
            # If max lot caps the size, report actual monetary risk of the order.
            risk_money = lot * money_per_lot

        return PositionSize(
            risk_money=risk_money,
            lot=lot,
            stop_distance=distance,
            stop_distance_pips=stop_pips,
            money_risk_per_lot=money_per_lot,
        )

    def check_limits(
        self,
        *,
        candidate_risk_money: float,
        balance: float,
        state: RiskState,
        limits: RiskLimits,
    ) -> RiskDecision:
        candidate = self._non_negative(candidate_risk_money, "candidate_risk_money")
        base = self._positive(balance, "balance")
        daily = self._non_negative(state.daily_risk_money, "daily_risk_money")
        open_risk = self._non_negative(state.total_open_risk_money, "total_open_risk_money")
        positions = self._non_negative_int(state.open_positions, "open_positions")
        symbol_positions = self._non_negative_int(
            state.open_positions_for_symbol, "open_positions_for_symbol"
        )

        projected_daily = daily + candidate
        projected_open = open_risk + candidate

        if limits.max_daily_risk_percent is not None:
            cap = base * self._non_negative(
                limits.max_daily_risk_percent, "max_daily_risk_percent"
            ) / 100.0
            if projected_daily > cap + 1e-9:
                return RiskDecision(False, "MAX_DAILY_RISK", projected_daily, projected_open)

        if limits.max_total_open_risk_percent is not None:
            cap = base * self._non_negative(
                limits.max_total_open_risk_percent, "max_total_open_risk_percent"
            ) / 100.0
            if projected_open > cap + 1e-9:
                return RiskDecision(False, "MAX_TOTAL_OPEN_RISK", projected_daily, projected_open)

        if limits.max_positions is not None:
            max_positions = self._positive_int(limits.max_positions, "max_positions")
            if positions + 1 > max_positions:
                return RiskDecision(False, "MAX_POSITIONS", projected_daily, projected_open)

        if limits.max_positions_per_symbol is not None:
            max_symbol = self._positive_int(
                limits.max_positions_per_symbol, "max_positions_per_symbol"
            )
            if symbol_positions + 1 > max_symbol:
                return RiskDecision(False, "MAX_POSITIONS_PER_SYMBOL", projected_daily, projected_open)

        return RiskDecision(True, "ALLOWED", projected_daily, projected_open)

    def _money_risk_per_lot(
        self,
        *,
        distance: float,
        pip_size: float | None,
        pip_value_per_lot: float | None,
        tick_size: float | None,
        tick_value_per_lot: float | None,
    ) -> tuple[float, float | None]:
        if pip_size is not None or pip_value_per_lot is not None:
            if pip_size is None or pip_value_per_lot is None:
                raise RiskEngineError("pip_size_and_value_required_together")
            pip = self._positive(pip_size, "pip_size")
            pip_value = self._positive(pip_value_per_lot, "pip_value_per_lot")
            pips = distance / pip
            return pips * pip_value, pips

        if tick_size is not None or tick_value_per_lot is not None:
            if tick_size is None or tick_value_per_lot is None:
                raise RiskEngineError("tick_size_and_value_required_together")
            tick = self._positive(tick_size, "tick_size")
            tick_value = self._positive(tick_value_per_lot, "tick_value_per_lot")
            ticks = distance / tick
            return ticks * tick_value, None

        raise RiskEngineError("contract_risk_data_required")

    @staticmethod
    def _normalize_lot(raw: float, minimum: float, maximum: float, step: float) -> float:
        if raw <= 0:
            raise RiskEngineError("lot_must_be_positive")
        capped = min(raw, maximum)
        # Floor to step so percentage/fixed-money modes do not exceed target risk.
        steps = int((capped + 1e-12) / step)
        normalized = steps * step
        if normalized < minimum:
            normalized = minimum
        if normalized > maximum:
            normalized = maximum
        return round(normalized, 10)

    @staticmethod
    def _mode(value: RiskMode | str) -> RiskMode:
        if isinstance(value, RiskMode):
            return value
        raw = str(value or "").strip().upper().replace(" ", "_")
        aliases = {
            "BALANCE_%": RiskMode.BALANCE_PERCENT,
            "BALANCE_PERCENTAGE": RiskMode.BALANCE_PERCENT,
            "EQUITY_%": RiskMode.EQUITY_PERCENT,
            "EQUITY_PERCENTAGE": RiskMode.EQUITY_PERCENT,
            "MONEY": RiskMode.FIXED_MONEY,
            "LOT": RiskMode.FIXED_LOT,
        }
        if raw in aliases:
            return aliases[raw]
        try:
            return RiskMode(raw)
        except ValueError as exc:
            raise RiskEngineError(f"unsupported_risk_mode:{value}") from exc

    @staticmethod
    def _number(value: Any, name: str) -> float:
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise RiskEngineError(f"risk_value_not_numeric:{name}") from exc

    @classmethod
    def _positive(cls, value: Any, name: str) -> float:
        result = cls._number(value, name)
        if result <= 0:
            raise RiskEngineError(f"{name}_must_be_positive")
        return result

    @classmethod
    def _non_negative(cls, value: Any, name: str) -> float:
        result = cls._number(value, name)
        if result < 0:
            raise RiskEngineError(f"{name}_must_be_non_negative")
        return result

    @staticmethod
    def _positive_int(value: Any, name: str) -> int:
        try:
            result = int(value)
        except (TypeError, ValueError) as exc:
            raise RiskEngineError(f"{name}_must_be_positive_integer") from exc
        if result <= 0:
            raise RiskEngineError(f"{name}_must_be_positive_integer")
        return result

    @staticmethod
    def _non_negative_int(value: Any, name: str) -> int:
        try:
            result = int(value)
        except (TypeError, ValueError) as exc:
            raise RiskEngineError(f"{name}_must_be_non_negative_integer") from exc
        if result < 0:
            raise RiskEngineError(f"{name}_must_be_non_negative_integer")
        return result
