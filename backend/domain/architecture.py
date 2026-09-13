from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

class ArchitectureLayer(str, Enum):
    WEB="WEB"
    BACKEND_API="BACKEND_API"
    APPLICATION="APPLICATION"
    DOMAIN="DOMAIN"
    BOT_CORE="BOT_CORE"
    BROKER_BOUNDARY="BROKER_BOUNDARY"

@dataclass(frozen=True, slots=True)
class ServiceBoundary:
    source: ArchitectureLayer
    target: ArchitectureLayer
    purpose: str

SAAS_ARCHITECTURE = (
    ServiceBoundary(ArchitectureLayer.WEB, ArchitectureLayer.BACKEND_API, "HTTP/API only"),
    ServiceBoundary(ArchitectureLayer.BACKEND_API, ArchitectureLayer.APPLICATION, "validated commands/queries"),
    ServiceBoundary(ArchitectureLayer.APPLICATION, ArchitectureLayer.DOMAIN, "business rules/entities"),
    ServiceBoundary(ArchitectureLayer.APPLICATION, ArchitectureLayer.BOT_CORE, "controlled Bot Core gateway"),
    ServiceBoundary(ArchitectureLayer.BOT_CORE, ArchitectureLayer.BROKER_BOUNDARY, "existing production safety/execution pipeline"),
)

FORBIDDEN_BACKEND_IMPORT_PREFIXES = (
    "MetaTrader5",
    "mt5_connector",
    "execution_adapters.mt5_execution",
)

def allowed_targets(source: ArchitectureLayer):
    return tuple(x.target for x in SAAS_ARCHITECTURE if x.source == source)

def is_allowed_boundary(source: ArchitectureLayer, target: ArchitectureLayer) -> bool:
    return any(x.source == source and x.target == target for x in SAAS_ARCHITECTURE)

def validate_no_direct_broker_dependency(imports: Iterable[str]) -> list[str]:
    violations = []
    for name in imports:
        normalized = str(name).strip()
        for prefix in FORBIDDEN_BACKEND_IMPORT_PREFIXES:
            if normalized == prefix or normalized.startswith(prefix + "."):
                violations.append(normalized)
                break
    return sorted(set(violations))
