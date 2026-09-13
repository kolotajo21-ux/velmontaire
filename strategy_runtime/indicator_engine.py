from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from math import sqrt
from typing import Any, Iterable


class IndicatorEvaluationError(ValueError):
    """Fail-closed indicator calculation error."""


class IndicatorType(str, Enum):
    EMA = "EMA"
    SMA = "SMA"
    RSI = "RSI"
    ATR = "ATR"
    MACD = "MACD"
    ADX = "ADX"
    STOCHASTIC = "STOCHASTIC"
    BOLLINGER_BANDS = "BOLLINGER_BANDS"
    VWAP = "VWAP"


@dataclass(frozen=True, slots=True)
class IndicatorRequest:
    indicator: IndicatorType | str
    timeframe: str
    period: int | None = None
    source: str = "close"
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class IndicatorResult:
    indicator: IndicatorType
    timeframe: str
    values: dict[str, float]
    parameters: dict[str, Any]

    def value(self, name: str = "value") -> float:
        if name not in self.values:
            raise IndicatorEvaluationError(f"indicator_output_missing:{name}")
        return self.values[name]


class UniversalIndicatorEngine:
    """
    Dependency-free deterministic indicator gateway.

    Input rates may be:
      - list[dict] with open/high/low/close/(tick_volume|real_volume|volume)
      - pandas-like DataFrame supporting to_dict("records")

    Missing history/fields/invalid parameters fail closed.
    """

    _ALIASES = {
        "EMA": IndicatorType.EMA,
        "EXPONENTIAL_MOVING_AVERAGE": IndicatorType.EMA,
        "SMA": IndicatorType.SMA,
        "SIMPLE_MOVING_AVERAGE": IndicatorType.SMA,
        "RSI": IndicatorType.RSI,
        "ATR": IndicatorType.ATR,
        "MACD": IndicatorType.MACD,
        "ADX": IndicatorType.ADX,
        "STOCHASTIC": IndicatorType.STOCHASTIC,
        "STOCH": IndicatorType.STOCHASTIC,
        "BOLLINGER_BANDS": IndicatorType.BOLLINGER_BANDS,
        "BOLLINGER": IndicatorType.BOLLINGER_BANDS,
        "BB": IndicatorType.BOLLINGER_BANDS,
        "VWAP": IndicatorType.VWAP,
    }

    def normalize(self, value: IndicatorType | str) -> IndicatorType:
        if isinstance(value, IndicatorType):
            return value
        raw = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
        result = self._ALIASES.get(raw)
        if result is None:
            raise IndicatorEvaluationError(f"unsupported_indicator:{value}")
        return result

    def calculate(self, request: IndicatorRequest, rates: Any) -> IndicatorResult:
        kind = self.normalize(request.indicator)
        rows = self._rows(rates)
        tf = str(request.timeframe or "").strip().upper()
        if not tf:
            raise IndicatorEvaluationError("indicator_timeframe_required")

        p = dict(request.parameters)
        source = str(request.source or "close").strip().lower()

        if kind == IndicatorType.EMA:
            period = self._period(request.period, p, default=20)
            values = {"value": self._ema(self._series(rows, source), period)[-1]}
            params = {"period": period, "source": source}
        elif kind == IndicatorType.SMA:
            period = self._period(request.period, p, default=20)
            values = {"value": self._sma(self._series(rows, source), period)}
            params = {"period": period, "source": source}
        elif kind == IndicatorType.RSI:
            period = self._period(request.period, p, default=14)
            values = {"value": self._rsi(self._series(rows, source), period)}
            params = {"period": period, "source": source}
        elif kind == IndicatorType.ATR:
            period = self._period(request.period, p, default=14)
            values = {"value": self._atr(rows, period)}
            params = {"period": period}
        elif kind == IndicatorType.MACD:
            fast = self._positive_int(p.get("fast", 12), "fast")
            slow = self._positive_int(p.get("slow", 26), "slow")
            signal = self._positive_int(p.get("signal", 9), "signal")
            if fast >= slow:
                raise IndicatorEvaluationError("macd_fast_must_be_less_than_slow")
            values = self._macd(self._series(rows, source), fast, slow, signal)
            params = {"fast": fast, "slow": slow, "signal": signal, "source": source}
        elif kind == IndicatorType.ADX:
            period = self._period(request.period, p, default=14)
            values = self._adx(rows, period)
            params = {"period": period}
        elif kind == IndicatorType.STOCHASTIC:
            k_period = self._positive_int(p.get("k_period", request.period or 14), "k_period")
            d_period = self._positive_int(p.get("d_period", 3), "d_period")
            values = self._stochastic(rows, k_period, d_period)
            params = {"k_period": k_period, "d_period": d_period}
        elif kind == IndicatorType.BOLLINGER_BANDS:
            period = self._period(request.period, p, default=20)
            deviation = self._positive_float(p.get("deviation", 2.0), "deviation")
            values = self._bollinger(self._series(rows, source), period, deviation)
            params = {"period": period, "deviation": deviation, "source": source}
        elif kind == IndicatorType.VWAP:
            values = {"value": self._vwap(rows)}
            params = {"source": "typical_price"}
        else:
            raise IndicatorEvaluationError(f"unsupported_indicator:{kind.value}")

        return IndicatorResult(kind, tf, values, params)

    @staticmethod
    def _rows(rates: Any) -> list[dict[str, Any]]:
        if hasattr(rates, "to_dict"):
            try:
                rows = rates.to_dict("records")
                if isinstance(rows, list):
                    return [dict(x) for x in rows]
            except Exception:
                pass
        if isinstance(rates, (list, tuple)):
            rows = [dict(x) for x in rates]
            if rows:
                return rows
        raise IndicatorEvaluationError("indicator_rates_required")

    @staticmethod
    def _series(rows: list[dict[str, Any]], field: str) -> list[float]:
        out = []
        for row in rows:
            if field not in row:
                raise IndicatorEvaluationError(f"indicator_source_missing:{field}")
            out.append(float(row[field]))
        return out

    @staticmethod
    def _positive_int(value: Any, name: str) -> int:
        try:
            v = int(value)
        except (TypeError, ValueError) as exc:
            raise IndicatorEvaluationError(f"invalid_indicator_parameter:{name}") from exc
        if v <= 0:
            raise IndicatorEvaluationError(f"invalid_indicator_parameter:{name}")
        return v

    @staticmethod
    def _positive_float(value: Any, name: str) -> float:
        try:
            v = float(value)
        except (TypeError, ValueError) as exc:
            raise IndicatorEvaluationError(f"invalid_indicator_parameter:{name}") from exc
        if v <= 0:
            raise IndicatorEvaluationError(f"invalid_indicator_parameter:{name}")
        return v

    def _period(self, direct: Any, params: dict[str, Any], *, default: int) -> int:
        return self._positive_int(direct if direct is not None else params.get("period", default), "period")

    @staticmethod
    def _need(values: list[Any], count: int, label: str) -> None:
        if len(values) < count:
            raise IndicatorEvaluationError(f"insufficient_history:{label}:{count}:{len(values)}")

    @classmethod
    def _sma(cls, values: list[float], period: int) -> float:
        cls._need(values, period, "SMA")
        return sum(values[-period:]) / period

    @classmethod
    def _ema(cls, values: list[float], period: int) -> list[float]:
        cls._need(values, period, "EMA")
        seed = sum(values[:period]) / period
        result = [seed]
        alpha = 2.0 / (period + 1.0)
        for value in values[period:]:
            result.append(alpha * value + (1.0 - alpha) * result[-1])
        return result

    @classmethod
    def _rsi(cls, closes: list[float], period: int) -> float:
        cls._need(closes, period + 1, "RSI")
        gains, losses = [], []
        for a, b in zip(closes[:-1], closes[1:]):
            delta = b - a
            gains.append(max(delta, 0.0))
            losses.append(max(-delta, 0.0))
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        for gain, loss in zip(gains[period:], losses[period:]):
            avg_gain = ((period - 1) * avg_gain + gain) / period
            avg_loss = ((period - 1) * avg_loss + loss) / period
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
        rs = avg_gain / avg_loss
        return 100.0 - 100.0 / (1.0 + rs)

    @classmethod
    def _true_ranges(cls, rows: list[dict[str, Any]]) -> list[float]:
        cls._need(rows, 2, "TR")
        tr = []
        for i in range(1, len(rows)):
            high = float(rows[i]["high"])
            low = float(rows[i]["low"])
            prev_close = float(rows[i - 1]["close"])
            tr.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
        return tr

    @classmethod
    def _atr(cls, rows: list[dict[str, Any]], period: int) -> float:
        tr = cls._true_ranges(rows)
        cls._need(tr, period, "ATR")
        atr = sum(tr[:period]) / period
        for value in tr[period:]:
            atr = ((period - 1) * atr + value) / period
        return atr

    @classmethod
    def _macd(cls, closes: list[float], fast: int, slow: int, signal: int) -> dict[str, float]:
        cls._need(closes, slow + signal, "MACD")
        # Calculate EMA streams on aligned suffix by direct rolling prefixes.
        macd_line = []
        for end in range(slow, len(closes) + 1):
            subset = closes[:end]
            fast_v = cls._ema(subset, fast)[-1]
            slow_v = cls._ema(subset, slow)[-1]
            macd_line.append(fast_v - slow_v)
        cls._need(macd_line, signal, "MACD_SIGNAL")
        signal_v = cls._ema(macd_line, signal)[-1]
        macd_v = macd_line[-1]
        return {"macd": macd_v, "signal": signal_v, "histogram": macd_v - signal_v}

    @classmethod
    def _adx(cls, rows: list[dict[str, Any]], period: int) -> dict[str, float]:
        cls._need(rows, period * 2 + 1, "ADX")
        tr, plus_dm, minus_dm = [], [], []
        for i in range(1, len(rows)):
            high = float(rows[i]["high"])
            low = float(rows[i]["low"])
            prev_high = float(rows[i - 1]["high"])
            prev_low = float(rows[i - 1]["low"])
            prev_close = float(rows[i - 1]["close"])
            up = high - prev_high
            down = prev_low - low
            plus_dm.append(up if up > down and up > 0 else 0.0)
            minus_dm.append(down if down > up and down > 0 else 0.0)
            tr.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))

        sm_tr = sum(tr[:period])
        sm_plus = sum(plus_dm[:period])
        sm_minus = sum(minus_dm[:period])
        dx_values = []
        for i in range(period, len(tr) + 1):
            if i > period:
                sm_tr = sm_tr - sm_tr / period + tr[i - 1]
                sm_plus = sm_plus - sm_plus / period + plus_dm[i - 1]
                sm_minus = sm_minus - sm_minus / period + minus_dm[i - 1]
            plus_di = 100.0 * sm_plus / sm_tr if sm_tr else 0.0
            minus_di = 100.0 * sm_minus / sm_tr if sm_tr else 0.0
            denom = plus_di + minus_di
            dx_values.append(100.0 * abs(plus_di - minus_di) / denom if denom else 0.0)

        cls._need(dx_values, period, "ADX_DX")
        adx = sum(dx_values[:period]) / period
        for dx in dx_values[period:]:
            adx = ((period - 1) * adx + dx) / period
        return {"adx": adx, "plus_di": plus_di, "minus_di": minus_di}

    @classmethod
    def _stochastic(cls, rows: list[dict[str, Any]], k_period: int, d_period: int) -> dict[str, float]:
        cls._need(rows, k_period + d_period - 1, "STOCHASTIC")
        ks = []
        for end in range(k_period, len(rows) + 1):
            window = rows[end - k_period:end]
            high = max(float(x["high"]) for x in window)
            low = min(float(x["low"]) for x in window)
            close = float(window[-1]["close"])
            ks.append(50.0 if high == low else 100.0 * (close - low) / (high - low))
        cls._need(ks, d_period, "STOCHASTIC_D")
        return {"k": ks[-1], "d": sum(ks[-d_period:]) / d_period}

    @classmethod
    def _bollinger(cls, values: list[float], period: int, deviation: float) -> dict[str, float]:
        cls._need(values, period, "BOLLINGER_BANDS")
        window = values[-period:]
        middle = sum(window) / period
        variance = sum((x - middle) ** 2 for x in window) / period
        std = sqrt(variance)
        return {
            "middle": middle,
            "upper": middle + deviation * std,
            "lower": middle - deviation * std,
        }

    @classmethod
    def _vwap(cls, rows: list[dict[str, Any]]) -> float:
        if not rows:
            raise IndicatorEvaluationError("indicator_rates_required")
        pv = 0.0
        volume_sum = 0.0
        for row in rows:
            high, low, close = float(row["high"]), float(row["low"]), float(row["close"])
            volume = row.get("real_volume", row.get("tick_volume", row.get("volume")))
            if volume is None:
                raise IndicatorEvaluationError("vwap_volume_missing")
            volume = float(volume)
            typical = (high + low + close) / 3.0
            pv += typical * volume
            volume_sum += volume
        if volume_sum <= 0:
            raise IndicatorEvaluationError("vwap_volume_zero")
        return pv / volume_sum
