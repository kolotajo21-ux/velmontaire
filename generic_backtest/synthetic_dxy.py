from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import pandas as pd


# Fixed ICE basket weights expressed through the broker's available FX pair
# orientation. EURUSD/GBPUSD fall when USD strengthens, hence negative powers.
# The other four quoted pairs rise when USD strengthens, hence positive powers.
DXY_COMPONENT_EXPONENTS: tuple[tuple[str, float], ...] = (
    ("EURUSD", -0.576),
    ("USDJPY", 0.136),
    ("GBPUSD", -0.119),
    ("USDCAD", 0.091),
    ("USDSEK", 0.042),
    ("USDCHF", 0.036),
)


@dataclass(slots=True)
class SyntheticDXYResult:
    rates: pd.DataFrame
    components: list[str]
    normalization: str = "FIRST_COMMON_CLOSE_EQUALS_100"
    ohlc_policy: str = "OPEN_CLOSE_DIRECTIONAL_PROXY"


def build_synthetic_dxy(
    component_rates: dict[str, pd.DataFrame],
) -> SyntheticDXYResult:
    """
    Build a proportional DXY directional proxy from synchronized FX bars.

    Open and close use the fixed-weight geometric basket. High/low are the
    extrema of synthetic open/close, intentionally avoiding fabricated
    cross-pair intrabar extremes whose timestamps are not available in H4 OHLC.
    The absolute scale is normalized to 100; percentage/directional movement is
    invariant to that scale and is what the strategy's H4 context consumes.
    """
    merged: pd.DataFrame | None = None

    for symbol, _ in DXY_COMPONENT_EXPONENTS:
        rates = component_rates.get(symbol)
        if rates is None or rates.empty:
            raise RuntimeError(f"synthetic_dxy_component_missing:{symbol}")
        required = {"time", "open", "close"}
        if not required.issubset(rates.columns):
            raise RuntimeError(f"synthetic_dxy_component_invalid:{symbol}")

        selected = (
            rates[["time", "open", "close"]]
            .copy()
            .sort_values("time")
            .drop_duplicates(subset=["time"], keep="last")
        )
        selected = selected.rename(
            columns={
                "open": f"{symbol}_open",
                "close": f"{symbol}_close",
            }
        )
        merged = (
            selected
            if merged is None
            else merged.merge(selected, on="time", how="inner")
        )

    if merged is None or merged.empty:
        raise RuntimeError("synthetic_dxy_no_common_bars")

    for symbol, _ in DXY_COMPONENT_EXPONENTS:
        for field in ("open", "close"):
            column = f"{symbol}_{field}"
            merged[column] = pd.to_numeric(merged[column], errors="coerce")
            if merged[column].isna().any() or (merged[column] <= 0).any():
                raise RuntimeError(
                    f"synthetic_dxy_non_positive_price:{symbol}:{field}"
                )

    def geometric_value(row: pd.Series, field: str) -> float:
        log_value = 0.0
        for symbol, exponent in DXY_COMPONENT_EXPONENTS:
            log_value += exponent * math.log(float(row[f"{symbol}_{field}"]))
        return math.exp(log_value)

    raw_open = merged.apply(lambda row: geometric_value(row, "open"), axis=1)
    raw_close = merged.apply(lambda row: geometric_value(row, "close"), axis=1)
    anchor = float(raw_close.iloc[0])
    if not math.isfinite(anchor) or anchor <= 0:
        raise RuntimeError("synthetic_dxy_normalization_anchor_invalid")

    scale = 100.0 / anchor
    synthetic_open = raw_open * scale
    synthetic_close = raw_close * scale

    rates = pd.DataFrame(
        {
            "time": merged["time"].astype("int64"),
            "open": synthetic_open.astype("float64"),
            "high": pd.concat(
                [synthetic_open, synthetic_close],
                axis=1,
            ).max(axis=1),
            "low": pd.concat(
                [synthetic_open, synthetic_close],
                axis=1,
            ).min(axis=1),
            "close": synthetic_close.astype("float64"),
            "tick_volume": 0,
            "spread": 0,
            "real_volume": 0,
        }
    )
    if len(rates) < 20:
        raise RuntimeError(
            f"synthetic_dxy_insufficient_common_bars:{len(rates)}"
        )

    return SyntheticDXYResult(
        rates=rates.reset_index(drop=True),
        components=[symbol for symbol, _ in DXY_COMPONENT_EXPONENTS],
    )


def load_synthetic_dxy(
    history_source: Any,
    *,
    timeframe: str,
    date_from: Any,
    date_to: Any,
) -> SyntheticDXYResult:
    components: dict[str, pd.DataFrame] = {}
    for symbol, _ in DXY_COMPONENT_EXPONENTS:
        try:
            loaded = history_source.load(
                symbol=symbol,
                timeframe=timeframe,
                date_from=date_from,
                date_to=date_to,
            )
        except Exception as exc:
            raise RuntimeError(
                "synthetic_dxy_component_load_failed:"
                f"{symbol}:{type(exc).__name__}:{exc}"
            ) from exc
        components[symbol] = loaded.rates.copy()

    return build_synthetic_dxy(components)
