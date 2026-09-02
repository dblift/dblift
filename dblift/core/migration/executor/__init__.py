"""
Migration executor module.

This module contains the core migration execution logic split into focused components:
- migration_executor.py: Main orchestrator and public API
- execution_engine.py: Core migration execution logic
- placeholder_manager.py: Placeholder replacement logic
"""

from .migration_executor import MigrationExecutor

__all__ = ["MigrationExecutor"]
