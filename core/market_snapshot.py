from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Mapping

from .detector import DetectorResult


@dataclass(slots=True)
class MarketSnapshot:
    """
    Единый снимок состояния рынка.

    Хранит:
    - символ и время анализа;
    - результаты всех детекторов;
    - общие события;
    - диагностику;
    - ошибки отдельных модулей.

    StrategyEngine и StrategyBuilder должны читать рынок
    только через этот объект.
    """

    symbol: str
    current_time: int

    results: dict[
        str,
        DetectorResult,
    ] = field(default_factory=dict)

    events: list[
        dict[str, Any]
    ] = field(default_factory=list)

    diagnostics: dict[
        str,
        Any,
    ] = field(default_factory=dict)

    errors: dict[
        str,
        str,
    ] = field(default_factory=dict)

    metadata: dict[
        str,
        Any,
    ] = field(default_factory=dict)

    def add_result(
        self,
        result: DetectorResult,
    ) -> None:
        if not isinstance(
            result,
            DetectorResult,
        ):
            raise TypeError(
                "MarketSnapshot accepts only DetectorResult"
            )

        detector_id = str(
            result.detector
        ).strip().lower()

        if not detector_id:
            raise ValueError(
                "Detector result has empty detector id"
            )

        self.results[detector_id] = result

        if result.events:
            for event in result.events:
                if not isinstance(
                    event,
                    dict,
                ):
                    continue

                normalized_event = dict(
                    event
                )

                normalized_event.setdefault(
                    "source",
                    detector_id,
                )

                self.events.append(
                    normalized_event
                )

        if result.diagnostics:
            self.diagnostics[
                detector_id
            ] = dict(
                result.diagnostics
            )

        if (
            not result.success
            and result.error
        ):
            self.errors[
                detector_id
            ] = str(
                result.error
            )

    def has(
        self,
        detector_id: str,
    ) -> bool:
        return (
            self._normalize_id(
                detector_id
            )
            in self.results
        )

    def succeeded(
        self,
        detector_id: str,
    ) -> bool:
        result = self.get_result(
            detector_id
        )

        return bool(
            result is not None
            and result.success
        )

    def get_result(
        self,
        detector_id: str,
    ) -> DetectorResult | None:
        return self.results.get(
            self._normalize_id(
                detector_id
            )
        )

    def get(
        self,
        detector_id: str,
        default: Any = None,
    ) -> Any:
        result = self.get_result(
            detector_id
        )

        if result is None:
            return default

        return result.data

    def require(
        self,
        detector_id: str,
    ) -> dict[str, Any]:
        result = self.get_result(
            detector_id
        )

        if result is None:
            raise KeyError(
                f"Snapshot result missing: {detector_id}"
            )

        if not result.success:
            raise RuntimeError(
                "Snapshot result failed: "
                f"{detector_id}: {result.error}"
            )

        return result.data

    def get_value(
        self,
        detector_id: str,
        key: str,
        default: Any = None,
    ) -> Any:
        data = self.get(
            detector_id,
            {},
        )

        if not isinstance(
            data,
            Mapping,
        ):
            return default

        return data.get(
            key,
            default,
        )

    def all_successful(self) -> bool:
        return (
            bool(self.results)
            and not self.errors
            and all(
                result.success
                for result
                in self.results.values()
            )
        )

    def successful_ids(
        self,
    ) -> list[str]:
        return [
            detector_id
            for detector_id, result
            in self.results.items()
            if result.success
        ]

    def failed_ids(
        self,
    ) -> list[str]:
        return [
            detector_id
            for detector_id, result
            in self.results.items()
            if not result.success
        ]

    def event_filter(
        self,
        *,
        source: str | None = None,
        event_type: str | None = None,
        direction: str | None = None,
    ) -> list[dict[str, Any]]:
        normalized_source = (
            str(source).strip().lower()
            if source is not None
            else None
        )

        normalized_event_type = (
            str(event_type).strip().upper()
            if event_type is not None
            else None
        )

        normalized_direction = (
            str(direction).strip().upper()
            if direction is not None
            else None
        )

        filtered: list[
            dict[str, Any]
        ] = []

        for event in self.events:
            event_source = str(
                event.get(
                    "source",
                    "",
                )
            ).strip().lower()

            event_name = str(
                event.get(
                    "event_type",
                    event.get(
                        "type",
                        "",
                    ),
                )
            ).strip().upper()

            event_direction = str(
                event.get(
                    "direction",
                    "",
                )
            ).strip().upper()

            if (
                normalized_source is not None
                and event_source
                != normalized_source
            ):
                continue

            if (
                normalized_event_type is not None
                and event_name
                != normalized_event_type
            ):
                continue

            if (
                normalized_direction is not None
                and event_direction
                != normalized_direction
            ):
                continue

            filtered.append(
                dict(event)
            )

        return filtered

    def to_dict(
        self,
    ) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "current_time": int(
                self.current_time
            ),
            "results": {
                detector_id: result.to_dict()
                for detector_id, result
                in self.results.items()
            },
            "events": [
                dict(event)
                for event in self.events
            ],
            "diagnostics": dict(
                self.diagnostics
            ),
            "errors": dict(
                self.errors
            ),
            "metadata": dict(
                self.metadata
            ),
            "status": {
                "all_successful": (
                    self.all_successful()
                ),
                "successful_detectors": (
                    self.successful_ids()
                ),
                "failed_detectors": (
                    self.failed_ids()
                ),
            },
        }

    def __getitem__(
        self,
        detector_id: str,
    ) -> dict[str, Any]:
        return self.require(
            detector_id
        )

    def __contains__(
        self,
        detector_id: object,
    ) -> bool:
        if not isinstance(
            detector_id,
            str,
        ):
            return False

        return self.has(
            detector_id
        )

    def __iter__(
        self,
    ) -> Iterator[str]:
        return iter(
            self.results
        )

    def __len__(
        self,
    ) -> int:
        return len(
            self.results
        )

    @staticmethod
    def _normalize_id(
        detector_id: str,
    ) -> str:
        normalized = str(
            detector_id
        ).strip().lower()

        if not normalized:
            raise ValueError(
                "Detector id cannot be empty"
            )

        return normalized