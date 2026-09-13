from __future__ import annotations

from typing import Any

from core.context import ModuleExecutionResult, StrategyContext
from core.detector import DetectorContext
from core.interfaces import POIModule
from core.strategy import ModuleRole, StrategyModuleDefinition

from concepts.fvg.detector import FVGDetector, FVGDetectorConfig


class FVGPOIModule(POIModule):
    """
    FVG/iFVG -> universal POI adapter.

    Supports strategy-defined timeframes and evaluates only candles available
    at context.current_time, preventing future-bar leakage.
    """

    provider = "fvg_poi"
    role = ModuleRole.POI
    version = "1.1.0"

    capabilities = (
        "imbalance_detection",
        "fvg_detection",
        "ifvg_detection",
        "poi_detection",
        "fvg_quality",
        "fvg_mitigation",
    )

    dependencies = ()

    def __init__(
        self,
        definition: StrategyModuleDefinition | None = None,
    ) -> None:
        super().__init__(definition=definition)

    def execute(
        self,
        context: StrategyContext,
    ) -> ModuleExecutionResult:
        timeframes = self._resolve_timeframes(context)
        confirmation_mode = self._confirmation_mode()

        attempts: list[dict[str, Any]] = []
        candidates: list[dict[str, Any]] = []
        all_events: list[dict[str, Any]] = []

        for timeframe in timeframes:
            source_rates = context.get_rates(timeframe)
            cutoff_rates = self._cutoff_rates(
                source_rates,
                context.current_time,
            )

            if not cutoff_rates:
                attempts.append({
                    "timeframe": timeframe,
                    "success": True,
                    "poi_found": False,
                    "rejection_reason": "rates_missing_before_current_time",
                    "candles": 0,
                })
                continue

            detector = FVGDetector(
                FVGDetectorConfig(
                    timeframe=timeframe,
                    # The historical runner supplies only bars that are
                    # already closed at evaluation_time. A confirmation EVENT
                    # must therefore be allowed to discover an FVG whose third
                    # candle is the current just-closed bar. Reaction/POI
                    # events retain the previous-bar snapshot and validate the
                    # current interaction separately below.
                    use_last_closed_candle=(
                        not confirmation_mode
                    ),
                )
            )

            detector_context = DetectorContext(
                symbol=context.symbol,
                rates_by_timeframe={
                    timeframe: cutoff_rates,
                },
                current_time=context.current_time,
            )

            result = detector.analyze(
                detector_context,
                {},
            )

            attempt = {
                "timeframe": timeframe,
                "success": bool(result.success),
                "candles": len(cutoff_rates),
                "diagnostics": dict(result.diagnostics or {}),
            }

            if not result.success:
                attempt["poi_found"] = False
                attempt["rejection_reason"] = (
                    result.error or "fvg_detector_failed"
                )
                attempts.append(attempt)
                continue

            data = dict(result.data or {})
            events = [
                dict(event)
                for event in (result.events or [])
            ]

            for event in events:
                event.setdefault("timeframe", timeframe)
                all_events.append(event)

            best_fvg = self._extract_zone(
                data=data,
                key="best_fvg",
            )
            best_ifvg = self._extract_zone(
                data=data,
                key="best_ifvg",
            )

            if confirmation_mode:
                # Confirmation means a NEW FVG/IFVG completed on the current
                # closed candle. It is not a retracement/tap. The resulting
                # zone can now arm either an immediate MARKET entry or a
                # pending LIMIT that becomes active on the next bar.
                for event in events:
                    normalized = dict(event)

                    try:
                        event_end_time = int(
                            normalized.get(
                                "end_time",
                                normalized.get("time"),
                            )
                        )
                    except (TypeError, ValueError, OverflowError):
                        continue

                    if event_end_time != int(context.current_time):
                        continue

                    kind = str(
                        normalized.get("event_type")
                        or normalized.get("type")
                        or ""
                    ).strip().upper()

                    if kind not in {"FVG", "IFVG"}:
                        continue
                    if normalized.get("active") is False:
                        continue

                    normalized["timeframe"] = timeframe
                    normalized["_candidate_kind"] = kind
                    normalized["_confirmation_new_zone"] = True
                    candidates.append(normalized)
            else:
                for kind, zone in (
                    ("IFVG", best_ifvg),
                    ("FVG", best_fvg),
                ):
                    if zone is None:
                        continue

                    normalized = dict(zone)
                    normalized["timeframe"] = timeframe
                    normalized["_candidate_kind"] = kind

                    # A POI is executable only when the current candle has
                    # actually interacted with the zone. Merely having an active
                    # historical FVG/IFVG is not enough to pass the reaction step.
                    current_candle = cutoff_rates[-1]
                    candle_low = self._price_value(current_candle, "low")
                    candle_high = self._price_value(current_candle, "high")
                    candle_close = self._price_value(current_candle, "close")
                    zone_low = self._price_value(normalized, "low")
                    zone_high = self._price_value(normalized, "high")

                    touched = (
                        candle_low is not None
                        and candle_high is not None
                        and zone_low is not None
                        and zone_high is not None
                        and candle_high >= zone_low
                        and candle_low <= zone_high
                    )

                    zone_direction = str(
                        normalized.get(
                            "zone_type",
                            normalized.get("direction", ""),
                        )
                    ).strip().upper()

                    invalidation_valid = False

                    if (
                        candle_close is not None
                        and zone_low is not None
                        and zone_high is not None
                    ):
                        if zone_direction == "BULLISH":
                            invalidation_valid = (
                                candle_close > zone_low
                            )
                        elif zone_direction == "BEARISH":
                            invalidation_valid = (
                                candle_close < zone_high
                            )

                    normalized["_reaction_touched"] = bool(touched)
                    normalized["_invalidation_side_valid"] = bool(
                        invalidation_valid
                    )

                    if touched and invalidation_valid:
                        candidates.append(normalized)
                    else:
                        reason = (
                            "current_candle_did_not_touch_zone"
                            if not touched
                            else "zone_invalidation_wrong_side_of_current_price"
                        )

                        attempt.setdefault("rejected_zones", []).append({
                            "kind": kind,
                            "reason": reason,
                            "zone_direction": zone_direction,
                            "candle_low": candle_low,
                            "candle_high": candle_high,
                            "candle_close": candle_close,
                            "zone_low": zone_low,
                            "zone_high": zone_high,
                        })

            attempt["poi_found"] = bool(
                any(
                    str(item.get("timeframe") or "").upper()
                    == timeframe
                    for item in candidates
                )
                if confirmation_mode
                else (
                    best_fvg is not None
                    or best_ifvg is not None
                )
            )

            if not attempt["poi_found"]:
                attempt["rejection_reason"] = (
                    attempt["diagnostics"].get("rejection_reason")
                    or "no_active_fvg_or_ifvg"
                )

            attempts.append(attempt)

        active_zone = self._select_best_candidate(
            candidates
        )

        poi_found = active_zone is not None

        if active_zone is not None:
            candidate_kind = str(
                active_zone.pop(
                    "_candidate_kind",
                    "",
                )
            ).upper()
            active_zone.pop(
                "_reaction_touched",
                None,
            )
            active_zone.pop(
                "_invalidation_side_valid",
                None,
            )
            active_zone.pop(
                "_confirmation_new_zone",
                None,
            )

            zone_type = str(
                active_zone.get(
                    "zone_type",
                    "",
                )
            ).upper()

            event_type = str(
                active_zone.get(
                    "event_type",
                    candidate_kind,
                )
            ).upper()

            direction = self._direction_from_zone(
                active_zone
            )
            selected_timeframe = str(
                active_zone.get(
                    "timeframe",
                    "",
                )
            ).upper()
        else:
            candidate_kind = None
            zone_type = None
            event_type = None
            direction = "NEUTRAL"
            selected_timeframe = None

        best_fvg = self._best_of_kind(
            candidates,
            "FVG",
        )
        best_ifvg = self._best_of_kind(
            candidates,
            "IFVG",
        )

        normalized_data = {
            "poi_found": bool(poi_found),
            "provider_type": event_type,
            "zone_type": zone_type,
            "direction": direction,
            "timeframe": selected_timeframe,
            "best_fvg": best_fvg,
            "best_ifvg": best_ifvg,
            "active_zone": (
                dict(active_zone)
                if active_zone is not None
                else None
            ),
            "event_count": len(all_events),
            "raw": {
                "timeframe_attempts": attempts,
            },
        }

        diagnostics = {
            "adapter": "FVGPOIModule",
            "provider": self.provider,
            "poi_found": bool(poi_found),
            "direction": direction,
            "active_event_type": event_type,
            "selected_timeframe": selected_timeframe,
            "evaluated_timeframes": list(timeframes),
            "current_time": int(context.current_time),
            "evaluation_mode": (
                "NEW_FVG_CONFIRMATION"
                if confirmation_mode
                else "CURRENT_BAR_REACTION"
            ),
            "candidate_count": len(candidates),
            "timeframe_attempts": attempts,
        }

        return self.success(
            passed=poi_found,
            data=normalized_data,
            events=all_events,
            diagnostics=diagnostics,
        )

    def _confirmation_mode(self) -> bool:
        definition_metadata = dict(
            getattr(self.definition, "metadata", {}) or {}
        )
        definition_parameters = dict(
            getattr(self.definition, "parameters", {}) or {}
        )
        event_metadata = dict(
            definition_parameters.get("event_metadata") or {}
        )

        semantic = str(
            event_metadata.get("semantic_event")
            or definition_metadata.get("semantic_event")
            or ""
        ).strip().upper()

        return semantic == "FVG_IFVG_CONFIRMATION"

    def _resolve_timeframes(
        self,
        context: StrategyContext,
    ) -> list[str]:
        candidates: list[str] = []

        definition_metadata = getattr(
            self.definition,
            "metadata",
            {},
        )
        definition_parameters = getattr(
            self.definition,
            "parameters",
            {},
        )

        for source in (
            definition_metadata,
            definition_parameters,
        ):
            if not isinstance(source, dict):
                continue

            raw = (
                source.get("timeframes")
                or source.get("timeframe")
            )

            if isinstance(raw, str):
                candidates.append(raw)
            elif isinstance(raw, (list, tuple, set)):
                candidates.extend(
                    str(value)
                    for value in raw
                )

        if not candidates:
            strategy_dict = (
                context.strategy.to_dict()
                if hasattr(context.strategy, "to_dict")
                else {}
            )
            self._collect_timeframes(
                strategy_dict,
                candidates,
            )

        available = {
            str(key).upper()
            for key in context.rates_by_timeframe
        }

        normalized: list[str] = []

        for timeframe in candidates:
            value = str(timeframe).strip().upper()
            if (
                value
                and value in available
                and value not in normalized
            ):
                normalized.append(value)

        # Preserve the intended HTF preference when schema metadata was not
        # propagated into the module definition.
        if not normalized:
            for value in ("H4", "H1"):
                if value in available:
                    normalized.append(value)

        if not normalized:
            normalized = sorted(available)

        return normalized

    @classmethod
    def _collect_timeframes(
        cls,
        value: Any,
        output: list[str],
    ) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                key_lower = str(key).lower()

                if key_lower in {
                    "timeframe",
                    "timeframes",
                }:
                    if isinstance(child, str):
                        output.append(child)
                    elif isinstance(
                        child,
                        (list, tuple, set),
                    ):
                        output.extend(
                            str(item)
                            for item in child
                        )

                cls._collect_timeframes(
                    child,
                    output,
                )

        elif isinstance(value, list):
            for child in value:
                cls._collect_timeframes(
                    child,
                    output,
                )

    @staticmethod
    def _cutoff_rates(
        rates: Any,
        current_time: int,
    ) -> list[Any]:
        if rates is None:
            return []

        # pandas.DataFrame must be converted by rows.
        # `list(DataFrame)` returns column names and `rates or []`
        # raises "truth value of a DataFrame is ambiguous".
        if hasattr(rates, "columns") and hasattr(rates, "to_dict"):
            try:
                candles = list(
                    rates.to_dict(
                        orient="records"
                    )
                )
            except Exception:
                return []
        else:
            try:
                candles = list(rates)
            except (TypeError, ValueError):
                return []

        cutoff: list[Any] = []

        for candle in candles:
            candle_time = FVGPOIModule._candle_time(
                candle
            )

            if candle_time is None:
                cutoff.append(candle)
                continue

            if candle_time <= int(current_time):
                cutoff.append(candle)

        return cutoff

    @staticmethod
    def _price_value(
        source: Any,
        key: str,
    ) -> float | None:
        value: Any = None

        if isinstance(source, dict):
            value = source.get(key)
        else:
            try:
                value = source[key]
            except (KeyError, IndexError, TypeError):
                value = getattr(source, key, None)

        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError, OverflowError):
            return None

    @staticmethod
    def _candle_time(
        candle: Any,
    ) -> int | None:
        value: Any = None

        if isinstance(candle, dict):
            value = candle.get("time")
        else:
            try:
                value = candle["time"]
            except (
                KeyError,
                IndexError,
                TypeError,
            ):
                value = getattr(
                    candle,
                    "time",
                    None,
                )

        if value is None:
            return None

        try:
            if hasattr(value, "timestamp"):
                return int(value.timestamp())
            return int(value)
        except (
            TypeError,
            ValueError,
            OverflowError,
        ):
            return None

    @staticmethod
    def _select_best_candidate(
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if not candidates:
            return None

        def score(
            zone: dict[str, Any],
        ) -> tuple[float, int]:
            quality_raw = zone.get(
                "quality_score",
                zone.get("quality", 0.0),
            )
            time_raw = zone.get(
                "end_time",
                zone.get("time", 0),
            )

            try:
                quality = float(quality_raw or 0.0)
            except (TypeError, ValueError):
                quality = 0.0

            try:
                timestamp = int(time_raw or 0)
            except (TypeError, ValueError):
                timestamp = 0

            return quality, timestamp

        return dict(
            max(
                candidates,
                key=score,
            )
        )

    @staticmethod
    def _best_of_kind(
        candidates: list[dict[str, Any]],
        kind: str,
    ) -> dict[str, Any] | None:
        matching = [
            zone
            for zone in candidates
            if str(
                zone.get(
                    "_candidate_kind",
                    "",
                )
            ).upper()
            == kind.upper()
        ]

        selected = FVGPOIModule._select_best_candidate(
            matching
        )

        if selected is None:
            return None

        selected.pop(
            "_candidate_kind",
            None,
        )
        selected.pop(
            "_reaction_touched",
            None,
        )
        selected.pop(
            "_invalidation_side_valid",
            None,
        )
        return selected

    @staticmethod
    def _extract_zone(
        *,
        data: dict[str, Any],
        key: str,
    ) -> dict[str, Any] | None:
        value = data.get(key)

        if isinstance(value, dict):
            return dict(value)

        return None

    @staticmethod
    def _direction_from_zone(
        zone: dict[str, Any] | None,
    ) -> str:
        if zone is None:
            return "NEUTRAL"

        zone_type = str(
            zone.get(
                "zone_type",
                zone.get("direction", ""),
            )
        ).upper()

        if zone_type in {
            "BULLISH",
            "BEARISH",
        }:
            return zone_type

        return "NEUTRAL"
