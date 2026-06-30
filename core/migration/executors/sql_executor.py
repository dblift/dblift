"""
SQL migration executor.

Handles execution of SQL-based migrations (.sql files).
This wraps the existing SQL execution logic from ExecutionEngine.
"""

import time
from typing import Any, List

from core.migration.formats import MigrationFormat
from core.migration.migration import Migration

from .base_executor import BaseMigrationExecutor, MigrationExecutionResult


class SqlMigrationExecutor(BaseMigrationExecutor):
    """
    Executor for SQL migrations.

    Handles standard SQL migration files (.sql) using the existing
    SQL execution infrastructure.

    This executor:
    - Parses SQL statements from the migration content
    - Executes them through the database provider
    - Handles transactions and error reporting
    - Supports both execution and validation

    Attributes:
        sql_analyzer: SQL analyzer for statement parsing
        sql_execution_service: Service for executing SQL with journaling
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
        Initialize the SQL executor.

        Args:
            provider: Database provider instance
            config: DBLIFT configuration
            log: Logger instance
            sql_analyzer: Optional SQL analyzer (will use dialect from config if not provided)
            sql_execution_service: Optional SQL execution service for advanced features
        """
        super().__init__(provider, config, log)

        # Import here to avoid circular dependency
        if sql_analyzer is None:
            from core.migration.migration import _default_splitter_dialect
            from core.migration.sql.sql_analyzer import SqlAnalyzer

            # Resolve dialect from config; fall back to the registry-derived
            # generic dialect when config has none (ADR-26 E5 — no literal).
            dialect = ""
            if config and hasattr(config, "database") and config.database:
                dialect = getattr(config.database, "type", None) or ""
            if not dialect:
                dialect = _default_splitter_dialect()
            sql_analyzer = SqlAnalyzer(dialect=dialect, logger=log)

        self.sql_analyzer = sql_analyzer
        self.sql_execution_service = sql_execution_service

    def can_execute(self, migration: Migration) -> bool:
        """
        Check if this executor can handle SQL migrations.

        Args:
            migration: Migration to check

        Returns:
            True if the migration format is SQL
        """
        # Check if migration has format attribute
        if hasattr(migration, "format"):
            return migration.format == MigrationFormat.SQL

        # Fallback: check file extension if format not set
        if hasattr(migration, "path") and migration.path:
            return migration.path.suffix.lower() == ".sql"

        # Default to True for backward compatibility (all existing migrations are SQL)
        return True

    def get_supported_formats(self) -> List[MigrationFormat]:
        """Get list of supported formats."""
        return [MigrationFormat.SQL]

    def execute_migration(
        self, migration: Migration, dry_run: bool = False, **kwargs: Any
    ) -> MigrationExecutionResult:
        """
        Execute a SQL migration.

        Args:
            migration: SQL migration to execute
            dry_run: If True, parse and validate but don't execute
            **kwargs: Additional parameters (ignored for SQL)

        Returns:
            Result of the migration execution
        """
        start_time = time.time()

        try:
            # Validate first
            is_valid, errors = self.validate_migration(migration)
            if not is_valid:
                execution_time = int((time.time() - start_time) * 1000)
                return MigrationExecutionResult(
                    success=False,
                    migration=migration,
                    execution_time_ms=execution_time,
                    error=f"Validation failed: {'; '.join(errors)}",
                )

            # Parse SQL statements
            dialect = self.sql_analyzer.dialect
            statements = migration.parse_sql_statements(dialect=dialect)

            if dry_run:
                # In dry-run mode, just validate and report
                execution_time = int((time.time() - start_time) * 1000)
                return MigrationExecutionResult(
                    success=True,
                    migration=migration,
                    execution_time_ms=execution_time,
                    statements_executed=len(statements),
                    output=f"[DRY-RUN] Would execute {len(statements)} SQL statements",
                )

            # Execute statements
            if self.sql_execution_service:
                # Use the advanced execution service if available (with journaling)
                self._execute_via_service(migration, statements)
            else:
                # Direct execution via provider
                self._execute_via_provider(migration, statements)

            execution_time = int((time.time() - start_time) * 1000)

            return MigrationExecutionResult(
                success=True,
                migration=migration,
                execution_time_ms=execution_time,
                statements_executed=len(statements),
                output=f"Successfully executed {len(statements)} SQL statements",
            )

        except Exception as e:
            execution_time = int((time.time() - start_time) * 1000)
            error_msg = f"Error executing SQL migration: {str(e)}"
            self.log.error(error_msg)

            return MigrationExecutionResult(
                success=False,
                migration=migration,
                execution_time_ms=execution_time,
                error=error_msg,
            )

    def validate_migration(self, migration: Migration) -> tuple[bool, list[str]]:
        """
        Validate a SQL migration.

        Args:
            migration: Migration to validate

        Returns:
            Tuple of (is_valid, list of error messages)
        """
        errors = []

        # Check if content exists
        if not migration.content or not migration.content.strip():
            errors.append("Migration content is empty")
            return False, errors

        # Try to parse SQL statements
        try:
            dialect = self.sql_analyzer.dialect
            statements = migration.parse_sql_statements(dialect=dialect)

            if not statements:
                errors.append("No SQL statements found in migration")
                return False, errors

            # Basic SQL syntax validation could be added here
            # For now, if parsing succeeded, we consider it valid

        except Exception as e:
            errors.append(f"Failed to parse SQL: {str(e)}")
            return False, errors

        return True, []

    def supports_rollback(self, migration: Migration) -> bool:
        """
        Check if rollback is supported.

        For SQL migrations, rollback is supported through undo scripts (U*.sql files).
        This method checks if an undo script exists for the migration.

        Args:
            migration: Migration to check

        Returns:
            True if an undo script exists
        """
        # Rollback is handled by undo scripts, not programmatically
        # This would need to check if a corresponding U*.sql file exists
        # For now, return False - rollback is handled at a higher level
        return False

    def rollback_migration(
        self, migration: Migration, dry_run: bool = False, **kwargs: Any
    ) -> MigrationExecutionResult:
        """
        Rollback not supported for SQL migrations via this executor.

        SQL rollbacks are handled via undo scripts (U*.sql), not programmatically.
        Use supports_rollback() to check availability before calling this method.

        Returns:
            MigrationExecutionResult with success=False indicating rollback is not supported.
        """
        return MigrationExecutionResult(
            success=False,
            migration=migration,
            execution_time_ms=0,
            error=(
                f"{self.__class__.__name__} does not support programmatic rollback. "
                "Use undo scripts (U*.sql) for SQL migration rollback."
            ),
        )

    def _execute_via_service(self, migration: Migration, statements: List[str]) -> None:
        """
        Execute statements via the SQL execution service.

        Args:
            migration: Migration being executed
            statements: List of SQL statements to execute
        """
        # The sql_execution_service handles execution with journaling and tracking
        for statement in statements:
            self.sql_execution_service.execute_statement(sql=statement, migration=migration)

    def _execute_via_provider(self, migration: Migration, statements: List[str]) -> None:
        """
        Execute statements directly via the database provider.

        Args:
            migration: Migration being executed
            statements: List of SQL statements to execute
        """
        # Safely get schema, handling None config or missing database attribute
        schema = None
        if self.config and hasattr(self.config, "database") and self.config.database:
            schema = getattr(self.config.database, "schema", None)

        for statement in statements:
            if statement.strip():
                self.provider.execute_statement(sql=statement, schema=schema)

    def __str__(self) -> str:
        """String representation."""
        return f"SqlMigrationExecutor(dialect={self.sql_analyzer.dialect})"
