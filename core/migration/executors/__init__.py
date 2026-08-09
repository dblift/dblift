"""
Migration executors.

Provides executor interfaces and implementations for non-SQL migration
formats. SQL migrations are executed by :class:`~core.migration.executor.
execution_engine.ExecutionEngine` itself — see the factory docstring.
"""

from .base_executor import BaseMigrationExecutor, MigrationExecutionResult
from .executor_factory import MigrationExecutorFactory
from .python_executor import MigrationContext, PythonMigrationExecutor

__all__ = [
    "BaseMigrationExecutor",
    "MigrationExecutionResult",
    "MigrationContext",
    "PythonMigrationExecutor",
    "MigrationExecutorFactory",
]
