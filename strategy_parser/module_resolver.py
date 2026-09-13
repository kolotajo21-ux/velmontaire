from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.strategy import ModuleRole


class CapabilityResolutionStatus(str, Enum):
    RESOLVED = "RESOLVED"
    MISSING = "MISSING"
    AMBIGUOUS = "AMBIGUOUS"
    PROVIDER_NOT_FOUND = "PROVIDER_NOT_FOUND"
    PROVIDER_CAPABILITY_MISMATCH = "PROVIDER_CAPABILITY_MISMATCH"


@dataclass(slots=True)
class StrategyCapabilityRequirement:
    capability: str
    role: ModuleRole | None = None
    provider: str | None = None
    required: bool = True
    source_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def normalized_capability(self) -> str:
        return str(self.capability).strip().lower()

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "role": (
                self.role.value
                if self.role is not None
                else None
            ),
            "provider": self.provider,
            "required": bool(self.required),
            "source_path": self.source_path,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class CapabilityResolution:
    requirement: StrategyCapabilityRequirement
    status: CapabilityResolutionStatus
    provider: str | None = None
    role: ModuleRole | None = None
    candidates: list[str] = field(default_factory=list)
    reason: str = ""

    @property
    def resolved(self) -> bool:
        return self.status == CapabilityResolutionStatus.RESOLVED

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement": self.requirement.to_dict(),
            "status": self.status.value,
            "provider": self.provider,
            "role": (
                self.role.value
                if self.role is not None
                else None
            ),
            "candidates": list(self.candidates),
            "reason": self.reason,
            "resolved": self.resolved,
        }


@dataclass(slots=True)
class StrategyCapabilityResolutionReport:
    resolutions: list[CapabilityResolution] = field(
        default_factory=list
    )

    @property
    def blockers(self) -> list[CapabilityResolution]:
        return [
            item
            for item in self.resolutions
            if (
                item.requirement.required
                and not item.resolved
            )
        ]

    @property
    def ready(self) -> bool:
        return not self.blockers

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "resolutions": [
                item.to_dict()
                for item in self.resolutions
            ],
            "blockers": [
                item.to_dict()
                for item in self.blockers
            ],
        }


class StrategyCapabilityResolver:
    """
    Day 84 capability -> real module resolver.

    The resolver never invents a provider.

    Resolution rules:
    - explicit provider must exist and expose the requested capability;
    - one capability match -> RESOLVED;
    - zero matches -> MISSING;
    - multiple matches -> AMBIGUOUS;
    - optional unresolved requirements do not block overall readiness.

    Registry contract used:
      registrations(role=None)
      find_by_capability(capability, role=None)
      get_registration(role=..., provider=...)
    """

    def __init__(
        self,
        *,
        registry: Any,
    ) -> None:
        self.registry = registry

    def resolve(
        self,
        requirements: list[
            StrategyCapabilityRequirement
        ],
    ) -> StrategyCapabilityResolutionReport:
        resolutions = [
            self._resolve_one(requirement)
            for requirement in requirements
        ]

        return StrategyCapabilityResolutionReport(
            resolutions=resolutions
        )

    def require_ready(
        self,
        report: StrategyCapabilityResolutionReport,
    ) -> StrategyCapabilityResolutionReport:
        if not report.ready:
            raise ValueError(
                "strategy_capability_resolution_not_ready"
            )
        return report

    def _resolve_one(
        self,
        requirement: StrategyCapabilityRequirement,
    ) -> CapabilityResolution:
        capability = (
            requirement.normalized_capability()
        )

        if not capability:
            return CapabilityResolution(
                requirement=requirement,
                status=CapabilityResolutionStatus.MISSING,
                reason="capability_required",
            )

        if requirement.provider:
            return self._resolve_explicit_provider(
                requirement,
                capability,
            )

        matches = self.registry.find_by_capability(
            capability,
            role=requirement.role,
        )

        if not matches:
            return CapabilityResolution(
                requirement=requirement,
                status=CapabilityResolutionStatus.MISSING,
                reason="capability_not_registered",
            )

        if len(matches) > 1:
            return CapabilityResolution(
                requirement=requirement,
                status=CapabilityResolutionStatus.AMBIGUOUS,
                candidates=[
                    self._candidate_name(item)
                    for item in matches
                ],
                reason="multiple_capability_providers",
            )

        selected = matches[0]

        return CapabilityResolution(
            requirement=requirement,
            status=CapabilityResolutionStatus.RESOLVED,
            provider=str(selected.provider),
            role=selected.role,
            candidates=[
                self._candidate_name(selected)
            ],
            reason="single_capability_provider",
        )

    def _resolve_explicit_provider(
        self,
        requirement: StrategyCapabilityRequirement,
        capability: str,
    ) -> CapabilityResolution:
        provider = str(
            requirement.provider
        ).strip()

        candidates = self.registry.registrations(
            requirement.role
        )

        matching_provider = [
            item
            for item in candidates
            if (
                str(item.provider)
                .strip()
                .lower()
                == provider.lower()
            )
        ]

        if not matching_provider:
            return CapabilityResolution(
                requirement=requirement,
                status=(
                    CapabilityResolutionStatus
                    .PROVIDER_NOT_FOUND
                ),
                provider=provider,
                reason="explicit_provider_not_registered",
            )

        if len(matching_provider) != 1:
            return CapabilityResolution(
                requirement=requirement,
                status=CapabilityResolutionStatus.AMBIGUOUS,
                provider=provider,
                candidates=[
                    self._candidate_name(item)
                    for item in matching_provider
                ],
                reason="explicit_provider_not_unique",
            )

        selected = matching_provider[0]

        normalized_capabilities = {
            str(item).strip().lower()
            for item in selected.capabilities
        }

        if capability not in normalized_capabilities:
            return CapabilityResolution(
                requirement=requirement,
                status=(
                    CapabilityResolutionStatus
                    .PROVIDER_CAPABILITY_MISMATCH
                ),
                provider=str(selected.provider),
                role=selected.role,
                candidates=[
                    self._candidate_name(selected)
                ],
                reason=(
                    "explicit_provider_missing_capability"
                ),
            )

        return CapabilityResolution(
            requirement=requirement,
            status=CapabilityResolutionStatus.RESOLVED,
            provider=str(selected.provider),
            role=selected.role,
            candidates=[
                self._candidate_name(selected)
            ],
            reason="explicit_provider_verified",
        )

    @staticmethod
    def _candidate_name(
        registration: Any,
    ) -> str:
        return (
            f"{registration.role.value}:"
            f"{registration.provider}"
        )