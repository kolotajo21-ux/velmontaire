from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class BacktestRunFingerprint:
    strategy_version_id: str
    market_data_hash: str
    execution_config_hash: str
    input_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BacktestReliabilityService:
    """
    Deterministic/reliability boundary for product backtests.

    It does not run the strategy itself. It validates and fingerprints the
    immutable inputs that a backtest engine must consume.
    """

    REQUIRED_CONFIG = (
        "spread_model",
        "commission_model",
        "intrabar_priority",
        "timezone",
    )

    def fingerprint(
        self,
        *,
        strategy_version_id: str,
        strategy_schema: dict[str, Any],
        candles: Iterable[dict[str, Any]],
        execution_config: dict[str, Any],
    ) -> BacktestRunFingerprint:
        if not str(strategy_version_id).strip():
            raise ValueError("strategy_version_id_required")

        self._validate_config(execution_config)
        normalized_candles = self._validate_and_normalize_candles(candles)

        market_hash = self._hash(normalized_candles)
        config_hash = self._hash(execution_config)
        total_hash = self._hash({
            "strategy_version_id": strategy_version_id,
            "strategy_schema": strategy_schema,
            "market_data_hash": market_hash,
            "execution_config_hash": config_hash,
        })

        return BacktestRunFingerprint(
            strategy_version_id=strategy_version_id,
            market_data_hash=market_hash,
            execution_config_hash=config_hash,
            input_hash=total_hash,
        )

    def assert_reproducible(
        self,
        *,
        first_fingerprint: BacktestRunFingerprint,
        second_fingerprint: BacktestRunFingerprint,
        first_result: dict[str, Any],
        second_result: dict[str, Any],
    ) -> None:
        if first_fingerprint.input_hash != second_fingerprint.input_hash:
            raise RuntimeError("backtest_inputs_not_identical")
        if self._canonical(first_result) != self._canonical(second_result):
            raise RuntimeError("determinism_violation_same_input_different_output")

    def validate_signal_time(
        self,
        *,
        decision_time: str,
        latest_available_candle_time: str,
    ) -> None:
        decision = self._dt(decision_time)
        candle = self._dt(latest_available_candle_time)
        if candle > decision:
            raise RuntimeError("lookahead_data_detected")

    def _validate_config(self, config: dict[str, Any]) -> None:
        if not isinstance(config, dict):
            raise ValueError("execution_config_required")
        missing = [k for k in self.REQUIRED_CONFIG if k not in config]
        if missing:
            raise ValueError("execution_config_incomplete:" + ",".join(missing))

    def _validate_and_normalize_candles(
        self,
        candles: Iterable[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rows = []
        previous = None
        for raw in candles:
            if not isinstance(raw, dict):
                raise ValueError("candle_must_be_mapping")
            for key in ("time", "open", "high", "low", "close"):
                if key not in raw:
                    raise ValueError(f"candle_{key}_required")

            dt = self._dt(str(raw["time"]))
            if previous is not None and dt <= previous:
                raise RuntimeError("market_data_time_not_strictly_increasing")
            previous = dt

            rows.append({
                "time": dt.isoformat(),
                "open": float(raw["open"]),
                "high": float(raw["high"]),
                "low": float(raw["low"]),
                "close": float(raw["close"]),
                "volume": float(raw.get("volume", 0.0)),
            })
        return rows

    @staticmethod
    def _dt(value: str) -> datetime:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("invalid_timestamp") from exc
        if dt.tzinfo is None:
            raise ValueError("timezone_aware_timestamp_required")
        return dt.astimezone(timezone.utc)

    @classmethod
    def _hash(cls, value: Any) -> str:
        return hashlib.sha256(cls._canonical(value).encode("utf-8")).hexdigest()

    @staticmethod
    def _canonical(value: Any) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
