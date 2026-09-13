from __future__ import annotations

import dataclasses
import types

from enum import Enum
from typing import (
    Any,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)

from strategy_schema import StrategySchema


def strategy_schema_from_dict(
    payload: dict[str, Any],
) -> StrategySchema:
    """
    Strict recursive dataclass/enum decoder for StrategySchema.

    Important normalization:
    collection fields such as symbols/timeframes may arrive from persisted
    JSON as a single string. A string must be treated as ONE collection item,
    never iterated character-by-character.
    """
    if not isinstance(payload, dict):
        raise TypeError(
            "strategy_schema_payload_must_be_object"
        )

    return _decode(
        StrategySchema,
        payload,
    )


def _decode(
    tp: Any,
    value: Any,
) -> Any:
    if value is None:
        return None

    origin = get_origin(tp)
    args = get_args(tp)

    # ==========================================================
    # LIST / TUPLE / SET
    # ==========================================================
    if origin in (
        list,
        tuple,
        set,
    ):
        inner = (
            args[0]
            if args
            else Any
        )

        # Critical fix:
        # list("EURUSD") would become:
        # ["E", "U", "R", "U", "S", "D"]
        #
        # For schema collection fields a string represents
        # one logical item.
        if isinstance(value, str):
            raw = value.strip()

            if not raw:
                source_items = []
            else:
                source_items = [raw]

        elif isinstance(
            value,
            (
                list,
                tuple,
                set,
            ),
        ):
            source_items = list(value)

        else:
            raise TypeError(
                "collection_payload_must_be_array_or_string:"
                f"{type(value).__name__}"
            )

        items = [
            _decode(
                inner,
                item,
            )
            for item in source_items
        ]

        if origin is list:
            return items

        if origin is tuple:
            return tuple(items)

        return set(items)

    # ==========================================================
    # DICT
    # ==========================================================
    if origin is dict:
        if not isinstance(
            value,
            dict,
        ):
            raise TypeError(
                "dict_payload_must_be_object"
            )

        key_type, value_type = (
            args
            if len(args) == 2
            else (Any, Any)
        )

        return {
            _decode(
                key_type,
                key,
            ): _decode(
                value_type,
                item,
            )
            for key, item
            in value.items()
        }

    # ==========================================================
    # UNION / OPTIONAL
    # ==========================================================
    if origin in (
        Union,
        types.UnionType,
    ):
        non_none = [
            candidate
            for candidate in args
            if candidate is not type(None)
        ]

        last_error = None

        for candidate in non_none:
            try:
                return _decode(
                    candidate,
                    value,
                )
            except Exception as exc:
                last_error = exc

        if last_error is not None:
            raise last_error

        return value

    # ==========================================================
    # ANY
    # ==========================================================
    if tp is Any:
        return value

    # ==========================================================
    # ENUM
    # ==========================================================
    if (
        isinstance(tp, type)
        and issubclass(tp, Enum)
    ):
        try:
            return tp(value)

        except ValueError:
            text = (
                str(value)
                .strip()
                .upper()
            )

            for member in tp:
                if (
                    member.name.upper()
                    == text
                    or str(
                        member.value
                    ).upper()
                    == text
                ):
                    return member

            raise

    # ==========================================================
    # DATACLASS
    # ==========================================================
    if (
        isinstance(tp, type)
        and dataclasses.is_dataclass(tp)
    ):
        if not isinstance(
            value,
            dict,
        ):
            raise TypeError(
                f"{tp.__name__}_payload_must_be_object"
            )

        hints = get_type_hints(tp)

        fields = (
            dataclasses.fields(tp)
        )

        known = {
            field.name
            for field in fields
        }

        unknown = sorted(
            set(value) - known
        )

        if unknown:
            raise ValueError(
                f"{tp.__name__}_unknown_fields:"
                f"{','.join(unknown)}"
            )

        kwargs: dict[str, Any] = {}

        for field in fields:
            if field.name not in value:
                continue

            field_type = hints.get(
                field.name,
                Any,
            )

            kwargs[field.name] = (
                _decode(
                    field_type,
                    value[field.name],
                )
            )

        return tp(**kwargs)

    # ==========================================================
    # PRIMITIVES
    # ==========================================================
    if tp is str:
        return str(value)

    if tp is int:
        return int(value)

    if tp is float:
        return float(value)

    if tp is bool:
        if isinstance(
            value,
            bool,
        ):
            return value

        if isinstance(
            value,
            str,
        ):
            normalized = (
                value
                .strip()
                .lower()
            )

            if normalized in {
                "true",
                "1",
                "yes",
                "on",
            }:
                return True

            if normalized in {
                "false",
                "0",
                "no",
                "off",
                "",
            }:
                return False

            raise ValueError(
                f"invalid_boolean:{value}"
            )

        return bool(value)

    return value