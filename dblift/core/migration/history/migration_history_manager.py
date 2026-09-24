"""Migration history manager — persists applied migrations and validates checksums against the DB."""

import logging
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Union, cast

from dblift.core.logger import Log
from dblift.core.migration.migration import AppliedMigration, Migration, MigrationType
from dblift.core.migration.scripting.migration_script_manager import MigrationScriptManager
from dblift.db.provider_interfaces import TransactionalProvider


@dataclass(frozen=True)
class FlywayCompatibilitySnapshot:
    """Immutable table data collected by HistoryManager."""

    flyway_exists: bool = False
    dblift_exists: bool = False
    flyway_migrations: tuple[Mapping[str, Any], ...] = ()
    dblift_migrations: tuple[Mapping[str, Any], ...] = ()
    collection_error: str = ""


class MigrationHistoryManager:
    """Manages migration history in the database."""

    script_manager: Optional["MigrationScriptManager"] = None

    def read_history_rows(
        self, schema: str, table: str, *, flyway_source: bool = False
    ) -> List[Dict[str, Any]]:
        """Collect import rows using the provider's authoritative identifier policy."""
        if not flyway_source or not self.provider.quirks.flyway_source_table_case_sensitive:
            return cast(List[Dict[str, Any]], self.provider.get_applied_migrations(schema, table))
        qualified_table = self.provider.get_schema_qualified_name(schema, table)
        rows = self.provider.execute_query(f"""
            SELECT script, installed_rank, version, description,
                   type, checksum, installed_by, installed_on, execution_time, success
            FROM {qualified_table} ORDER BY installed_rank
        """)
        return [self._normalize_flyway_row(row) for row in rows]

    @staticmethod
    def _normalize_flyway_row(row: Dict[str, Any]) -> Dict[str, Any]:
        fields = (
            "script",
            "installed_rank",
            "version",
            "description",
            "type",
            "checksum",
            "installed_by",
            "installed_on",
            "execution_time",
            "success",
        )

        def get_value(name: str) -> Any:
            return row.get(name, row.get(name.upper(), row.get(name.lower())))

        return {field: get_value(field) for field in fields}

    def history_source_exists(self, schema: str, table: str) -> bool:
        """Report whether an import source exists when the provider supports probing."""
        return not hasattr(self.provider, "table_exists") or self.provider.table_exists(
            schema, table
        )

    def resolve_flyway_source_table(self, table: str) -> str:
        """Normalize only Flyway's default name for case-sensitive providers."""
        if (
            table == "flyway_schema_history"
            and self.provider.quirks.flyway_source_table_case_sensitive
        ):
            return str(self.provider.get_normalized_object_name(table))
        return table

    def ensure_history_table(self) -> None:
        """Initialize history when absent, preserving the public validator adapter."""
        if not self.has_history_table:
            self.create_schema_and_history_table()

    def collect_flyway_compatibility_snapshot(self) -> FlywayCompatibilitySnapshot:
        """Read provider tables without deciding whether their histories agree."""
        flyway_exists = False
        dblift_exists = False
        flyway_rows: tuple[Mapping[str, Any], ...] = ()
        dblift_rows: tuple[Mapping[str, Any], ...] = ()
        error = ""
        try:
            flyway_exists = self.provider.table_exists(self.schema, "flyway_schema_history")
            if flyway_exists:
                dblift_exists = self.provider.table_exists(
                    self.schema, self.normalized_history_table
                )
            if flyway_exists and dblift_exists:
                flyway_query = f'''SELECT "version", "description", "type", "script",
                    "installed_by", "installed_rank", "checksum", "success"
                    FROM {self.schema}.flyway_schema_history ORDER BY "installed_rank"'''
                flyway_rows = tuple(
                    MappingProxyType(dict(row)) for row in self.provider.execute_query(flyway_query)
                )
                dblift_query = f"""SELECT version, description, type, script,
                    installed_by, installed_rank, checksum, success
                    FROM {self.schema}.{self.history_table} ORDER BY installed_rank"""
                dblift_rows = tuple(
                    MappingProxyType(dict(row)) for row in self.provider.execute_query(dblift_query)
                )
        except Exception as exc:
            error = str(exc)
        return FlywayCompatibilitySnapshot(
            flyway_exists, dblift_exists, flyway_rows, dblift_rows, error
        )

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

        ADR-0015: every call site that qualifies the history-
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
        if self.script_manager is None:
            self.script_manager = MigrationScriptManager(cast(Log, self.logger))
        return [
            applied.to_migration(
                logger=self.logger,
                _filename_metadata=self.script_manager.parse_filename(applied.script_name),
            )
            for applied in self.get_applied_migration_records()
        ]

    def get_applied_migration_records(self) -> List[AppliedMigration]:
        """Get applied migrations from history as first-class history records."""
        dicts = self.provider.get_applied_migrations(self.schema, self.history_table)
        return [AppliedMigration.from_history_row(m) for m in dicts]

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
            # No ``installed_on``: providers now bind a supplied value, and a
            # client-side clock here would replace each dialect's own
            # ``CURRENT_TIMESTAMP`` default (UTC on SQLite, server time
            # elsewhere) with local time. Only import-flyway, which carries a
            # date it must preserve, supplies this key.
            "installed_by": self.installed_by,
        }

        # Log the actual values we're passing to the provider
        if hasattr(self, "logger") and self.logger:
            self.logger.debug(
                f"Recorded migration info: script={migration_info['script']}, type={migration_info['type']}"
            )

        self.provider.record_migration(self.schema, migration_info, self.history_table)

    def create_schema_and_history_table(self, create_schema: bool = False) -> None:
        """Ensure schema and history table exist.

        Transparently retries when a concurrent process is racing to create
        the same schema/history table — PostgreSQL's ``CREATE SCHEMA IF NOT
        EXISTS`` is not atomic under concurrent sessions and the losing
        transaction is left in an aborted state until rolled back, which
        cascades "transaction is aborted" errors onto every subsequent
        statement.

        Race detection is delegated to ``provider.quirks.is_schema_history_race_error``
        instead of a single hard-coded marker list: dialects whose bare
        ``CREATE TABLE`` (no ``IF NOT EXISTS``) reports the race in wording
        the default English substrings don't cover — DB2 (SQL0601N), Oracle
        (ORA-00955), SQL Server (Msg 2714) — override it with a stable
        vendor error-code check instead of driver message text.

        Args:
            create_schema: True when called from baseline command, False for regular migrations
        """
        import random
        import time

        MAX_ATTEMPTS = 3

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
                is_race = self.provider.quirks.is_schema_history_race_error(str(e))
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
                if isinstance(self.provider, TransactionalProvider):
                    try:
                        self.provider.rollback_transaction()
                    except Exception:
                        pass
                # Exponential backoff with jitter lets the winner commit.
                time.sleep(0.1 * (2**attempt) + random.uniform(0, 0.05))

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
                table_name=self.normalized_history_table,
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
