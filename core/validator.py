from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .strategy import ModuleRole, StrategyDefinition
from .strategy_registry import StrategyModuleRegistry


@dataclass(slots=True)
class ValidationIssue:
    level: str
    code: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "code": self.code,
            "message": self.message,
        }


@dataclass(slots=True)
class ValidationReport:
    valid: bool = True
    issues: list[ValidationIssue] = field(default_factory=list)

    def add(self, level: str, code: str, message: str) -> None:
        self.issues.append(ValidationIssue(level, code, message))
        if level.upper() == "ERROR":
            self.valid = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "issues": [i.to_dict() for i in self.issues],
        }


class StrategyValidator:

    REQUIRED_ROLES = (
        ModuleRole.TREND,
        ModuleRole.ENTRY,
        ModuleRole.RISK,
    )

    def __init__(self, registry: StrategyModuleRegistry) -> None:
        self.registry = registry

    def validate(self, strategy: StrategyDefinition) -> ValidationReport:
        report = ValidationReport()

        if not strategy.modules:
            report.add("ERROR", "NO_MODULES", "Strategy has no modules.")
            return report

        for role in self.REQUIRED_ROLES:
            if not strategy.modules_by_role(role):
                report.add(
                    "ERROR",
                    f"MISSING_{role.value}",
                    f"Missing required role: {role.value}",
                )

        seen: set[tuple[ModuleRole, str]] = set()

        for module in strategy.modules:
            key = (module.role, module.provider.lower())

            if key in seen:
                report.add(
                    "WARNING",
                    "DUPLICATE_PROVIDER",
                    f"Duplicate provider {module.provider} for {module.role.value}",
                )
            else:
                seen.add(key)

            ok, reason = self.registry.validate_definition(module)
            if not ok:
                report.add(
                    "ERROR",
                    "UNKNOWN_PROVIDER",
                    reason or "Unknown provider",
                )

        return report