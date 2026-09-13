from __future__ import annotations

from dataclasses import dataclass, field
from typing import Type

from .interfaces import StrategyModule
from .strategy import (
    ModuleRole,
    StrategyModuleDefinition,
)


@dataclass(slots=True)
class RegisteredStrategyModule:
    provider: str
    role: ModuleRole
    module_class: Type[StrategyModule]

    version: str = "1.0.0"

    capabilities: set[str] = field(
        default_factory=set
    )

    metadata: dict[str, object] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "role": self.role.value,
            "version": self.version,
            "capabilities": sorted(
                self.capabilities
            ),
            "metadata": dict(
                self.metadata
            ),
        }


class StrategyModuleRegistry:
    """
    Реестр модулей Universal Strategy Engine.

    Хранит классы StrategyModule по паре:
        role + provider

    Не связан с существующим DetectorRegistry.
    """

    def __init__(self) -> None:
        self._modules: dict[
            tuple[
                ModuleRole,
                str,
            ],
            RegisteredStrategyModule,
        ] = {}

    def register(
        self,
        module_class: Type[StrategyModule],
        *,
        replace: bool = False,
    ) -> None:
        if not issubclass(
            module_class,
            StrategyModule,
        ):
            raise TypeError(
                "module_class must inherit "
                "from StrategyModule"
            )

        provider = str(
            module_class.provider
        ).strip()

        if not provider:
            raise ValueError(
                "Strategy module provider "
                "cannot be empty"
            )

        role = module_class.role

        key = self._key(
            role=role,
            provider=provider,
        )

        if (
            key in self._modules
            and not replace
        ):
            raise ValueError(
                "Strategy module already "
                f"registered: {role.value}/"
                f"{provider}"
            )

        self._modules[
            key
        ] = RegisteredStrategyModule(
            provider=provider,
            role=role,
            module_class=module_class,
            version=str(
                module_class.version
            ),
            capabilities=set(
                module_class.capabilities
            ),
            metadata={},
        )

    def unregister(
        self,
        *,
        role: ModuleRole,
        provider: str,
    ) -> None:
        key = self._key(
            role=role,
            provider=provider,
        )

        self._modules.pop(
            key,
            None,
        )

    def contains(
        self,
        *,
        role: ModuleRole,
        provider: str,
    ) -> bool:
        return (
            self._key(
                role=role,
                provider=provider,
            )
            in self._modules
        )

    def get_registration(
        self,
        *,
        role: ModuleRole,
        provider: str,
    ) -> RegisteredStrategyModule:
        key = self._key(
            role=role,
            provider=provider,
        )

        registered = self._modules.get(
            key
        )

        if registered is None:
            raise KeyError(
                "Unknown strategy module: "
                f"{role.value}/{provider}"
            )

        return registered

    def create(
        self,
        definition: StrategyModuleDefinition,
    ) -> StrategyModule:
        registered = self.get_registration(
            role=definition.role,
            provider=definition.provider,
        )

        return registered.module_class(
            definition=definition
        )

    def providers(
        self,
        role: ModuleRole | None = None,
    ) -> list[str]:
        items = self._modules.values()

        if role is not None:
            items = [
                item
                for item in items
                if item.role == role
            ]

        return sorted(
            item.provider
            for item in items
        )

    def registrations(
        self,
        role: ModuleRole | None = None,
    ) -> list[RegisteredStrategyModule]:
        items = list(
            self._modules.values()
        )

        if role is not None:
            items = [
                item
                for item in items
                if item.role == role
            ]

        return sorted(
            items,
            key=lambda item: (
                item.role.value,
                item.provider.lower(),
            ),
        )

    def find_by_capability(
        self,
        capability: str,
        *,
        role: ModuleRole | None = None,
    ) -> list[
        RegisteredStrategyModule
    ]:
        target = str(
            capability
        ).strip().lower()

        matches = []

        for item in self._modules.values():
            if (
                role is not None
                and item.role != role
            ):
                continue

            normalized = {
                str(name)
                .strip()
                .lower()
                for name
                in item.capabilities
            }

            if target in normalized:
                matches.append(
                    item
                )

        return sorted(
            matches,
            key=lambda item: (
                item.role.value,
                item.provider.lower(),
            ),
        )

    def validate_definition(
        self,
        definition: StrategyModuleDefinition,
    ) -> tuple[
        bool,
        str | None,
    ]:
        if not definition.enabled:
            return (
                True,
                None,
            )

        if not self.contains(
            role=definition.role,
            provider=definition.provider,
        ):
            return (
                False,
                (
                    "provider_not_registered:"
                    f"{definition.role.value}:"
                    f"{definition.provider}"
                ),
            )

        return (
            True,
            None,
        )

    def to_dict(self) -> dict[
        str,
        object,
    ]:
        registrations = (
            self.registrations()
        )

        return {
            "count": len(
                registrations
            ),
            "modules": [
                item.to_dict()
                for item
                in registrations
            ],
        }

    @staticmethod
    def _key(
        *,
        role: ModuleRole,
        provider: str,
    ) -> tuple[
        ModuleRole,
        str,
    ]:
        return (
            role,
            str(
                provider
            ).strip().lower(),
        )