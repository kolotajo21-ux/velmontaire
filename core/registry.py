from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterator
from typing import Iterable

from .detector import BaseDetector


class DetectorRegistry:
    """
    Реестр рыночных детекторов.

    Отвечает за:
    - регистрацию и удаление детекторов;
    - запрет дубликатов;
    - включение и отключение модулей;
    - проверку зависимостей;
    - построение безопасного порядка запуска.
    """

    def __init__(
        self,
        detectors: Iterable[BaseDetector] | None = None,
    ) -> None:
        self._detectors: OrderedDict[
            str,
            BaseDetector,
        ] = OrderedDict()

        if detectors is not None:
            for detector in detectors:
                self.register(detector)

    def register(
        self,
        detector: BaseDetector,
        *,
        replace: bool = False,
    ) -> None:
        if not isinstance(
            detector,
            BaseDetector,
        ):
            raise TypeError(
                "Registry accepts only BaseDetector instances"
            )

        detector.validate()
        detector_id = detector.detector_id

        if (
            detector_id in self._detectors
            and not replace
        ):
            raise ValueError(
                f"Detector already registered: {detector_id}"
            )

        self._detectors[detector_id] = detector

    def unregister(
        self,
        detector_id: str,
    ) -> BaseDetector:
        normalized_id = self._normalize_id(
            detector_id
        )

        if normalized_id not in self._detectors:
            raise KeyError(
                f"Detector not registered: {normalized_id}"
            )

        return self._detectors.pop(
            normalized_id
        )

    def get(
        self,
        detector_id: str,
    ) -> BaseDetector:
        normalized_id = self._normalize_id(
            detector_id
        )

        if normalized_id not in self._detectors:
            raise KeyError(
                f"Detector not registered: {normalized_id}"
            )

        return self._detectors[
            normalized_id
        ]

    def has(
        self,
        detector_id: str,
    ) -> bool:
        return (
            self._normalize_id(detector_id)
            in self._detectors
        )

    def enable(
        self,
        detector_id: str,
    ) -> None:
        self.get(detector_id).enabled = True

    def disable(
        self,
        detector_id: str,
    ) -> None:
        self.get(detector_id).enabled = False

    def clear(self) -> None:
        self._detectors.clear()

    def ids(
        self,
        *,
        enabled_only: bool = False,
    ) -> list[str]:
        return [
            detector_id
            for detector_id, detector
            in self._detectors.items()
            if (
                not enabled_only
                or detector.enabled
            )
        ]

    def detectors(
        self,
        *,
        enabled_only: bool = False,
    ) -> list[BaseDetector]:
        return [
            detector
            for detector
            in self._detectors.values()
            if (
                not enabled_only
                or detector.enabled
            )
        ]

    def resolve_order(
        self,
        *,
        enabled_only: bool = True,
    ) -> list[BaseDetector]:
        """
        Возвращает детекторы в порядке зависимостей.

        Если A зависит от B, B будет запущен раньше A.
        При циклической или отсутствующей зависимости
        выбрасывается понятная ошибка.
        """
        selected = {
            detector.detector_id: detector
            for detector in self.detectors(
                enabled_only=enabled_only
            )
        }

        visiting: set[str] = set()
        visited: set[str] = set()
        ordered: list[BaseDetector] = []

        def visit(
            detector_id: str,
            path: list[str],
        ) -> None:
            if detector_id in visited:
                return

            if detector_id in visiting:
                cycle = " -> ".join(
                    [
                        *path,
                        detector_id,
                    ]
                )
                raise ValueError(
                    f"Circular detector dependency: {cycle}"
                )

            detector = selected.get(
                detector_id
            )

            if detector is None:
                raise KeyError(
                    f"Missing detector dependency: {detector_id}"
                )

            visiting.add(detector_id)

            for dependency in detector.dependencies:
                dependency_id = self._normalize_id(
                    dependency
                )

                if dependency_id not in selected:
                    raise KeyError(
                        "Detector "
                        f"{detector_id} requires missing "
                        f"dependency {dependency_id}"
                    )

                visit(
                    dependency_id,
                    [
                        *path,
                        detector_id,
                    ],
                )

            visiting.remove(detector_id)
            visited.add(detector_id)
            ordered.append(detector)

        for detector_id in selected:
            visit(
                detector_id,
                [],
            )

        return ordered

    def validate(self) -> None:
        for detector in self._detectors.values():
            detector.validate()

        self.resolve_order(
            enabled_only=True
        )

    def describe(self) -> list[dict[str, object]]:
        return [
            {
                "id": detector.detector_id,
                "name": detector.name,
                "version": detector.version,
                "enabled": detector.enabled,
                "dependencies": list(
                    detector.dependencies
                ),
            }
            for detector
            in self._detectors.values()
        ]

    def __len__(self) -> int:
        return len(self._detectors)

    def __contains__(
        self,
        detector_id: object,
    ) -> bool:
        if not isinstance(
            detector_id,
            str,
        ):
            return False

        return self.has(detector_id)

    def __iter__(
        self,
    ) -> Iterator[BaseDetector]:
        return iter(
            self.resolve_order(
                enabled_only=True
            )
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