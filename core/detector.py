from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(slots=True)
class DetectorContext:
    """
    Входные данные для любого рыночного детектора.

    rates_by_timeframe:
        Свечи, сгруппированные по таймфреймам.
        Пример: {"D1": [...], "H4": [...], "M5": [...]}

    symbol:
        Торговый инструмент, например EURUSD.

    current_time:
        Время анализа в Unix timestamp.

    metadata:
        Дополнительные данные: настройки брокера, сессии,
        параметры стратегии и прочий внешний контекст.
    """

    symbol: str
    rates_by_timeframe: Mapping[str, Any]
    current_time: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def get_rates(
        self,
        timeframe: str,
    ) -> Any:
        return self.rates_by_timeframe.get(
            str(timeframe).upper(),
            [],
        )


@dataclass(slots=True)
class DetectorResult:
    """
    Стандартизированный результат работы детектора.
    """

    detector: str
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "detector": self.detector,
            "success": self.success,
            "data": dict(self.data),
            "events": [
                dict(event)
                for event in self.events
                if isinstance(event, dict)
            ],
            "diagnostics": dict(self.diagnostics),
            "error": self.error,
        }


class BaseDetector(ABC):
    """
    Базовый интерфейс всех рыночных детекторов.

    Каждый новый модуль должен:
    1. иметь уникальное имя;
    2. перечислять зависимости;
    3. реализовать analyze();
    4. возвращать DetectorResult;
    5. не открывать сделки самостоятельно.
    """

    name: str = "base"
    version: str = "1.0.0"
    dependencies: tuple[str, ...] = ()
    enabled: bool = True

    @property
    def detector_id(self) -> str:
        return str(self.name).strip().lower()

    def validate(self) -> None:
        if not self.detector_id:
            raise ValueError(
                "Detector name cannot be empty"
            )

        if self.detector_id == "base":
            raise ValueError(
                "Detector must define a unique name"
            )

        if not isinstance(
            self.dependencies,
            tuple,
        ):
            raise TypeError(
                "Detector dependencies must be a tuple"
            )

    def can_run(
        self,
        available_results: Mapping[
            str,
            DetectorResult,
        ],
    ) -> bool:
        return all(
            dependency in available_results
            and available_results[
                dependency
            ].success
            for dependency in self.dependencies
        )

    @abstractmethod
    def analyze(
        self,
        context: DetectorContext,
        snapshot: Mapping[str, Any],
    ) -> DetectorResult:
        """
        Выполняет анализ рынка.

        context:
            Свечи, символ, время и внешние параметры.

        snapshot:
            Уже собранные результаты предыдущих детекторов.
        """
        raise NotImplementedError

    def success(
        self,
        *,
        data: dict[str, Any] | None = None,
        events: list[dict[str, Any]] | None = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> DetectorResult:
        return DetectorResult(
            detector=self.detector_id,
            success=True,
            data=data or {},
            events=events or [],
            diagnostics=diagnostics or {},
        )

    def failure(
        self,
        *,
        error: str,
        diagnostics: dict[str, Any] | None = None,
    ) -> DetectorResult:
        return DetectorResult(
            detector=self.detector_id,
            success=False,
            diagnostics=diagnostics or {},
            error=str(error),
        )