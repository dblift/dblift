"""Base abstract class for database history managers."""

import os
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from dblift.core.constants import DEFAULT_HISTORY_TABLE
from dblift.core.logger import Log, NullLog
from dblift.core.migration.migration import MigrationType
from dblift.db.provider_registry import ProviderRegistry

# History rows are written with ``migration.type.name`` and read back by
# ``AppliedMigration.from_history_row`` through the name-based ``MigrationType[...]``
# lookup, so the name is the persisted contract. The persisted vocabulary is frozen:
# never rename or add stored values — historical rows would silently degrade to
# ``UNKNOWN``.

#: History ``type`` written for a synthetic undo row, derived rather than typed.
UNDO_HISTORY_TYPE: str = MigrationType.UNDO_SQL.name


def installed_on_to_bind(value: Any) -> Optional[Any]:
    """Return the ``installed_on`` value to bind, or ``None`` to keep the column default.

    ``record_migration`` normally omits ``installed_on`` so the history table's
    ``CURRENT_TIMESTAMP`` default stamps the row. ``import-flyway`` instead
    carries the source row's own timestamp, which has to survive the copy —
    otherwise an imported row pairs Flyway's real ``installed_by`` with the
    date of the import.

    A missing or blank value falls back to the default rather than binding
    ``NULL``, which several dialects declare the column ``NOT NULL``.
    """
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return value


