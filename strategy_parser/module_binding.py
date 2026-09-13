from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.strategy import (
    ModuleRole,
    StrategyDefinition,
    StrategyMetadata,
    StrategyModuleDefinition,
    StrategyStatus,
)

from .module_resolver import (
    CapabilityResolution,
    StrategyCapabilityResolutionReport,
)


class StrategyModuleBindingStatus(str, Enum):
    READY = "READY"
    BLOCKED = "BLOCKED"


@dataclass(slots=True)
class StrategyModuleBindingResult:
    status: StrategyModuleBindingStatus
    definition: StrategyDefinition | None = None
    blockers: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return (
            self.status == StrategyModuleBindingStatus.READY
            and self.definition is not None
            and not self.blockers
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "status": self.status.value,
            "definition": (
                self.definition.to_dict()
                if self.definition is not None
                else None
            ),
            "blockers": list(self.blockers),
            "diagnostics": dict(self.diagnostics),
        }


class AIStrategyModuleBinder:
    """
    Day 85 deterministic AI strategy -> module binding.

    Input:
        validated StrategySchema-like object
        +
        Day 84 StrategyCapabilityResolutionReport

    Output:
        StrategyDefinition with explicit StrategyModuleDefinition entries.

    Safety:
    - unresolved required capability mappings block binding;
    - no provider is guessed here;
    - only RESOLVED Day 84 mappings become modules;
    - duplicate provider/role mappings are merged deterministically;
    - conflicting explicit timeframes for one module block binding.
    """

    def bind(
        self,
        *,
        schema: Any,
        resolution_report: StrategyCapabilityResolutionReport,
    ) -> StrategyModuleBindingResult:
        if not resolution_report.ready:
            return StrategyModuleBindingResult(
                status=StrategyModuleBindingStatus.BLOCKED,
                blockers=[
                    self._resolution_blocker(item)
                    for item in resolution_report.blockers
                ],
                diagnostics={
                    "module_binding_performed": False,
                    "provider_guessing_performed": False,
                },
            )

        schema_error = self._validate_schema_identity(schema)
        if schema_error is not None:
            return StrategyModuleBindingResult(
                status=StrategyModuleBindingStatus.BLOCKED,
                blockers=[schema_error],
                diagnostics={
                    "module_binding_performed": False,
                    "provider_guessing_performed": False,
                },
            )

        grouped: dict[
            tuple[ModuleRole, str],
            list[CapabilityResolution],
        ] = {}

        for resolution in resolution_report.resolutions:
            if not resolution.resolved:
                # Optional unresolved capabilities are deliberately ignored.
                continue

            if resolution.role is None or not resolution.provider:
                return StrategyModuleBindingResult(
                    status=StrategyModuleBindingStatus.BLOCKED,
                    blockers=[
                        "resolved_capability_missing_role_or_provider"
                    ],
                    diagnostics={
                        "module_binding_performed": False,
                        "provider_guessing_performed": False,
                    },
                )

            key = (
                resolution.role,
                str(resolution.provider).strip().lower(),
            )
            grouped.setdefault(key, []).append(
                resolution
            )

        modules: list[StrategyModuleDefinition] = []

        for (_, _), resolutions in sorted(
            grouped.items(),
            key=lambda item: (
                item[0][0].value,
                item[0][1],
            ),
        ):
            first = resolutions[0]
            role = first.role
            provider = str(first.provider)

            timeframes = {
                str(
                    item.requirement.metadata.get(
                        "timeframe"
                    )
                ).strip().upper()
                for item in resolutions
                if item.requirement.metadata.get(
                    "timeframe"
                )
                not in (None, "")
            }

            if len(timeframes) > 1:
                return StrategyModuleBindingResult(
                    status=StrategyModuleBindingStatus.BLOCKED,
                    blockers=[
                        (
                            "module_timeframe_conflict:"
                            f"{role.value}:{provider}:"
                            + ",".join(sorted(timeframes))
                        )
                    ],
                    diagnostics={
                        "module_binding_performed": False,
                        "provider_guessing_performed": False,
                    },
                )

            capabilities = sorted({
                item.requirement.normalized_capability()
                for item in resolutions
            })

            source_paths = sorted({
                str(item.requirement.source_path)
                for item in resolutions
                if item.requirement.source_path
            })

            required = any(
                item.requirement.required
                for item in resolutions
            )

            modules.append(
                StrategyModuleDefinition(
                    role=role,
                    provider=provider,
                    enabled=True,
                    timeframe=(
                        next(iter(timeframes))
                        if timeframes
                        else None
                    ),
                    parameters={},
                    priority=100,
                    required=required,
                    metadata={
                        "bound_by": "AIStrategyModuleBinder",
                        "capabilities": capabilities,
                        "source_paths": source_paths,
                    },
                )
            )

        definition = StrategyDefinition(
            metadata=StrategyMetadata(
                name=str(schema.name),
                strategy_id=str(schema.strategy_id),
                version=str(
                    getattr(
                        schema,
                        "version",
                        "1.0",
                    )
                ),
                created_from="AI_STRATEGY_BUILDER",
                metadata={
                    "schema_version": str(
                        getattr(
                            schema,
                            "schema_version",
                            "",
                        )
                    ),
                },
            ),
            modules=modules,
            symbols=[
                str(item)
                for item in list(schema.symbols)
            ],
            timeframes=[
                str(item)
                for item in list(schema.timeframes)
            ],
            status=StrategyStatus.VALIDATED,
            settings={},
            metadata_extra={
                "capability_binding_ready": True,
                "capability_resolution_count": len(
                    resolution_report.resolutions
                ),
            },
        )

        return StrategyModuleBindingResult(
            status=StrategyModuleBindingStatus.READY,
            definition=definition,
            diagnostics={
                "module_binding_performed": True,
                "provider_guessing_performed": False,
                "bound_module_count": len(modules),
            },
        )

    def require_ready_definition(
        self,
        result: StrategyModuleBindingResult,
    ) -> StrategyDefinition:
        if not result.ready:
            raise ValueError(
                "strategy_module_binding_not_ready"
            )
        assert result.definition is not None
        return result.definition

    @staticmethod
    def _validate_schema_identity(
        schema: Any,
    ) -> str | None:
        if schema is None:
            return "strategy_schema_required"

        if not str(
            getattr(
                schema,
                "strategy_id",
                "",
            )
        ).strip():
            return "strategy_schema_id_missing"

        if not str(
            getattr(
                schema,
                "name",
                "",
            )
        ).strip():
            return "strategy_schema_name_missing"

        if not list(
            getattr(
                schema,
                "symbols",
                [],
            )
        ):
            return "strategy_schema_symbols_missing"

        if not list(
            getattr(
                schema,
                "timeframes",
                [],
            )
        ):
            return "strategy_schema_timeframes_missing"

        return None

    @staticmethod
    def _resolution_blocker(
        resolution: CapabilityResolution,
    ) -> str:
        requirement = resolution.requirement

        role = (
            requirement.role.value
            if requirement.role is not None
            else "ANY"
        )

        return (
            "capability_resolution:"
            f"{resolution.status.value}:"
            f"{role}:"
            f"{requirement.normalized_capability()}"
        )