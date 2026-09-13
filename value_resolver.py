from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from strategy_schema import ValueReference, ValueSourceType


class ValueResolutionError(ValueError):
    pass


@dataclass(slots=True)
class ValueResolutionContext:
    symbol: str | None = None
    current_time: int | datetime | None = None
    rates_by_timeframe: dict[str, Any] = field(default_factory=dict)
    indicators: dict[str, Any] = field(default_factory=dict)
    structure: dict[str, Any] = field(default_factory=dict)
    levels: dict[str, Any] = field(default_factory=dict)
    sessions: dict[str, Any] = field(default_factory=dict)
    trade: dict[str, Any] = field(default_factory=dict)
    account: dict[str, Any] = field(default_factory=dict)
    module_outputs: dict[str, Any] = field(default_factory=dict)
    custom: dict[str, Any] = field(default_factory=dict)


class UniversalValueResolver:
    """
    Resolves ValueReference through one fail-closed gateway.

    The resolver never guesses missing values.  A reference either resolves
    deterministically from context or raises ValueResolutionError.
    """

    def __init__(self) -> None:
        self._custom_resolvers: dict[str, Callable[[ValueReference, ValueResolutionContext], Any]] = {}

    def register(
        self,
        source: str,
        resolver: Callable[[ValueReference, ValueResolutionContext], Any],
    ) -> None:
        key = str(source or "").strip().lower()
        if not key:
            raise ValueError("custom_value_source_required")
        self._custom_resolvers[key] = resolver

    def resolve(self, ref: ValueReference, context: ValueResolutionContext) -> Any:
        kind = ref.source_type

        if kind == ValueSourceType.CONSTANT:
            return ref.constant
        if kind == ValueSourceType.PRICE:
            return self._resolve_price(ref, context)
        if kind == ValueSourceType.INDICATOR:
            return self._lookup(context.indicators, ref, "indicator")
        if kind == ValueSourceType.STRUCTURE:
            return self._lookup(context.structure, ref, "structure")
        if kind == ValueSourceType.LEVEL:
            return self._lookup(context.levels, ref, "level")
        if kind == ValueSourceType.SESSION:
            return self._lookup(context.sessions, ref, "session")
        if kind == ValueSourceType.TIME:
            return self._resolve_time(ref, context)
        if kind == ValueSourceType.TRADE_STATE:
            return self._lookup(context.trade, ref, "trade")
        if kind == ValueSourceType.ACCOUNT_STATE:
            return self._lookup(context.account, ref, "account")
        if kind == ValueSourceType.MODULE_OUTPUT:
            return self._resolve_module_output(ref, context)

        custom = self._custom_resolvers.get(ref.source.lower())
        if custom is not None:
            return custom(ref, context)

        if ref.source in context.custom:
            value = context.custom[ref.source]
            return self._extract(value, ref.field)

        raise ValueResolutionError(f"unsupported_value_source:{ref.source}")

    def _resolve_price(self, ref: ValueReference, context: ValueResolutionContext) -> Any:
        if not ref.timeframe:
            raise ValueResolutionError("price_timeframe_required")
        if not ref.field:
            raise ValueResolutionError("price_field_required")

        frame = self._timeframe_value(context.rates_by_timeframe, ref.timeframe)
        if frame is None:
            raise ValueResolutionError(f"price_timeframe_missing:{ref.timeframe}")

        field = ref.field.lower()

        # pandas DataFrame / Series compatible without importing pandas.
        try:
            if hasattr(frame, "iloc") and hasattr(frame, "columns"):
                if field not in [str(x).lower() for x in frame.columns]:
                    raise ValueResolutionError(f"price_field_missing:{field}")
                actual = next(x for x in frame.columns if str(x).lower() == field)
                return frame[actual].iloc[-1]
        except ValueResolutionError:
            raise
        except Exception as exc:
            raise ValueResolutionError(f"price_resolution_failed:{field}") from exc

        if isinstance(frame, list):
            if not frame:
                raise ValueResolutionError(f"price_frame_empty:{ref.timeframe}")
            return self._extract(frame[-1], ref.field)

        if isinstance(frame, dict):
            return self._extract(frame, ref.field)

        return self._extract(frame, ref.field)

    def _resolve_time(self, ref: ValueReference, context: ValueResolutionContext) -> Any:
        if context.current_time is None:
            raise ValueResolutionError("current_time_missing")

        value = context.current_time
        field = (ref.field or "timestamp").lower()

        if field in {"timestamp", "time", "current_time"}:
            return value

        if isinstance(value, datetime):
            mapping = {
                "hour": value.hour,
                "minute": value.minute,
                "weekday": value.weekday(),
                "date": value.date(),
            }
            if field in mapping:
                return mapping[field]

        raise ValueResolutionError(f"unsupported_time_field:{field}")

    def _resolve_module_output(
        self,
        ref: ValueReference,
        context: ValueResolutionContext,
    ) -> Any:
        provider = ref.provider
        if not provider:
            raise ValueResolutionError("module_output_provider_required")

        if provider not in context.module_outputs:
            raise ValueResolutionError(f"module_output_provider_missing:{provider}")

        output_name = ref.output or ref.field
        return self._extract(context.module_outputs[provider], output_name)

    def _lookup(
        self,
        mapping: dict[str, Any],
        ref: ValueReference,
        label: str,
    ) -> Any:
        candidates: list[str] = []
        if ref.field:
            candidates.append(ref.field)
        if ref.timeframe and ref.field:
            candidates.extend([
                f"{ref.timeframe}:{ref.field}",
                f"{ref.field}:{ref.timeframe}",
            ])

        for key in candidates:
            found, value = self._casefold_get(mapping, key)
            if found:
                return value

        # Nested timeframe -> field form.
        if ref.timeframe:
            frame = self._timeframe_value(mapping, ref.timeframe)
            if frame is not None:
                return self._extract(frame, ref.field)

        raise ValueResolutionError(
            f"{label}_value_missing:{ref.timeframe or '*'}:{ref.field or '*'}"
        )

    @staticmethod
    def _timeframe_value(mapping: dict[str, Any], timeframe: str) -> Any:
        target = str(timeframe).upper()
        for key, value in mapping.items():
            if str(key).upper() == target:
                return value
        return None

    @staticmethod
    def _casefold_get(mapping: dict[str, Any], key: str) -> tuple[bool, Any]:
        target = str(key).casefold()
        for candidate, value in mapping.items():
            if str(candidate).casefold() == target:
                return True, value
        return False, None

    @staticmethod
    def _extract(value: Any, field: str | None) -> Any:
        if field is None:
            return value

        if isinstance(value, dict):
            target = str(field).casefold()
            for key, item in value.items():
                if str(key).casefold() == target:
                    return item
            raise ValueResolutionError(f"value_field_missing:{field}")

        if hasattr(value, field):
            return getattr(value, field)

        try:
            return value[field]
        except Exception as exc:
            raise ValueResolutionError(f"value_field_missing:{field}") from exc
