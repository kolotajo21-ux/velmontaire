from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class OrderBlockScore:
    impulse: float = 0.0
    body: float = 0.0
    displacement: float = 0.0
    liquidity: float = 0.0
    freshness: float = 0.0
    mitigation: float = 0.0
    reaction: float = 0.0

    total: float = 0.0

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "impulse": self.impulse,
            "body": self.body,
            "displacement": self.displacement,
            "liquidity": self.liquidity,
            "freshness": self.freshness,
            "mitigation": self.mitigation,
            "reaction": self.reaction,
            "total": self.total,
            "metadata": dict(self.metadata),
        }


class OrderBlockScorer:

    WEIGHTS = {
        "impulse": 0.20,
        "body": 0.15,
        "displacement": 0.15,
        "liquidity": 0.20,
        "freshness": 0.10,
        "mitigation": 0.10,
        "reaction": 0.10,
    }

    def calculate(
        self,
        score: OrderBlockScore,
    ) -> OrderBlockScore:

        total = (
            score.impulse * self.WEIGHTS["impulse"]
            + score.body * self.WEIGHTS["body"]
            + score.displacement * self.WEIGHTS["displacement"]
            + score.liquidity * self.WEIGHTS["liquidity"]
            + score.freshness * self.WEIGHTS["freshness"]
            + score.mitigation * self.WEIGHTS["mitigation"]
            + score.reaction * self.WEIGHTS["reaction"]
        )

        score.total = round(
            total,
            2,
        )

        return score