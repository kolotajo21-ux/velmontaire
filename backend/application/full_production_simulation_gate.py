from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class GateResult:
    name: str
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FullProductionSimulationGate:
    """
    Day 129 pre-release system gate.

    Runs product/regression checks through injected test runners. It never
    authorizes LIVE trading and never calls MT5/broker execution APIs directly.
    """

    REQUIRED_GATES = (
        "DAY100_CORE_ACCEPTANCE",
        "DAY103_PERSISTENCE",
        "DAY104_AUTH",
        "DAY105_MULTI_USER",
        "DAY107_AI_CLARIFICATION",
        "DAY108_HUMAN_REVIEW",
        "DAY111_BACKTEST_API",
        "DAY115_BACKTEST_DETERMINISM",
        "DAY117_MT5_CREDENTIAL_SECURITY",
        "DAY119_PAPER_LIVE_SEPARATION",
        "DAY120_RECOVERY",
        "DAY123_ENTITLEMENTS",
        "DAY124_ABUSE_PROTECTION",
        "DAY127_OBSERVABILITY",
        "DAY128_CLOSED_BETA",
    )

    def __init__(self, *, runners: dict[str, Callable[[], Any]]) -> None:
        self.runners = dict(runners)

    def run(self) -> dict[str, Any]:
        missing = [name for name in self.REQUIRED_GATES if name not in self.runners]
        if missing:
            return {
                "status": "BLOCKED",
                "release_candidate": False,
                "real_broker_order_submitted": False,
                "missing_gates": missing,
                "results": [],
            }

        results: list[GateResult] = []
        for name in self.REQUIRED_GATES:
            try:
                raw = self.runners[name]()
                passed = raw is True or (
                    isinstance(raw, dict) and raw.get("passed") is True
                )
                detail = "PASS" if passed else "FAILED"
            except Exception as exc:
                passed = False
                detail = f"EXCEPTION:{type(exc).__name__}"

            results.append(GateResult(name, passed, detail))

            # Fail closed: no later gate runs after a failed critical gate.
            if not passed:
                break

        all_passed = (
            len(results) == len(self.REQUIRED_GATES)
            and all(item.passed for item in results)
        )

        return {
            "status": "PASS" if all_passed else "BLOCKED",
            "release_candidate": all_passed,
            "real_broker_order_submitted": False,
            "missing_gates": [],
            "results": [item.to_dict() for item in results],
        }