class BaseHistoryManager(ABC):
    """Abstract base class for database-specific history managers.

    This class defines the common interface that all database providers must implement
    for migration history management. Each database provider implements these methods
    according to its SQL dialect and driver requirements.
    """

    def __init__(
        self,
        query_executor: Any,
        schema_operations: Any,
        config: Any,
        log: Optional[Log] = None,
    ) -> None:
        """Initialize the history manager.

        Args:
            query_executor: Database-specific query executor instance
            schema_operations: Database-specific schema operations instance
            config: Application configuration (DbliftConfig). Required by
                implementations that need it (e.g. CosmosDB for container
                resolution via connection_manager.config). Implementations
                that do not use config may pass it through and ignore it.
            log: Optional logger for operation tracking
        """
        self.query_executor: Any = query_executor
        self.schema_operations: Any = schema_operations
        self.config: Any = config
        self.log: Log = log if log is not None else NullLog()

    @abstractmethod
    def create_migration_history_table_if_not_exists(
        self,
        connection: Any,
        schema: str,
        create_schema: bool = False,
        table_name: str = DEFAULT_HISTORY_TABLE,
    ) -> None:
        """Create the migration history table if it doesn't exist.

        Implementation varies by database due to different SQL syntax,
        data types, and identifier handling.

        Args:
            connection: Active database connection (provided by Provider)
            schema: Schema name
            create_schema: Whether to create schema if it doesn't exist
            table_name: Custom history table name
        """

    @abstractmethod
    def record_migration(
        self,
        connection: Any,
        schema: str,
        migration_info: Dict[str, Any],
        table_name: Optional[str] = None,
    ) -> None:
        """Record a migration in the history table.

        Implementation varies by database due to different parameter binding,
        data type handling, and SQL syntax requirements.

        Args:
            connection: Active database connection (provided by Provider)
            schema: Schema name
            migration_info: Dictionary containing migration information
            table_name: Custom history table name
        """

    @abstractmethod
    def get_applied_migrations(
        self, connection: Any, schema: str, table_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get list of applied migrations from history table.

        Implementation varies by database due to different result set handling,
        data type conversions, and column name casing.

        Args:
            connection: Active database connection (provided by Provider)
            schema: Schema name
            table_name: Custom history table name

        Returns:
            List of dictionaries containing migration information
        """

    @abstractmethod
    def create_history_table(self, schema: str, table_name: str) -> str:
        """Generate SQL to create the migration history table.

        Implementation varies by database due to different SQL syntax,
        data types, and constraint definitions.

        Args:
            schema: Schema name
            table_name: History table name

        Returns:
            SQL statement to create the history table
        """

    # Common utility methods that can be shared across implementations

    def _get_default_table_name(self) -> str:
        """Get the default history table name for this database.

        Default implementation returns the standard name. Database-specific
        implementations can override this for case-sensitive requirements.

        Returns:
            Default history table name
        """
        return DEFAULT_HISTORY_TABLE

    def _check_baseline_safety(self, connection: Any, schema: str, table_name: str) -> None:
        """Refuse to baseline a schema whose history table already has rows.

        Called by vendor ``create_migration_history_table_if_not_exists``
        implementations at the top of the "table already exists" branch when
        ``create_schema=True`` (baseline command). Mirrors the pre-X-5 check
        previously hosted on the provider base (issue #405).

        Args:
            connection: Active database / SDK connection.
            schema: Schema name.
            table_name: History table name (already normalised by the caller
                if dialect-specific casing applies).

        Raises:
            RuntimeError: If the history table contains one or more rows, or
                if the COUNT query itself fails (wrapped with a "Could not
                verify if history table is empty" message).
        """
        qualified_table = self.query_executor.get_schema_qualified_name(schema, table_name)
        # ``COUNT(1)`` instead of ``COUNT(*)``: Azure Cosmos DB SQL API rejects
        # the ``*`` form (per cursor[bot] PR #421). ``COUNT(1)`` is supported
        # by every relational dialect and Cosmos DB, so one query shape covers all
        # seven vendors.
        count_query = f"SELECT COUNT(1) as count FROM {qualified_table}"

        try:
            result = self.query_executor.execute_query(connection, count_query)
        except RuntimeError:
            raise
        except Exception as e:
            error_msg = f"Could not verify if history table is empty: {e}"
            self.log.error(error_msg)
            raise RuntimeError(error_msg)

        migration_count = 0
        if result:
            first = result[0]
            if isinstance(first, dict):
                migration_count = int(first.get("count", first.get("COUNT", 0)) or 0)

        if migration_count > 0:
            error_msg = (
                f"Schema {schema} already contains a migration history table "
                f"{table_name} with {migration_count} migration(s). "
                "Baseline cannot be applied to a schema with existing migrations."
            )
            self.log.error(error_msg)
            raise RuntimeError(error_msg)

    def repair_migration_history(
        self,
        connection: Any,
        schema: str,
        script_name: str,
        checksum: Any,
        success_value: Optional[Any] = None,
        table_name: Optional[str] = None,
    ) -> bool:
        """Repair a migration record in the history table.

        Generic implementation using parameterised ``UPDATE``. Vendor-specific
        implementations may override for dialect-specific column casing or
        type binding (Oracle uses uppercase columns; SQL Server uses BIT, etc.).

        Args:
            connection: Active database connection (provided by Provider).
            schema: Schema name.
            script_name: Script name to repair.
            checksum: New checksum value (int for CRC32, str for legacy).
            success_value: ``None`` to set ``success = NULL`` (traditional
                "needs reapplication" marker); otherwise the explicit value.
            table_name: Custom history table name.

        Returns:
            True if a history row was updated, False otherwise.
        """
        table_name_to_use = table_name or self._get_default_table_name()

        if not self.query_executor.table_exists(connection, schema, table_name_to_use):
            self.log.warning(
                f"Migration history table {table_name_to_use} does not exist in schema {schema}"
            )
            return False

        qualified_table = self.query_executor.get_schema_qualified_name(schema, table_name_to_use)

        if success_value is None:
            update_sql = f"""
            UPDATE {qualified_table}
            SET checksum = ?, success = NULL
            WHERE script = ?
            """
            params: List[Any] = [checksum, script_name]
        else:
            update_sql = f"""
            UPDATE {qualified_table}
            SET checksum = ?, success = ?
            WHERE script = ?
            """
            params = [checksum, success_value, script_name]

        try:
            affected = self.query_executor.execute_statement(connection, update_sql, params=params)
            affected_count = int(affected) if affected is not None else 0
            if affected_count > 0:
                success_str = "NULL" if success_value is None else str(success_value)
                self.log.debug(
                    f"Migration record repaired in schema {schema}: "
                    f"{script_name} (success={success_str})"
                )
            else:
                self.log.warning(
                    f"No migration record found to repair in schema {schema}: {script_name}"
                )
            return affected_count > 0
        except Exception as e:
            error_msg = f"Error repairing migration record in schema {schema}: {str(e)}"
            self.log.error(error_msg)
            raise

    def delete_failed_migration_entry(
        self,
        connection: Any,
        schema: str,
        script_name: str,
        table_name: Optional[str] = None,
    ) -> int:
        """Delete the failed history row for *script_name*; return rows removed.

        ``repair`` calls this to clear a failed migration so the script can
        be re-applied. Relational backends express it as a parameterised
        ``DELETE``; document stores override this method and delete the
        history document through their SDK, which is why the statement is
        built here rather than in the command.

        Returns the number of rows removed (``0`` when no failed row
        matched), or ``-1`` when the driver reports an unknown row count.
        """
        table_name_to_use = table_name or self._get_default_table_name()
        qualified_table = self.query_executor.get_schema_qualified_name(schema, table_name_to_use)
        false_literal = self._false_literal()

        delete_sql = (
            f"DELETE FROM {qualified_table} " f"WHERE script = ? AND success = {false_literal}"
        )
        affected = self.query_executor.execute_statement(
            connection, delete_sql, params=[script_name]
        )
        return int(affected) if affected is not None else 0

    def _false_literal(self) -> str:
        """Dialect literal for ``False`` in history predicates.

        Resolved from the plugin quirks so no command has to know that
        Oracle/SQL Server/SQLite spell it ``0``.
        """
        dialect = getattr(self.query_executor, "dialect_name", "") or ""
        if not dialect:
            config = getattr(
                getattr(self.query_executor, "connection_manager", None), "config", None
            )
            dialect = str(getattr(getattr(config, "database", None), "type", "") or "")
        return ProviderRegistry.get_quirks(dialect.lower()).boolean_false_literal

    def record_undo(
        self,
        connection: Any,
        schema: str,
        version: str,
        table_name: Optional[str] = None,
        script_name: Optional[str] = None,
    ) -> bool:
        """Record an undo operation in the migration history.

        Default implementation creates a synthetic UNDO_SQL record.
        Database-specific implementations can override for custom behavior.

        Args:
            connection: Active database connection (provided by Provider)
            schema: Schema name
            version: Version being undone
            table_name: Custom history table name
            script_name: Original migration script name, if available

        Returns:
            True if undo was recorded successfully
        """
        try:
            undo_script_name = self._undo_script_name(version, script_name)
            undo_info = {
                "version": version,
                "description": f"Undo migration {version}",
                "type": UNDO_HISTORY_TYPE,
                "script": undo_script_name,
                # ``checksum`` is INT; typed NULL on an INT
                # column breaks PostgreSQL. ``0`` is the existing sentinel for
                # "no checksum".
                "checksum": 0,
                "installed_by": os.environ.get("USER", os.environ.get("USERNAME", "dblift")),
                # No ``installed_on``: ``record_migration`` now binds a supplied
                # value, and a client-side clock here would override the history
                # table's own timestamp default for undo rows.
                "execution_time": 0,
                "success": True,
            }

            self.record_migration(connection, schema, undo_info, table_name)
            self.log.debug(f"Recorded undo operation for version {version} in schema {schema}")
            return True

        except Exception as e:
            self.log.error(f"Error recording undo for version {version}: {str(e)}")
            return False

    def _undo_script_name(self, version: str, script_name: Optional[str] = None) -> str:
        """Return an extension-bearing script name for synthetic undo history rows."""
        if script_name:
            return script_name if os.path.splitext(script_name)[1] else f"{script_name}.sql"
        return f"UNDO_{version}.sql"
