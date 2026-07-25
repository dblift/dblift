"""
Migration executor factory.

Routes migrations to the appropriate executor based on their format.
This is the central "aiguilleur" (router) that detects migration type
and directs it to the correct executor.
"""

import logging
from typing import Any, Dict, List, Optional, Type

from core.exceptions import UnsupportedMigrationFormatError
from core.logger import NullLog
from core.migration.formats import MigrationFormat
from core.migration.migration import Migration

from .base_executor import BaseMigrationExecutor, MigrationExecutionResult
from .python_executor import PythonMigrationExecutor
from .sql_executor import SqlMigrationExecutor

logger = logging.getLogger(__name__)


class MigrationExecutorFactory:
    """
    Factory for creating and routing to migration executors.

    This class acts as a router ("aiguilleur") that:
    1. Detects the format of a migration
    2. Finds the appropriate executor for that format
    3. Routes the migration to that executor

    This architecture allows DBLIFT to support multiple migration formats
    (SQL, Python, JavaScript, etc.) without changing the core execution logic.

    Examples:
        >>> factory = MigrationExecutorFactory(provider, config, log)
        >>> factory.register_executor(SqlMigrationExecutor)
        >>>
        >>> # Execute a SQL migration
        >>> migration = Migration(script_path=Path("V1__test.sql"))
        >>> result = factory.execute(migration)

        >>> # Execute a Python migration
        >>> migration = Migration(script_path=Path("V1__test.py"))
        >>> result = factory.execute(migration)
    """

    def __init__(
        self,
        provider: Any,
        config: Any,
        log: Any,
        sql_analyzer: Any = None,
        sql_execution_service: Any = None,
    ):
        """
        Initialize the executor factory.

        Args:
            provider: Database provider instance
            config: DBLIFT configuration
            log: Logger instance
            sql_analyzer: Optional SQL analyzer
            sql_execution_service: Optional SQL execution service
        """
        self.provider = provider
        self.config = config
        self.log = log if log is not None else NullLog()
        self.sql_analyzer = sql_analyzer
        self.sql_execution_service = sql_execution_service

        # Registry of executor classes by format
        self._executor_classes: Dict[MigrationFormat, Type[BaseMigrationExecutor]] = {}

        # Cache of initialized executors
        self._executor_instances: Dict[MigrationFormat, BaseMigrationExecutor] = {}

        # Register default executors
        self.register_executor_class(MigrationFormat.SQL, SqlMigrationExecutor)
        self.register_executor_class(MigrationFormat.PYTHON, PythonMigrationExecutor)

    def register_executor_class(
        self, format: MigrationFormat, executor_class: Type[BaseMigrationExecutor]
    ) -> None:
        """
        Register an executor class for a migration format.

        Args:
            format: Migration format this executor handles
            executor_class: Executor class (not instance) to register

        Examples:
            >>> factory.register_executor_class(MigrationFormat.PYTHON, PythonMigrationExecutor)
        """
        self._executor_classes[format] = executor_class
        self.log.debug(f"Registered executor {executor_class.__name__} for format {format}")

    def get_executor(self, migration: Migration) -> Optional[BaseMigrationExecutor]:
        """
        Get the appropriate executor for a migration.

        This is the core routing logic that determines which executor
        should handle a given migration based on its format.

        Args:
            migration: Migration to get executor for

        Returns:
            Executor instance that can handle the migration, or None if
            no suitable executor is found

        Examples:
            >>> migration = Migration(script_path=Path("V1__test.sql"))
            >>> executor = factory.get_executor(migration)
            >>> print(executor)  # SqlMigrationExecutor(dialect=postgresql)
        """
        # Determine the migration format
        if hasattr(migration, "format"):
            format = migration.format
        elif hasattr(migration, "path") and migration.path:
            # Detect format from file extension
            from core.migration.formats import MigrationFormatDetector

            format = MigrationFormatDetector.detect_from_path(migration.path)
        else:
            # Default to SQL for backward compatibility
            format = MigrationFormat.SQL

        self.ensure_format_supported(migration, format)

        # Check if format is supported
        if format not in self._executor_classes:
            self.log.warning(
                f"No executor registered for format {format}. "
                f"Migration: {migration.script_name}"
            )
            return None

        # Get or create executor instance for this format
        if format not in self._executor_instances:
            executor_class = self._executor_classes[format]

            # Create instance with appropriate arguments
            if format == MigrationFormat.SQL:
                # SQL executor needs sql_analyzer and sql_execution_service
                executor = executor_class(  # type: ignore[call-arg]
                    self.provider,
                    self.config,
                    self.log,
                    self.sql_analyzer,
                    self.sql_execution_service,
                )
            else:
                # Other executors use standard constructor
                executor = executor_class(self.provider, self.config, self.log)

            self._executor_instances[format] = executor
            self.log.debug(f"Created executor instance: {executor}")

        return self._executor_instances[format]

    def ensure_format_supported(self, migration: Migration, format: MigrationFormat) -> None:
        """Raise when the target dialect cannot run migrations of *format*.

        Document stores declare ``supports_sql_migrations = False``: they
        have no SQL DDL, so a ``.sql`` migration is a mistake to surface
        rather than something to translate.

        Public because callbacks do not route through :meth:`get_executor`
        — ``ExecutionEngine.execute_callback`` runs SQL callbacks itself and
        needs the same verdict, or a ``.sql`` callback on a document store
        would fail later with an opaque parser/driver error instead of
        ``DBLIFT-NOSQL-001``.
        """
        if format is not MigrationFormat.SQL:
            return
        quirks = getattr(self.provider, "quirks", None)
        if quirks is None or getattr(quirks, "supports_sql_migrations", True):
            return

        dialect = getattr(quirks, "dialect_name", "") or "this dialect"
        raise UnsupportedMigrationFormatError(
            f"{UnsupportedMigrationFormatError.code}: '{migration.script_name}' is a SQL "
            f"migration, but the '{dialect}' dialect does not execute SQL migrations. "
            "Rewrite it as a Python migration exposing 'def migrate(context)' and drive "
            "the vendor SDK through 'context.db' / 'context.raw_client'. "
            "See docs/user-guide/nosql-python-migrations.md."
        )

    def execute(
        self, migration: Migration, dry_run: bool = False, **kwargs: Any
    ) -> MigrationExecutionResult:
        """
        Execute a migration using the appropriate executor.

        This is a convenience method that:
        1. Finds the right executor for the migration
        2. Executes the migration
        3. Returns the result

        Args:
            migration: Migration to execute
            dry_run: If True, simulate execution without making changes
            **kwargs: Additional executor-specific parameters

        Returns:
            MigrationExecutionResult from the executor

        Raises:
            ValueError: If no suitable executor is found

        Examples:
            >>> result = factory.execute(migration, dry_run=True)
            >>> print(result.success)
            True
        """
        executor = self.get_executor(migration)

        if executor is None:
            raise ValueError(
                f"No executor available for migration {migration.script_name}. "
                f"Format: {getattr(migration, 'format', 'unknown')}"
            )

        # Validate before execution
        is_valid, errors = executor.validate_migration(migration)
        if not is_valid:
            from .base_executor import MigrationExecutionResult

            return MigrationExecutionResult(
                success=False,
                migration=migration,
                execution_time_ms=0,
                error=f"Validation failed: {'; '.join(errors)}",
            )

        # Execute
        return executor.execute_migration(migration, dry_run=dry_run, **kwargs)

    def validate(self, migration: Migration) -> tuple[bool, list[str]]:
        """
        Validate a migration using the appropriate executor.

        Args:
            migration: Migration to validate

        Returns:
            Tuple of (is_valid, list of error messages)
        """
        executor = self.get_executor(migration)

        if executor is None:
            return False, [f"No executor available for migration {migration.script_name}"]

        return executor.validate_migration(migration)

    def get_supported_formats(self) -> List[MigrationFormat]:
        """
        Get list of all supported migration formats.

        Returns:
            List of MigrationFormat values that have registered executors
        """
        return list(self._executor_classes.keys())

    def is_format_supported(self, format: MigrationFormat) -> bool:
        """
        Check if a migration format is supported.

        Args:
            format: Migration format to check

        Returns:
            True if an executor is registered for this format
        """
        return format in self._executor_classes

    def __str__(self) -> str:
        """String representation of the factory."""
        formats = ", ".join(str(f) for f in self.get_supported_formats())
        return f"MigrationExecutorFactory(supported_formats=[{formats}])"
