from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any


class RuntimeIdempotencyError(ValueError):
    """Fail-closed duplicate market-input protection error."""


@dataclass(frozen=True, slots=True)
class IdempotentProcessResult:
    duplicate: bool
    input_id: str
    transaction_result: Any


class RuntimeIdempotencyGuard:
    """
    Prevents the same semantic market input from being committed twice.

    Identity includes capability/version/symbol/bar and canonical context.
    Same bar + same context => return original committed result.
    Same bar + different context => fail closed as conflicting duplicate.
    """

    def __init__(self, transaction_boundary: Any) -> None:
        if not hasattr(transaction_boundary, "process_bar"):
            raise RuntimeIdempotencyError("transaction_boundary_required")
        self.boundary = transaction_boundary
        self._committed: dict[str, Any] = {}
        self._bar_identity: dict[str, str] = {}

    @staticmethod
    def _canonical_context(context: dict[str, Any]) -> str:
        try:
            return json.dumps(
                context,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                default=str,
            )
        except Exception as exc:
            raise RuntimeIdempotencyError(
                f"context_not_canonicalizable:{exc}"
            ) from exc

    @classmethod
    def make_input_id(
        cls,
        *,
        capability_id: str,
        version: int | None,
        symbol: str,
        bar_index: int,
        context: dict[str, Any],
    ) -> str:
        payload = {
            "capability_id": capability_id,
            "version": version,
            "symbol": symbol.upper(),
            "bar_index": int(bar_index),
            "context": cls._canonical_context(context),
        }
        raw = json.dumps(
            payload, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return "INP_" + sha256(raw).hexdigest()[:20].upper()

    @staticmethod
    def _bar_key(
        capability_id: str,
        version: int | None,
        symbol: str,
        bar_index: int,
    ) -> str:
        return (
            f"{capability_id}@v{version if version is not None else 'LATEST'}:"
            f"{symbol.upper()}:{int(bar_index)}"
        )

    def process_bar(
        self,
        capability_id: str,
        *,
        symbol: str,
        bar_index: int,
        context: dict[str, Any],
        version: int | None = None,
    ) -> IdempotentProcessResult:
        input_id = self.make_input_id(
            capability_id=capability_id,
            version=version,
            symbol=symbol,
            bar_index=bar_index,
            context=context,
        )
        bar_key = self._bar_key(
            capability_id, version, symbol, bar_index
        )

        previous_input = self._bar_identity.get(bar_key)
        if previous_input is not None:
            if previous_input != input_id:
                raise RuntimeIdempotencyError(
                    f"conflicting_duplicate_bar:{bar_key}"
                )
            return IdempotentProcessResult(
                duplicate=True,
                input_id=input_id,
                transaction_result=self._committed[input_id],
            )

        kwargs = {
            "symbol": symbol,
            "bar_index": bar_index,
            "context": context,
        }
        if version is not None:
            kwargs["version"] = version

        result = self.boundary.process_bar(capability_id, **kwargs)

        # Register only after durable transaction COMMIT.
        self._committed[input_id] = result
        self._bar_identity[bar_key] = input_id
        return IdempotentProcessResult(
            duplicate=False,
            input_id=input_id,
            transaction_result=result,
        )

    def committed_count(self) -> int:
        return len(self._committed)
