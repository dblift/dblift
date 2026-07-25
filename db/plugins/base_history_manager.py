"""Base abstract class for database history managers."""

import datetime
import os
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from core.logger import Log, NullLog


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
        table_name: str = "dblift_schema_history",
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
        return "dblift_schema_history"

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
            checksum: New checksum value (int for Epic 17 CRC32, str for legacy).
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
        from db.provider_registry import ProviderRegistry

        dialect = getattr(self.query_executor, "dialect_name", "") or ""
        if not dialect:
            config = getattr(
                getattr(self.query_executor, "connection_manager", None), "config", None
            )
            dialect = str(getattr(getattr(config, "database", None), "type", "") or "")
        return ProviderRegistry.get_quirks(dialect.lower()).boolean_false_literal

    def _validate_migration_info(self, migration_info: Dict[str, Any]) -> None:
        """Validate migration information dictionary.

        Args:
            migration_info: Migration information to validate

        Raises:
            ValueError: If required fields are missing
        """
        required_fields = ["version", "description", "type", "script"]
        missing_fields = [field for field in required_fields if field not in migration_info]

        if missing_fields:
            raise ValueError(f"Missing required migration fields: {', '.join(missing_fields)}")

    def _normalize_migration_results(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Normalize migration results to handle database-specific variations.

        This method standardizes column names, data types, and formats across
        different database implementations.

        Args:
            results: Raw migration results from database

        Returns:
            Normalized migration results
        """
        normalized = []

        for result in results:
            normalized_result: Dict[str, Any] = {}

            # Normalize common column names (handle case variations)
            for key, value in result.items():
                normalized_key = key.lower()

                # Handle common column name variations
                if normalized_key in ["installed_rank", "installedrank"]:
                    normalized_result["installed_rank"] = self._to_int(value)
                elif normalized_key in ["version"]:
                    normalized_result["version"] = str(value) if value is not None else None
                elif normalized_key in ["description"]:
                    normalized_result["description"] = str(value) if value is not None else None
                elif normalized_key in ["type"]:
                    normalized_result["type"] = str(value) if value is not None else None
                elif normalized_key in ["script", "script_name", "scriptname"]:
                    normalized_result["script"] = str(value) if value is not None else None
                elif normalized_key in ["checksum"]:
                    normalized_result["checksum"] = str(value) if value is not None else None
                elif normalized_key in ["installed_by", "installedby"]:
                    normalized_result["installed_by"] = str(value) if value is not None else None
                elif normalized_key in ["installed_on", "installedon"]:
                    normalized_result["installed_on"] = self._convert_timestamp(value)
                elif normalized_key in ["execution_time", "executiontime"]:
                    normalized_result["execution_time"] = self._to_int(value)
                elif normalized_key in ["success"]:
                    normalized_result["success"] = self._to_boolean(value)
                else:
                    # Keep other fields as-is
                    normalized_result[normalized_key] = value

            normalized.append(normalized_result)

        return normalized

    def _to_int(self, value: Any) -> int:
        """Convert various numeric types to int safely.

        Handles decimal-like driver values, numeric types, and string representations.

        Args:
            value: Value to convert

        Returns:
            Integer value, 0 if conversion fails
        """
        try:
            if value is None:
                return 0

            # Handle decimal-like driver objects that expose intValue().
            if hasattr(value, "intValue"):
                return int(value.intValue())

            # Handle standard numeric types
            if isinstance(value, (int, float)):
                return int(value)

            # Handle string representations
            str_value = str(value).strip()
            if str_value == "":
                return 0

            # Handle decimal strings
            if "." in str_value:
                return int(float(str_value))

            return int(str_value)

        except (ValueError, TypeError, AttributeError):
            return 0

    def _to_boolean(self, value: Any) -> bool:
        """Convert various types to boolean safely.

        Handles database-specific boolean representations (0/1, true/false, etc.).

        Args:
            value: Value to convert

        Returns:
            Boolean value
        """
        if value is None:
            return False

        # Handle numeric representations
        if isinstance(value, (int, float)):
            return value != 0

        # Handle numeric driver objects.
        if hasattr(value, "intValue"):
            return int(value.intValue()) != 0

        # Handle string representations
        str_value = str(value).lower().strip()
        return str_value in ("true", "1", "yes", "on", "t", "y")

    def _convert_timestamp(self, value: Any) -> Any:
        """Convert database timestamp to Python datetime.

        Handles various database timestamp formats and timestamp-like driver objects.

        Args:
            value: Timestamp value to convert

        Returns:
            Python datetime object or original value if conversion fails
        """
        if value is None:
            return None

        # If it's already a datetime, return as-is
        if isinstance(value, datetime.datetime):
            return value

        # Handle timestamp-like driver objects.
        if hasattr(value, "toLocalDateTime"):
            try:
                # Convert timestamp-like object to Python datetime.
                local_dt = value.toLocalDateTime()
                return datetime.datetime(
                    local_dt.getYear(),
                    local_dt.getMonthValue(),
                    local_dt.getDayOfMonth(),
                    local_dt.getHour(),
                    local_dt.getMinute(),
                    local_dt.getSecond(),
                    local_dt.getNano() // 1000,
                )
            except Exception as e:
                self.log.debug(f"Could not convert database timestamp to datetime: {e}")

        # Return original value if conversion fails
        return value

    def _get_first_value(self, result: Any) -> Any:
        """Get the first value from a database result safely.

        Handles different result formats and extracts the first column value.

        Args:
            result: Database result (dict or list)

        Returns:
            First value or None if not found
        """
        if not result:
            return None

        if isinstance(result, dict):
            # Get first value from dictionary
            return next(iter(result.values())) if result else None

        if isinstance(result, (list, tuple)) and result:
            first_item = result[0]
            if isinstance(first_item, dict):
                # Get first value from first dictionary
                return next(iter(first_item.values())) if first_item else None
            else:
                # Return first item directly
                return first_item

        return None

    def _build_migration_params(
        self, migration_info: Dict[str, Any], success_value: Any
    ) -> List[Any]:
        """Build the standard params list for INSERT INTO history table.

        Extracts and normalises the common fields shared across all database
        dialect implementations of record_migration().  The caller is
        responsible for computing the dialect-specific ``success_value``
        (integer 0/1, boolean, or string "true"/"false") before calling
        this helper.

        Args:
            migration_info: Dictionary containing migration information.
            success_value: Dialect-specific representation of the success flag.

        Returns:
            List of 8 parameter values in standard column order:
            version, description, type, script, checksum,
            installed_by, execution_time, success_value.
        """
        return [
            migration_info.get("version"),
            migration_info.get("description") or "",
            migration_info.get("type") or "SQL",
            migration_info.get("script") or "",
            migration_info.get("checksum"),
            migration_info.get("installed_by") or "unknown",
            migration_info.get("execution_time", 0),
            success_value,
        ]

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
                "type": "UNDO_SQL",
                "script": undo_script_name,
                # Batch-6 BUG-02: ``checksum`` is INT; typed NULL on an INT
                # column breaks PostgreSQL. ``0`` is the existing sentinel for
                # "no checksum".
                "checksum": 0,
                "installed_by": os.environ.get("USER", os.environ.get("USERNAME", "dblift")),
                "installed_on": datetime.datetime.now(),
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

    def migration_exists(
        self, connection: Any, schema: str, version: str, table_name: Optional[str] = None
    ) -> bool:
        """Check if a migration with the given version exists in the history.

        Default implementation queries the history table.
        Database-specific implementations can override for optimization.

        Args:
            schema: Schema name
            version: Migration version to check
            table_name: Custom history table name

        Returns:
            True if migration exists, False otherwise
        """
        try:
            table_name = table_name or self._get_default_table_name()

            if not self.query_executor.table_exists(schema, table_name):
                return False

            qualified_table = self.query_executor.get_schema_qualified_name(schema, table_name)
            query = f"SELECT COUNT(*) as count FROM {qualified_table} WHERE version = ?"

            results = self.query_executor.execute_query(query, [version])
            if results:
                count = self._get_first_value(results)
                return self._to_int(count) > 0

            return False

        except Exception as e:
            self.log.error(f"Error checking if migration {version} exists: {str(e)}")
            return False

    def get_row_limit_clause(self, n: int = 1) -> str:
        """Return SQL clause to limit the number of rows returned.

        Defaults to MySQL/PostgreSQL syntax. Override in dialect-specific history managers.

        Args:
            n: Maximum number of rows to return

        Returns:
            str: SQL LIMIT clause appropriate for this database dialect
        """
        return f"LIMIT {n}"

    def get_current_version(
        self, connection: Any, schema: str, table_name: Optional[str] = None
    ) -> Optional[str]:
        """Get the current schema version from the history table.

        Default implementation finds the highest version number.
        Database-specific implementations can override for custom logic.

        Args:
            schema: Schema name
            table_name: Custom history table name

        Returns:
            Current version string or None if no migrations found
        """
        try:
            table_name = table_name or self._get_default_table_name()

            if not self.query_executor.table_exists(schema, table_name):
                return None

            qualified_table = self.query_executor.get_schema_qualified_name(schema, table_name)
            query = f"""
                SELECT version FROM {qualified_table}
                WHERE type = 'SQL' AND success = TRUE
                ORDER BY installed_rank DESC
                {self.get_row_limit_clause(1)}
            """

            results = self.query_executor.execute_query(query)
            if results:
                version = self._get_first_value(results)
                return str(version) if version is not None else None

            return None

        except Exception as e:
            self.log.error(f"Error getting current version: {str(e)}")
            return None
