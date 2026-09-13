"""Compatibility bridge for legacy backend.application imports.

Canonical implementation lives in application.strategy_management_service.
"""
from application.strategy_management_service import StrategyManagementService

__all__ = ["StrategyManagementService"]
