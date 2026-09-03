"""
Base migration executor interface.

Defines the contract that all migration executors must implement.
This allows DBLIFT to support multiple migration formats (SQL, Python, etc.)
with a consistent interface.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, List, Optional

from dblift.core.logger import NullLog
from dblift.core.migration.formats import MigrationFormat
from dblift.core.migration.migration import Migration


@dataclass
class MigrationExecutionResult:
    """
    Result of executing a migration.

    Attributes:
        success: Whether the migration executed successfully
        migration: The migration that was executed
        execution_time_ms: Execution time in milliseconds
        statements_executed: Number of statements executed
        output: Optional output/log messages from execution
        error: Optional error message if execution failed
    """

    success: bool
    migration: Migration
    execution_time_ms: int
    statements_executed: int = 0
    output: Optional[str] = None
    error: Optional[str] = None

    def __str__(self) -> str:
        """String representation of the result."""
        status = "SUCCESS" if self.success else "FAILED"
        return (
            f"{status}: {self.migration.script_name} "
            f"({self.execution_time_ms}ms, {self.statements_executed} statements)"
        )


class BaseMigrationExecutor(ABC):
    """
    Abstract base class for migration executors.

    Each migration format (SQL, Python, JavaScript, etc.) must implement
    this interface to execute migrations. Undo is handled at a higher level
    via companion ``U*`` scripts executed through ``execute_migration``.

    Attributes:
        provider: Database provider instance
        config: DBLIFT configuration
        log: Logger instance
    """

    def __init__(self, provider: Any, config: Any, log: Any):
        """
        Initialize the executor.

        Args:
            provider: Database provider (BaseProvider instance)
            config: DBLIFT configuration
            log: Logger instance
        """
        self.provider = provider
        self.config = config
        self.log = log if log is not None else NullLog()

    @abstractmethod
    def can_execute(self, migration: Migration) -> bool:
        """
        Check if this executor can handle the given migration.

        Args:
            migration: Migration to check

        Returns:
            True if this executor can execute the migration

        Examples:
            >>> executor = PythonMigrationExecutor(provider, config, log)
            >>> migration = Migration(script_path=Path("V1__test.py"))
            >>> executor.can_execute(migration)
            True
        """

    @abstractmethod
    def execute_migration(
        self, migration: Migration, dry_run: bool = False, **kwargs: Any
    ) -> MigrationExecutionResult:
        """
        Execute a migration.

        Args:
            migration: Migration to execute
            dry_run: If True, simulate execution without making changes
            **kwargs: Additional executor-specific parameters

        Returns:
            Result of the migration execution

        Raises:
            Exception: If execution fails (implementation-specific)
        """

    @abstractmethod
    def validate_migration(self, migration: Migration) -> tuple[bool, list[str]]:
        """
        Validate a migration before execution.

        Args:
            migration: Migration to validate

        Returns:
            Tuple of (is_valid, error_messages)

        Examples:
            >>> is_valid, errors = executor.validate_migration(migration)
            >>> if not is_valid:
            ...     print(f"Validation errors: {errors}")
        """

    def get_supported_formats(self) -> List[MigrationFormat]:
        """
        Get list of migration formats supported by this executor.

        Returns:
            List of supported MigrationFormat values
        """
        return []

    def __str__(self) -> str:
        """String representation of the executor."""
        formats = ", ".join(str(f) for f in self.get_supported_formats())
        return f"{self.__class__.__name__}(formats=[{formats}])"
