from __future__ import annotations

import time

from .detector import DetectorContext, DetectorResult
from .market_snapshot import MarketSnapshot
from .registry import DetectorRegistry


class ConceptEngine:
    """
    Центральный движок анализа рынка.

    Запускает все зарегистрированные детекторы,
    собирает результаты в MarketSnapshot
    и не останавливает весь анализ,
    если один модуль завершился с ошибкой.
    """

    def __init__(
        self,
        registry: DetectorRegistry,
    ) -> None:
        if not isinstance(
            registry,
            DetectorRegistry,
        ):
            raise TypeError(
                "registry must be DetectorRegistry"
            )

        self.registry = registry

    def analyze(
        self,
        context: DetectorContext,
    ) -> MarketSnapshot:
        if not isinstance(
            context,
            DetectorContext,
        ):
            raise TypeError(
                "context must be DetectorContext"
            )

        self.registry.validate()

        snapshot = MarketSnapshot(
            symbol=context.symbol,
            current_time=context.current_time,
            metadata={
                "context_metadata": dict(
                    context.metadata
                ),
            },
        )

        execution_times: dict[
            str,
            float,
        ] = {}

        total_start = time.perf_counter()

        for detector in self.registry:
            detector_id = detector.detector_id
            detector_start = time.perf_counter()

            try:
                if not detector.can_run(
                    snapshot.results
                ):
                    result = detector.failure(
                        error=(
                            "detector_dependencies_"
                            "not_satisfied"
                        ),
                        diagnostics={
                            "dependencies": list(
                                detector.dependencies
                            ),
                        },
                    )

                    snapshot.add_result(
                        result
                    )

                    continue

                result = detector.analyze(
                    context=context,
                    snapshot=snapshot.to_dict(),
                )

                if not isinstance(
                    result,
                    DetectorResult,
                ):
                    raise TypeError(
                        f"{detector_id} returned "
                        "an invalid result"
                    )

                if (
                    result.detector.strip().lower()
                    != detector_id
                ):
                    raise ValueError(
                        f"{detector_id} returned "
                        f"result for {result.detector}"
                    )

                snapshot.add_result(
                    result
                )

            except Exception as error:
                snapshot.add_result(
                    detector.failure(
                        error=(
                            f"{type(error).__name__}: "
                            f"{error}"
                        ),
                        diagnostics={
                            "exception_type": (
                                type(error).__name__
                            ),
                        },
                    )
                )

            finally:
                execution_times[
                    detector_id
                ] = round(
                    (
                        time.perf_counter()
                        - detector_start
                    )
                    * 1000.0,
                    3,
                )

        total_time = round(
            (
                time.perf_counter()
                - total_start
            )
            * 1000.0,
            3,
        )

        snapshot.metadata.update(
            {
                "detectors": (
                    self.registry.ids(
                        enabled_only=True
                    )
                ),
                "execution_time_ms": (
                    execution_times
                ),
                "total_execution_time_ms": (
                    total_time
                ),
                "detector_count": len(
                    execution_times
                ),
            }
        )

        return snapshot