from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Type

from strategy_compiler import StrategyCompiler
from core.strategy import ModuleRole

from .module_binding import (
    StrategyModuleBindingResult,
)


@dataclass(slots=True)
class GuardedCompilationResult:
    success: bool
    attempted: bool
    reason: str
    compilation_result: Any | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = None

        if self.compilation_result is not None:
            if hasattr(
                self.compilation_result,
                "to_dict",
            ):
                payload = (
                    self.compilation_result
                    .to_dict()
                )

        return {
            "success": bool(self.success),
            "attempted": bool(self.attempted),
            "reason": self.reason,
            "compilation_result": payload,
            "diagnostics": dict(
                self.diagnostics
            ),
        }


class BoundRegistryView:
    """
    Read-only registry view restricted to providers explicitly approved
    by Day 85 module binding.

    The legacy compiler can still call find_by_capability(), but it can
    never see an unapproved competing provider through this view.
    """

    def __init__(
        self,
        *,
        registry: Any,
        binding: StrategyModuleBindingResult,
    ) -> None:
        self.registry = registry

        definition = binding.definition

        self._allowed: dict[
            tuple[ModuleRole, str],
            set[str],
        ] = {}

        if definition is None:
            return

        for module in definition.modules:
            capabilities = {
                str(item).strip().lower()
                for item in (
                    module.metadata.get(
                        "capabilities",
                        [],
                    )
                    or []
                )
            }

            key = (
                module.role,
                str(
                    module.provider
                ).strip().lower(),
            )

            self._allowed[
                key
            ] = capabilities

    def find_by_capability(
        self,
        capability: str,
        *,
        role: ModuleRole | None = None,
    ) -> list[Any]:
        target = str(
            capability
        ).strip().lower()

        matches = self.registry.find_by_capability(
            target,
            role=role,
        )

        filtered = []

        for item in matches:
            key = (
                item.role,
                str(
                    item.provider
                ).strip().lower(),
            )

            allowed_capabilities = (
                self._allowed.get(
                    key
                )
            )

            if allowed_capabilities is None:
                continue

            if (
                target
                not in allowed_capabilities
            ):
                continue

            filtered.append(
                item
            )

        return filtered

    def registrations(
        self,
        role: ModuleRole | None = None,
    ) -> list[Any]:
        items = self.registry.registrations(
            role
        )

        return [
            item
            for item in items
            if (
                item.role,
                str(
                    item.provider
                ).strip().lower(),
            )
            in self._allowed
        ]

    def contains(
        self,
        *,
        role: ModuleRole,
        provider: str,
    ) -> bool:
        return (
            role,
            str(
                provider
            ).strip().lower(),
        ) in self._allowed

    def get_registration(
        self,
        *,
        role: ModuleRole,
        provider: str,
    ) -> Any:
        key = (
            role,
            str(
                provider
            ).strip().lower(),
        )

        if key not in self._allowed:
            raise KeyError(
                "provider_not_approved_by_module_binding:"
                f"{role.value}:{provider}"
            )

        return self.registry.get_registration(
            role=role,
            provider=provider,
        )


class GuardedStrategyCompiler:
    """
    Day 86 compiler safety boundary.

    Pipeline:
        READY Day 85 binding
        -> restricted BoundRegistryView
        -> existing StrategyCompiler
        -> compiled provider verification

    The frozen core/compiler.py is not modified.

    Safety:
    - compile is blocked unless Day 85 binding is READY;
    - compiler sees only providers explicitly approved by binding;
    - ambiguous registry providers are invisible unless selected;
    - compiled module bindings must match the approved provider set;
    - no provider guessing is performed here.
    """

    def __init__(
        self,
        *,
        registry: Any,
        compiler_class: Type[Any] = StrategyCompiler,
    ) -> None:
        self.registry = registry
        self.compiler_class = (
            compiler_class
        )

    def compile(
        self,
        *,
        schema: Any,
        binding: StrategyModuleBindingResult,
    ) -> GuardedCompilationResult:
        if not binding.ready:
            return GuardedCompilationResult(
                success=False,
                attempted=False,
                reason=(
                    "strategy_module_binding_not_ready"
                ),
                diagnostics={
                    "compiler_called": False,
                    "provider_guessing_performed": False,
                },
            )

        if binding.definition is None:
            return GuardedCompilationResult(
                success=False,
                attempted=False,
                reason=(
                    "strategy_module_binding_definition_missing"
                ),
                diagnostics={
                    "compiler_called": False,
                    "provider_guessing_performed": False,
                },
            )

        restricted_registry = BoundRegistryView(
            registry=self.registry,
            binding=binding,
        )

        compiler = self.compiler_class(
            restricted_registry
        )

        try:
            compilation = compiler.compile(
                schema
            )
        except Exception as exc:
            return GuardedCompilationResult(
                success=False,
                attempted=True,
                reason=(
                    "guarded_strategy_compiler_exception"
                ),
                diagnostics={
                    "compiler_called": True,
                    "provider_guessing_performed": False,
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                },
            )

        if not bool(
            getattr(
                compilation,
                "success",
                False,
            )
        ):
            return GuardedCompilationResult(
                success=False,
                attempted=True,
                reason=(
                    "strategy_compilation_failed"
                ),
                compilation_result=compilation,
                diagnostics={
                    "compiler_called": True,
                    "provider_guessing_performed": False,
                },
            )

        verification = (
            self._verify_compiled_bindings(
                compilation=compilation,
                binding=binding,
            )
        )

        if verification is not None:
            return GuardedCompilationResult(
                success=False,
                attempted=True,
                reason=verification,
                compilation_result=compilation,
                diagnostics={
                    "compiler_called": True,
                    "provider_guessing_performed": False,
                    "compiled_binding_verified": False,
                },
            )

        return GuardedCompilationResult(
            success=True,
            attempted=True,
            reason=(
                "strategy_compiled_with_guarded_bindings"
            ),
            compilation_result=compilation,
            diagnostics={
                "compiler_called": True,
                "provider_guessing_performed": False,
                "compiled_binding_verified": True,
            },
        )

    @staticmethod
    def _verify_compiled_bindings(
        *,
        compilation: Any,
        binding: StrategyModuleBindingResult,
    ) -> str | None:
        compiled = getattr(
            compilation,
            "compiled",
            None,
        )

        if compiled is None:
            return (
                "compiled_strategy_missing"
            )

        approved = {
            (
                module.role.value,
                str(
                    module.provider
                ).strip().lower(),
                capability,
            )
            for module in (
                binding.definition.modules
                if binding.definition
                is not None
                else []
            )
            for capability in {
                str(item)
                .strip()
                .lower()
                for item in (
                    module.metadata.get(
                        "capabilities",
                        [],
                    )
                    or []
                )
            }
        }

        for item in getattr(
            compiled,
            "module_bindings",
            [],
        ):
            key = (
                str(
                    item.role
                ),
                str(
                    item.provider
                ).strip().lower(),
                str(
                    item.capability
                ).strip().lower(),
            )

            if key not in approved:
                return (
                    "compiled_provider_not_approved:"
                    f"{key[0]}:"
                    f"{key[1]}:"
                    f"{key[2]}"
                )

        return None