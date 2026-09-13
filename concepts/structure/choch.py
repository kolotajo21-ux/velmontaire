from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .models import (
    StructureDirection,
    StructureEvent,
    StructureEventType,
)


@dataclass(slots=True)
class ChochAnalyzerConfig:
    update_bias_after_choch: bool = True
    range_uses_first_break_as_bias: bool = True


class ChochAnalyzer:
    """
    Классифицирует подтверждённые пробои структуры.

    Правила:
    - пробой в направлении текущего bias остаётся BOS;
    - пробой против текущего bias становится CHoCH;
    - после CHoCH bias переключается на новое направление;
    - если bias RANGE, первый пробой устанавливает направление.
    """

    def __init__(
        self,
        config: ChochAnalyzerConfig | None = None,
    ) -> None:
        self.config = (
            config
            if config is not None
            else ChochAnalyzerConfig()
        )

    def classify(
        self,
        break_events: Iterable[StructureEvent],
        initial_direction: StructureDirection,
    ) -> tuple[
        list[StructureEvent],
        StructureDirection,
    ]:
        events = sorted(
            list(break_events),
            key=lambda event: (
                event.index,
                event.time,
            ),
        )

        current_bias = initial_direction
        classified: list[StructureEvent] = []

        for event in events:
            if not event.confirmed:
                continue

            event_direction = event.direction

            if current_bias == StructureDirection.RANGE:
                classified.append(
                    self._copy_event(
                        event=event,
                        event_type=StructureEventType.BOS,
                        previous_bias=current_bias,
                        new_bias=event_direction,
                    )
                )

                if (
                    self.config
                    .range_uses_first_break_as_bias
                ):
                    current_bias = event_direction

                continue

            if event_direction == current_bias:
                classified.append(
                    self._copy_event(
                        event=event,
                        event_type=StructureEventType.BOS,
                        previous_bias=current_bias,
                        new_bias=current_bias,
                    )
                )
                continue

            new_event = self._copy_event(
                event=event,
                event_type=StructureEventType.CHOCH,
                previous_bias=current_bias,
                new_bias=event_direction,
            )

            classified.append(new_event)

            if self.config.update_bias_after_choch:
                current_bias = event_direction

        return classified, current_bias

    def choch_only(
        self,
        break_events: Iterable[StructureEvent],
        initial_direction: StructureDirection,
    ) -> list[StructureEvent]:
        classified, _ = self.classify(
            break_events=break_events,
            initial_direction=initial_direction,
        )

        return [
            event
            for event in classified
            if event.event_type
            == StructureEventType.CHOCH
        ]

    @staticmethod
    def _copy_event(
        *,
        event: StructureEvent,
        event_type: StructureEventType,
        previous_bias: StructureDirection,
        new_bias: StructureDirection,
    ) -> StructureEvent:
        metadata = dict(
            event.metadata
        )

        metadata.update(
            {
                "raw_event_type": (
                    event.event_type.value
                ),
                "previous_bias": (
                    previous_bias.value
                ),
                "new_bias": (
                    new_bias.value
                ),
                "classification": (
                    event_type.value
                ),
            }
        )

        return StructureEvent(
            event_type=event_type,
            direction=event.direction,
            index=int(event.index),
            time=int(event.time),
            broken_level=float(
                event.broken_level
            ),
            close_price=float(
                event.close_price
            ),
            source_swing_index=(
                int(event.source_swing_index)
                if event.source_swing_index
                is not None
                else None
            ),
            source_swing_time=(
                int(event.source_swing_time)
                if event.source_swing_time
                is not None
                else None
            ),
            body_ratio=float(
                event.body_ratio
            ),
            break_distance=float(
                event.break_distance
            ),
            break_ratio=float(
                event.break_ratio
            ),
            confirmed=bool(
                event.confirmed
            ),
            quality_score=float(
                event.quality_score
            ),
            metadata=metadata,
        )