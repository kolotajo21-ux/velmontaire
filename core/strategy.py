from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class StrategyStatus(str, Enum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    COMPILED = "COMPILED"
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class ModuleRole(str, Enum):
    MARKET = "MARKET"
    TREND = "TREND"
    LIQUIDITY = "LIQUIDITY"
    POI = "POI"
    ENTRY = "ENTRY"
    RISK = "RISK"
    MANAGEMENT = "MANAGEMENT"
    FILTER = "FILTER"
    EXECUTION = "EXECUTION"


@dataclass(slots=True)
class StrategyModuleDefinition:
    role: ModuleRole
    provider: str
    enabled: bool = True
    timeframe: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    priority: int = 100
    required: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role.value,
            "provider": self.provider,
            "enabled": self.enabled,
            "timeframe": self.timeframe,
            "parameters": dict(self.parameters),
            "priority": self.priority,
            "required": self.required,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class StrategyMetadata:
    name: str
    strategy_id: str
    version: str = "1.0.0"
    author: str | None = None
    description: str | None = None
    tags: list[str] = field(default_factory=list)
    created_from: str = "MANUAL"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "strategy_id": self.strategy_id,
            "version": self.version,
            "author": self.author,
            "description": self.description,
            "tags": list(self.tags),
            "created_from": self.created_from,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class StrategyDefinition:
    metadata: StrategyMetadata
    modules: list[StrategyModuleDefinition] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    timeframes: list[str] = field(default_factory=list)
    status: StrategyStatus = StrategyStatus.DRAFT
    settings: dict[str, Any] = field(default_factory=dict)
    metadata_extra: dict[str, Any] = field(default_factory=dict)

    def enabled_modules(self) -> list[StrategyModuleDefinition]:
        return [
            module
            for module in self.modules
            if module.enabled
        ]

    def modules_by_role(
        self,
        role: ModuleRole,
    ) -> list[StrategyModuleDefinition]:
        return sorted(
            [
                module
                for module in self.modules
                if module.enabled and module.role == role
            ],
            key=lambda module: module.priority,
        )

    def add_module(
        self,
        module: StrategyModuleDefinition,
    ) -> None:
        self.modules.append(module)

    def remove_provider(
        self,
        provider: str,
    ) -> None:
        target = provider.strip().lower()
        self.modules = [
            module
            for module in self.modules
            if module.provider.strip().lower() != target
        ]

    def has_provider(
        self,
        provider: str,
    ) -> bool:
        target = provider.strip().lower()
        return any(
            module.enabled
            and module.provider.strip().lower() == target
            for module in self.modules
        )

    def required_roles(self) -> set[ModuleRole]:
        return {
            module.role
            for module in self.modules
            if module.enabled and module.required
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "metadata": self.metadata.to_dict(),
            "modules": [
                module.to_dict()
                for module in self.modules
            ],
            "symbols": list(self.symbols),
            "timeframes": list(self.timeframes),
            "status": self.status.value,
            "settings": dict(self.settings),
            "metadata_extra": dict(self.metadata_extra),
        }