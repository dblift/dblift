"""Migration history manager — persists applied migrations and validates checksums against the DB."""

import datetime
import logging
from typing import TYPE_CHECKING, Any, List, Optional, Tuple, Union, cast

from core.logger import Log
from core.migration.migration import AppliedMigration, Migration, MigrationType

if TYPE_CHECKING:
    from .migration_script_manager import MigrationScriptManager


class ValidationResult:
    """Result of a validation operation."""

    def __init__(self) -> None:
        """Start with a success state and an empty error message."""
        self.success = True
        self.error_message = ""


class MigrationHistoryManager:
    """Manages migration history in the database."""

    script_manager: Optional["MigrationScriptManager"] = None

    def __init__(
        self,
        provider: Any,
        schema: str,
        installed_by: str,
        logger: Optional[Log] = None,
        table_name: Optional[str] = None,
    ) -> None:
        """Initialize the history manager.

        Args:
            provider: Database provider instance
            schema: Schema name for history table
            installed_by: User who is installing migrations
            logger: Optional logger instance
            table_name: Optional custom table name (defaults to dblift_schema_history)
        """
        self.provider = provider
        self.schema = schema
        self.installed_by = installed_by
        self.logger = logger or logging.getLogger(__name__)

        # Use the provided table name or default
        # Each database provider handles case sensitivity through get_schema_qualified_name()
        # - Oracle & DB2: Convert to uppercase unquoted identifiers
        # - PostgreSQL: Use lowercase quoted identifiers
        # - MySQL: Use lowercase backticked identifiers
        # - SQL Server: Case-insensitive, use lowercase by convention
        base_table_name = table_name or "dblift_schema_history"
        self.history_table = base_table_name

        if self.logger:
            self.logger.debug(
                f"[DEBUG] MigrationHistoryManager __init__: schema={self.schema}, table={self.history_table}"
            )

    @property
    def normalized_history_table(self) -> str:
        """Return the history-table name in the case the database stores it.

        Oracle and DB2 fold unquoted identifiers to UPPERCASE at DDL
        time; PostgreSQL / SQL Server / MySQL / SQLite / CosmosDB fold
        to lowercase. ``self.history_table`` stores the operator-supplied
        (or default) name verbatim — usually ``"dblift_schema_history"``
        in lowercase — which Oracle cannot match when it is wrapped in
        ANSI double-quotes later (a quoted lowercase identifier is
        *literally* lowercase to Oracle).

        ADR-0015 (BUG-03): every call site that qualifies the history-
        table identifier via ``provider.get_schema_qualified_name`` or
        ``provider.table_exists`` must pass the normalized form so the
        quoted literal matches what the database actually stored.
        """
        # ``get_normalized_object_name`` is typed as ``Any`` on the
        # base provider — wrap to satisfy mypy strict-return-type.
        return str(self.provider.get_normalized_object_name(self.history_table))

    @property
    def has_history_table(self) -> bool:
        """Always perform a live check for the existence of the history table."""
        return bool(self.provider.table_exists(self.schema, self.normalized_history_table))

    def get_applied_migrations(self) -> List[Migration]:
        """Get list of applied migrations from history table as Migration objects."""
        return [
            applied.to_migration(logger=self.logger)
            for applied in self.get_applied_migration_records()
        ]

    def get_applied_migration_records(self) -> List[AppliedMigration]:
        """Get applied migrations from history as first-class history records."""
        dicts = self.provider.get_applied_migrations(self.schema, self.history_table)
        return [AppliedMigration.from_history_row(m) for m in dicts]

    def get_applied_migrations_legacy(self) -> List[Migration]:
        """Backward-compatible alias for callers that explicitly need Migration objects."""
        dicts = self.provider.get_applied_migrations(self.schema, self.history_table)
        from ..migration import dict_to_migration

        return [dict_to_migration(m, logger=self.logger) for m in dicts]

    def record_migration(self, migration: Migration, success: bool, execution_time: int) -> None:
        """Record a migration in the history table."""
        # Ensure success is explicitly a boolean to avoid type confusion
        success_flag = bool(success)

        if hasattr(self, "logger") and self.logger:
            self.logger.debug(
                f"Recording migration {migration.script_name} with success={success_flag}, type={migration.type.name}"
            )

        # Log specific details for repeatable migrations to help diagnose issues
        if migration.type == MigrationType.REPEATABLE:
            if hasattr(self, "logger") and self.logger:
                self.logger.debug(f"Recording REPEATABLE migration: {migration.script_name}")
                self.logger.debug(f"  - checksum: {migration.checksum}")
                self.logger.debug(
                    f"  - content length: {len(migration.sql_content) if hasattr(migration, 'sql_content') else 'N/A'}"
                )

        migration_info = {
            "script": migration.script_name,
            "version": migration.version,
            "description": migration.description,
            "type": migration.type.name,
            "checksum": migration.checksum,
            "success": success_flag,
            "execution_time": execution_time,
            "installed_on": datetime.datetime.now(),
            "installed_by": self.installed_by,
        }

        # Log the actual values we're passing to the provider
        if hasattr(self, "logger") and self.logger:
            self.logger.debug(
                f"Recorded migration info: script={migration_info['script']}, type={migration_info['type']}"
            )

        self.provider.record_migration(self.schema, migration_info, self.history_table)

    def acquire_migration_lock(self) -> bool:
        """Try to acquire the migration lock."""
        return bool(self.provider.acquire_migration_lock(self.schema))

    def release_migration_lock(self) -> bool:
        """Release the migration lock.

        Returns:
            bool: True if successful, False if failed to release
        """
        if not self.provider:
            return False

        try:
            # It's okay if release fails during testing - log at warning level instead of error
            result = self.provider.release_migration_lock(self.schema)
            if not result and self.provider.log:
                self.provider.log.warning(
                    f"Could not release migration lock for schema {self.schema}."
                )
            return bool(result)
        except Exception as e:
            if self.provider.log:
                self.provider.log.warning(
                    f"Exception while releasing migration lock for schema {self.schema}: {str(e)}."
                )
            return False

    def validate_history_table(self, command: str = "migrate") -> ValidationResult:
        """Validate that the history table exists or can be created.

        This method checks if the history table exists, and for certain commands
        (like undo) that require the history table to exist, returns an error
        if it doesn't. For other commands (like migrate), the table will be
        created later if needed.

        Args:
            command: The command being executed (migrate, undo, etc.)

        Returns:
            ValidationResult: Result of the validation
        """
        result = ValidationResult()

        try:
            # Check if schema history table exists (use normalized name for dialect)
            history_table_exists = self.provider.table_exists(
                self.schema, self.normalized_history_table
            )

            # For undo command, the history table must exist
            if command.lower() == "undo" and not history_table_exists:
                error_msg = f"Cannot undo migrations: Schema history table [{self.schema}].[{self.history_table}] does not exist"
                if self.logger:
                    self.logger.error(error_msg)
                result.success = False
                result.error_message = error_msg
                return result

            # For other commands, just log information - table will be created during execution if needed
            if not history_table_exists:
                if self.logger:
                    self.logger.debug(
                        f"Schema history table [{self.schema}].[{self.history_table}] does not exist yet"
                    )

            return result

        except Exception as e:
            error_msg = f"Error checking history table: {str(e)}"
            if self.logger:
                self.logger.error(error_msg)
            result.success = False
            result.error_message = error_msg
            return result

    def create_schema_and_history_table(self, create_schema: bool = False) -> None:
        """Ensure schema and history table exist.

        Transparently retries when a concurrent process is racing to create
        the same schema/history table — PostgreSQL's ``CREATE SCHEMA IF NOT
        EXISTS`` is not atomic under concurrent sessions and the losing
        transaction is left in an aborted state until rolled back, which
        cascades "transaction is aborted" errors onto every subsequent
        statement. BUG-07.

        Args:
            create_schema: True when called from baseline command, False for regular migrations
        """
        import random
        import time

        MAX_ATTEMPTS = 3
        RACE_MARKERS = (
            "already exists",
            "duplicate key",
            "tuple concurrently updated",
            "transaction is aborted",
            "concurrently",
        )

        for attempt in range(MAX_ATTEMPTS):
            try:
                if self.logger:
                    self.logger.debug(
                        f"[DEBUG] create_schema_and_history_table: schema={self.schema}, "
                        f"table={self.history_table}, create_schema={create_schema}, "
                        f"attempt={attempt + 1}/{MAX_ATTEMPTS}"
                    )
                if create_schema:
                    self.provider.create_schema_if_not_exists(self.schema)
                self.provider.create_history_table_if_not_exists(
                    self.schema, create_schema, self.history_table
                )
                return
            except Exception as e:
                err_str = str(e).lower()
                is_race = any(marker in err_str for marker in RACE_MARKERS)
                if not is_race or attempt == MAX_ATTEMPTS - 1:
                    raise
                if self.logger:
                    self.logger.warning(
                        f"Concurrent schema/history-table creation detected "
                        f"(attempt {attempt + 1}/{MAX_ATTEMPTS}): {e}. Retrying..."
                    )
                # Clear any aborted-transaction state on the provider's connection
                # so the retry can issue statements again. Swallow failures — the
                # retry itself will surface any real issue.
                if hasattr(self.provider, "rollback_transaction"):
                    try:
                        self.provider.rollback_transaction()
                    except Exception:
                        pass
                # Exponential backoff with jitter lets the winner commit.
                time.sleep(0.1 * (2**attempt) + random.uniform(0, 0.05))

    def record_undo(self, migration: Migration) -> bool:
        """Record that a migration has been undone in the history table.

        This method marks the migration as undone in the history table,
        which prevents it from being considered in future operations.

        Args:
            migration: Migration that was undone

        Returns:
            bool: True if the undo was recorded, False if not (e.g., already undone)
        """
        script_name = getattr(migration, "script_name", None)
        if not isinstance(script_name, str):
            script_name = None
        return bool(
            self.provider.record_undo(
                self.schema,
                migration.version,
                self.history_table,
                script_name,
            )
        )

    def delete_failed_migration_entry(self, script_name: str) -> bool:
        """Remove the failed history row for *script_name*.

        ``repair`` calls this so a failed migration can be re-applied. The
        statement (or SDK call) belongs to the backend, so this only
        delegates and interprets the answer.

        Some drivers report an unknown row count of ``-1`` for DML rather
        than the number affected; in that case the row is re-read to decide
        whether it is really gone.

        Returns:
            True when a failed row was removed.
        """
        rows_affected = int(
            self.provider.delete_failed_migration_entry(
                self.schema, script_name, self.normalized_history_table
            )
        )
        if rows_affected >= 0:
            return rows_affected > 0
        return not self._failed_row_still_present(script_name)

    def _failed_row_still_present(self, script_name: str) -> bool:
        """Re-read the failed row after an unknown-rowcount delete."""
        if not hasattr(self.provider, "execute_query"):
            return False
        qualified = self.provider.get_schema_qualified_name(
            self.schema, self.normalized_history_table
        )
        false_literal = self.provider.quirks.boolean_false_literal
        remaining = self.provider.execute_query(
            f"SELECT 1 FROM {qualified} WHERE script = ? AND success = {false_literal}",
            [script_name],
        )
        return bool(remaining)

    def repair_checksum(self, script_name: str, new_checksum: Union[int, str]) -> bool:
        """Repair the checksum of a migration in the history table.

        This method updates the checksum of a migration that has been modified,
        allowing the validation to pass and further migrations to proceed.

        Args:
            script_name: Name of the script to repair
            new_checksum: New checksum value

        Returns:
            bool: True if the record was updated, False otherwise
        """
        try:
            # Mark the migration as successful so it won't be flagged as failed after the checksum update
            updated = self.provider.repair_migration_history(
                self.schema,
                script_name,
                new_checksum,
                success_value=True,
                table_name=self.history_table,
            )
            if not updated and self.logger:
                self.logger.warning(
                    f"No migration history entry updated for {script_name}; checksum remains unchanged"
                )
            return bool(updated)
        except Exception as e:
            if hasattr(self, "logger") and self.logger:
                self.logger.error(f"Failed to repair migration checksum: {str(e)}")
            return False

    def get_columns_query(self, table: str) -> Union[str, Tuple[Any, ...]]:
        """Get a database-specific query to retrieve column information from a table.

        Delegates to the provider for database-specific implementation.

        Args:
            table: Table name

        Returns:
            str or tuple: SQL query string, or (sql, params) tuple for parameterized queries.
            Callers must handle both forms (see view_extractor.py for reference implementation).
        """
        return cast(
            Union[str, Tuple[str, List[Any]]], self.provider.get_columns_query(self.schema, table)
        )

    def get_add_column_sql(self, table: str, column: str, type_def: str) -> str:
        """Generate database-specific SQL to add a column to a table.

        Delegates to the provider for database-specific implementation.

        Args:
            table: Table name
            column: Column name to add
            type_def: Column data type definition

        Returns:
            str: SQL for adding the column
        """
        # Use the provider's method to get database-specific SQL
        return str(self.provider.get_add_column_sql(self.schema, table, column, type_def))

    def get_parameter_placeholders(self, count: int) -> str:
        """Get database-specific parameter placeholders for prepared statements.

        Delegates to the provider for database-specific implementation.

        Args:
            count: Number of parameters

        Returns:
            str: Parameter placeholders string
        """
        # Use the provider's method to get database-specific placeholders
        return str(self.provider.get_parameter_placeholders(count))
