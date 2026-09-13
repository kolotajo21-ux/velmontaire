from __future__ import annotations

from typing import Any

from core.context import (
    ModuleExecutionResult,
    StrategyContext,
)
from core.entry_signal import (
    EntryDirection,
    EntryOrderType,
    EntrySignal,
    EntrySignalStatus,
)
from core.interfaces import (
    EntryModule,
)
from core.strategy import (
    ModuleRole,
    StrategyModuleDefinition,
)


class POILimitEntryModule(
    EntryModule
):
    """
    Универсальный limit-entry от active_poi.

    Поддерживает:
    - BULLISH -> BUY_LIMIT
    - BEARISH -> SELL_LIMIT
    - entry по midpoint / proximal / distal
    - SL за POI
    - TP по fixed RR
    """

    provider = "poi_limit_entry"
    role = ModuleRole.ENTRY
    version = "1.0.0"

    capabilities = (
        "limit_entry",
        "poi_entry",
        "fixed_rr_target",
        "stop_beyond_poi",
    )

    dependencies = (
        ModuleRole.POI,
    )

    def __init__(
        self,
        definition: (
            StrategyModuleDefinition
            | None
        ) = None,
    ) -> None:
        super().__init__(
            definition=definition
        )

        params = dict(
            self.definition.parameters
            or {}
        )

        self.entry_mode = str(
            params.get(
                "entry_mode",
                "MIDPOINT",
            )
        ).upper()

        self.rr = float(
            params.get(
                "rr",
                2.0,
            )
        )

        self.stop_buffer = float(
            params.get(
                "stop_buffer",
                0.0,
            )
        )

        self.minimum_rr = float(
            params.get(
                "minimum_rr",
                1.0,
            )
        )

    def execute(
        self,
        context: StrategyContext,
    ) -> ModuleExecutionResult:
        active_poi = context.get(
            "active_poi"
        )

        if not isinstance(
            active_poi,
            dict,
        ):
            return self.success(
                passed=False,
                data={
                    "entry_ready": False,
                    "reason": (
                        "active_poi_missing"
                    ),
                },
            )

        direction_raw = str(
            active_poi.get(
                "direction",
                "NEUTRAL",
            )
        ).upper()

        if direction_raw not in {
            "BULLISH",
            "BEARISH",
        }:
            return self.success(
                passed=False,
                data={
                    "entry_ready": False,
                    "reason": (
                        "poi_direction_invalid"
                    ),
                },
            )

        zone = active_poi.get(
            "active_zone"
        )

        if not isinstance(
            zone,
            dict,
        ):
            return self.success(
                passed=False,
                data={
                    "entry_ready": False,
                    "reason": (
                        "active_zone_missing"
                    ),
                },
            )

        high = self._float_value(
            zone,
            "high",
        )

        low = self._float_value(
            zone,
            "low",
        )

        if (
            high is None
            or low is None
            or high <= low
        ):
            return self.success(
                passed=False,
                data={
                    "entry_ready": False,
                    "reason": (
                        "poi_zone_invalid"
                    ),
                },
            )

        entry_price = (
            self._entry_price(
                direction=direction_raw,
                high=high,
                low=low,
            )
        )

        if entry_price is None:
            return self.success(
                passed=False,
                data={
                    "entry_ready": False,
                    "reason": (
                        "entry_mode_invalid"
                    ),
                },
            )

        if direction_raw == "BULLISH":
            direction = (
                EntryDirection.BUY
            )

            order_type = (
                EntryOrderType.BUY_LIMIT
            )

            stop_loss = (
                low - self.stop_buffer
            )

            risk_distance = (
                entry_price
                - stop_loss
            )

            take_profit = (
                entry_price
                + risk_distance
                * self.rr
            )

        else:
            direction = (
                EntryDirection.SELL
            )

            order_type = (
                EntryOrderType.SELL_LIMIT
            )

            stop_loss = (
                high + self.stop_buffer
            )

            risk_distance = (
                stop_loss
                - entry_price
            )

            take_profit = (
                entry_price
                - risk_distance
                * self.rr
            )

        if risk_distance <= 0:
            return self.success(
                passed=False,
                data={
                    "entry_ready": False,
                    "reason": (
                        "risk_distance_invalid"
                    ),
                },
            )

        if self.rr < self.minimum_rr:
            return self.success(
                passed=False,
                data={
                    "entry_ready": False,
                    "reason": (
                        "rr_below_minimum"
                    ),
                },
            )

        signal = EntrySignal(
            signal_id=(
                f"{self.provider}:"
                f"{context.symbol}:"
                f"{context.current_time}"
            ),
            symbol=context.symbol,
            direction=direction,
            order_type=order_type,
            entry_price=float(
                entry_price
            ),
            stop_loss=float(
                stop_loss
            ),
            take_profit=float(
                take_profit
            ),
            rr=float(
                self.rr
            ),
            status=(
                EntrySignalStatus.READY
            ),
            provider=self.provider,
            timeframe=(
                self.definition.timeframe
            ),
            poi_provider=(
                active_poi.get(
                    "provider"
                )
            ),
            poi_type=(
                active_poi.get(
                    "poi_type"
                )
            ),
            created_time=int(
                context.current_time
            ),
            confidence=float(
                active_poi.get(
                    "quality_score",
                    0.0,
                )
                or 0.0
            ),
            metadata={
                "entry_mode": (
                    self.entry_mode
                ),
                "stop_buffer": (
                    self.stop_buffer
                ),
                "poi_score": (
                    active_poi.get(
                        "score"
                    )
                ),
            },
        )

        valid, reason = (
            signal.validate()
        )

        if not valid:
            return self.failure(
                error=(
                    reason
                    or "entry_signal_invalid"
                ),
                data={
                    "entry_ready": False,
                    "signal": (
                        signal.to_dict()
                    ),
                },
            )

        context.put(
            "entry_signal",
            signal.to_dict(),
        )

        context.trade[
            "entry_signal"
        ] = signal.to_dict()

        return self.success(
            passed=True,
            data={
                "entry_ready": True,
                "signal": (
                    signal.to_dict()
                ),
            },
            diagnostics={
                "provider": (
                    self.provider
                ),
                "entry_mode": (
                    self.entry_mode
                ),
                "rr": (
                    self.rr
                ),
                "poi_provider": (
                    active_poi.get(
                        "provider"
                    )
                ),
            },
        )

    def _entry_price(
        self,
        *,
        direction: str,
        high: float,
        low: float,
    ) -> float | None:
        if self.entry_mode == "MIDPOINT":
            return (
                high + low
            ) / 2.0

        if self.entry_mode == "PROXIMAL":
            if direction == "BULLISH":
                return high

            return low

        if self.entry_mode == "DISTAL":
            if direction == "BULLISH":
                return low

            return high

        return None

    @staticmethod
    def _float_value(
        data: dict[str, Any],
        key: str,
    ) -> float | None:
        value = data.get(
            key
        )

        if value is None:
            return None

        try:
            return float(
                value
            )
        except (
            TypeError,
            ValueError,
        ):
            return None