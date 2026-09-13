from __future__ import annotations

import importlib
import inspect
import pkgutil
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any

from .interfaces import StrategyModule
from .strategy_registry import StrategyModuleRegistry


@dataclass(slots=True)
class ModuleLoadError:
    module_name: str
    error: str

    def to_dict(self) -> dict[str, str]:
        return {
            "module_name": self.module_name,
            "error": self.error,
        }


@dataclass(slots=True)
class ModuleLoadReport:
    package: str

    discovered_modules: int = 0
    imported_modules: int = 0
    discovered_classes: int = 0
    registered_classes: int = 0
    skipped_classes: int = 0

    registered_providers: list[str] = field(
        default_factory=list
    )

    errors: list[ModuleLoadError] = field(
        default_factory=list
    )

    @property
    def success(self) -> bool:
        return not bool(
            self.errors
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "package": self.package,
            "success": self.success,
            "discovered_modules": (
                self.discovered_modules
            ),
            "imported_modules": (
                self.imported_modules
            ),
            "discovered_classes": (
                self.discovered_classes
            ),
            "registered_classes": (
                self.registered_classes
            ),
            "skipped_classes": (
                self.skipped_classes
            ),
            "registered_providers": list(
                self.registered_providers
            ),
            "errors": [
                error.to_dict()
                for error in self.errors
            ],
        }


class StrategyModuleLoader:
    """
    Автоматически обнаруживает и регистрирует
    StrategyModule-классы внутри Python package.

    По умолчанию сканирует:
        modules.*

    Пример:
        modules.trend.structure_trend
        modules.liquidity.sweep
        modules.poi.fvg
    """

    def __init__(
        self,
        registry: StrategyModuleRegistry,
        *,
        package_name: str = "modules",
        replace_existing: bool = False,
        fail_fast: bool = False,
    ) -> None:
        self.registry = registry
        self.package_name = str(
            package_name
        ).strip()
        self.replace_existing = bool(
            replace_existing
        )
        self.fail_fast = bool(
            fail_fast
        )

        if not self.package_name:
            raise ValueError(
                "package_name cannot be empty"
            )

    def load(self) -> ModuleLoadReport:
        report = ModuleLoadReport(
            package=self.package_name
        )

        root_package = self._import_root(
            report
        )

        if root_package is None:
            return report

        package_path = getattr(
            root_package,
            "__path__",
            None,
        )

        if package_path is None:
            self._add_error(
                report,
                self.package_name,
                (
                    "Root module is not a package "
                    "and has no __path__"
                ),
            )
            return report

        prefix = (
            root_package.__name__
            + "."
        )

        discovered = list(
            pkgutil.walk_packages(
                package_path,
                prefix=prefix,
            )
        )

        report.discovered_modules = len(
            discovered
        )

        for module_info in discovered:
            module_name = (
                module_info.name
            )

            if self._should_skip_module(
                module_name
            ):
                continue

            imported = self._import_module(
                module_name=module_name,
                report=report,
            )

            if imported is None:
                if self.fail_fast:
                    break
                continue

            report.imported_modules += 1

            self._register_from_module(
                module=imported,
                report=report,
            )

            if (
                self.fail_fast
                and report.errors
            ):
                break

        return report

    def _import_root(
        self,
        report: ModuleLoadReport,
    ) -> ModuleType | None:
        try:
            return importlib.import_module(
                self.package_name
            )
        except Exception as exc:
            self._add_error(
                report,
                self.package_name,
                (
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),
            )
            return None

    def _import_module(
        self,
        *,
        module_name: str,
        report: ModuleLoadReport,
    ) -> ModuleType | None:
        try:
            return importlib.import_module(
                module_name
            )
        except Exception as exc:
            self._add_error(
                report,
                module_name,
                (
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),
            )
            return None

    def _register_from_module(
        self,
        *,
        module: ModuleType,
        report: ModuleLoadReport,
    ) -> None:
        classes = inspect.getmembers(
            module,
            inspect.isclass,
        )

        for _, cls in classes:
            if not self._is_strategy_module_class(
                cls=cls,
                module=module,
            ):
                continue

            report.discovered_classes += 1

            provider = str(
                cls.provider
            ).strip()

            if not provider:
                report.skipped_classes += 1
                continue

            try:
                self.registry.register(
                    cls,
                    replace=(
                        self.replace_existing
                    ),
                )

                report.registered_classes += 1

                report.registered_providers.append(
                    (
                        f"{cls.role.value}:"
                        f"{provider}"
                    )
                )

            except ValueError as exc:
                if self._already_registered(
                    cls
                ):
                    report.skipped_classes += 1
                    continue

                self._add_error(
                    report,
                    module.__name__,
                    (
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    ),
                )

                if self.fail_fast:
                    return

            except Exception as exc:
                self._add_error(
                    report,
                    module.__name__,
                    (
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    ),
                )

                if self.fail_fast:
                    return

    def _already_registered(
        self,
        cls: type[StrategyModule],
    ) -> bool:
        try:
            return self.registry.contains(
                role=cls.role,
                provider=cls.provider,
            )
        except Exception:
            return False

    @staticmethod
    def _is_strategy_module_class(
        *,
        cls: type,
        module: ModuleType,
    ) -> bool:
        if cls is StrategyModule:
            return False

        if not issubclass(
            cls,
            StrategyModule,
        ):
            return False

        # Не регистрируем импортированные в файл классы.
        # Только классы, объявленные непосредственно
        # внутри текущего module.
        if (
            cls.__module__
            != module.__name__
        ):
            return False

        # Абстрактные базовые классы
        # TrendModule / EntryModule и т.д.
        # регистрировать нельзя.
        if inspect.isabstract(
            cls
        ):
            return False

        return True

    @staticmethod
    def _should_skip_module(
        module_name: str,
    ) -> bool:
        parts = module_name.split(
            "."
        )

        leaf = parts[-1]

        if leaf.startswith(
            "_"
        ):
            return True

        if leaf in {
            "__pycache__",
        }:
            return True

        return False

    @staticmethod
    def _add_error(
        report: ModuleLoadReport,
        module_name: str,
        error: str,
    ) -> None:
        report.errors.append(
            ModuleLoadError(
                module_name=module_name,
                error=error,
            )
        )