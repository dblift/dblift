"""
SQL Server migration history manager.

This module handles SQL Server-specific migration history table operations including
creation, recording migrations, retrieving applied migrations, and repair operations.
"""

import datetime
import os
from typing import Any, Dict, List, Optional, Union, cast

from core.logger import Log
from db.object_naming import get_normalized_object_name
from db.plugins.base_history_manager import (
    UNDO_HISTORY_TYPE,
    VERSIONED_HISTORY_TYPES_SQL_IN,
    BaseHistoryManager,
)


class SqlServerHistoryManager(BaseHistoryManager):
    """Manages SQL Server migration history operations."""

    # SQL Server stores identifiers as specified (case-insensitive by default)
    DEFAULT_HISTORY_TABLE = "dblift_schema_history"

    def __init__(
        self,
        query_executor: Any,
        schema_operations: Any,
        config: Any,
        log: Optional[Log] = None,
    ) -> None:
        """Initialize the history manager.

        Args:
            query_executor: Query executor instance
            schema_operations: Schema operations instance
            config: Configuration object
            log: Optional logger
        """
        super().__init__(query_executor, schema_operations, config, log)

    def create_migration_history_table_if_not_exists(
        self,
        connection: Any,
        schema: str,
        create_schema: bool = False,
        table_name: Optional[str] = None,
    ) -> None:
        """Create the migration history table if it doesn't exist.

        Args:
            schema: Schema name
            create_schema: Whether to create schema if it doesn't exist
            table_name: Custom history table name
        """
        self.log.debug(f"Creating migration history table if not exists: {schema}")

        try:
            if create_schema:
                self.schema_operations.create_schema_if_not_exists(connection, schema)

            raw_table = table_name or getattr(self.config, "history_table", "dblift_schema_history")
            table = get_normalized_object_name(
                str(raw_table) if raw_table is not None else "dblift_schema_history", "sqlserver"
            )

            # Check if table exists
            table_exists = self.query_executor.table_exists(connection, schema, table)
            if table_exists:
                if create_schema:
                    self._check_baseline_safety(connection, schema, table)
                self.log.debug(f"Migration history table {schema}.{table} already exists")
                return

            # Create the table
            qualified_table = self.query_executor.get_schema_qualified_name(schema, table)
            create_sql = f"""
            CREATE TABLE {qualified_table} (
                installed_rank INT IDENTITY(1,1) PRIMARY KEY,
                version NVARCHAR(50),
                description NVARCHAR(200) NOT NULL,
                type NVARCHAR(20) NOT NULL,
                script NVARCHAR(1000) NOT NULL,
                checksum INT,
                installed_by NVARCHAR(100) NOT NULL,
                installed_on DATETIME2 NOT NULL DEFAULT GETDATE(),
                execution_time INT NOT NULL,
                success BIT NOT NULL
            )
            """

            self.query_executor.execute_statement(connection, create_sql)
            self.log.debug(f"Migration history table created successfully in schema {schema}")

        except Exception as e:
            error_msg = f"Error creating migration history table in schema {schema}: {str(e)}"
            self.log.error(error_msg)
            raise

    def record_migration(
        self,
        connection: Any,
        schema: str,
        migration_info: Dict[str, Any],
        table_name: Optional[str] = None,
    ) -> None:
        """Record a migration in the history table.

        Args:
            schema: Schema name
            migration_info: Dictionary containing migration information
            table_name: Custom history table name
        """
        raw_table = table_name or getattr(self.config, "history_table", "dblift_schema_history")
        table = get_normalized_object_name(
            str(raw_table) if raw_table is not None else "dblift_schema_history", "sqlserver"
        )

        if not self.query_executor.table_exists(connection, schema, table):
            self.create_migration_history_table_if_not_exists(connection, schema, True, raw_table)

        try:
            installed_on = migration_info.get("installed_on")
            if installed_on is None:
                installed_on_query = "SELECT GETDATE() as current_time"
                installed_on_result = self.query_executor.execute_query(
                    connection, installed_on_query
                )
                if installed_on_result and len(installed_on_result) > 0:
                    installed_on = installed_on_result[0].get("current_time")

            # For SQL Server, installed_rank is an IDENTITY column, so we don't include it in INSERT
            qualified_table = self.query_executor.get_schema_qualified_name(schema, table)
            insert_sql = f"""
            INSERT INTO {qualified_table} (
                version, description, type, script,
                checksum, installed_by, installed_on, execution_time, success
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """

            if migration_info.get("success") is not None:
                success_value = bool(migration_info.get("success"))
                if (
                    self.log
                    and hasattr(self.log, "is_debug_enabled")
                    and self.log.is_debug_enabled()
                ):
                    self.log.debug(
                        f"Setting success value for migration {migration_info.get('script')}: {success_value}"
                    )
            else:
                success_value = True

            # Don't include next_rank in params since installed_rank is auto-generated
            params = [
                migration_info.get("version"),
                migration_info.get("description") or "",
                migration_info.get("type") or "SQL",
                migration_info.get("script") or "",
                migration_info.get("checksum"),
                migration_info.get("installed_by") or "unknown",
                installed_on,
                migration_info.get("execution_time", 0),
                success_value,
            ]

            self.query_executor.execute_statement(connection, insert_sql, params=params)

            self.log.debug(f"Migration recorded in schema {schema}: {migration_info.get('script')}")
        except Exception as e:
            error_msg = f"Error recording migration in schema {schema}: {str(e)}"
            self.log.error(error_msg)
            raise

    def get_applied_migrations(
        self, connection: Any, schema: str, table_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get list of applied migrations from history table.

        Args:
            schema: Schema name
            table_name: Custom history table name

        Returns:
            List of dictionaries containing migration information
        """
        raw_table = table_name or getattr(self.config, "history_table", "dblift_schema_history")
        table = get_normalized_object_name(
            str(raw_table) if raw_table is not None else "dblift_schema_history", "sqlserver"
        )

        if not self.query_executor.table_exists(connection, schema, table):
            return []

        qualified_table = self.query_executor.get_schema_qualified_name(schema, table)
        query = f"""
        SELECT script, installed_rank, version, description,
               type, checksum, installed_by, installed_on,
               execution_time, success
        FROM {qualified_table}
        ORDER BY installed_rank
        """

        try:
            results = self.query_executor.execute_query(connection, query)
            # Results from execute_query are already normalized; just convert string values.
            normalized_results: List[Dict[str, Any]] = results
            for row in normalized_results:
                if "success" in row:
                    row["success"] = bool(row["success"])
            return normalized_results
        except Exception as exc:
            error_msg = f"Error getting applied migrations from schema {schema}: {str(exc)}"
            self.log.error(error_msg)
            raise

    def record_undo(
        self,
        connection: Any,
        schema: str,
        version: str,
        table_name: Optional[str] = None,
        script_name: Optional[str] = None,
    ) -> bool:
        """Record an undo operation in the migration history.

        Args:
            schema: Schema name
            version: Version being undone
            table_name: Custom history table name
            script_name: Original migration script name, if available

        Returns:
            bool: True on success, False on failure
        """
        try:
            # Fetch the original migration to get description - using database-agnostic approach
            raw_table = table_name or getattr(self.config, "history_table", "dblift_schema_history")
            dblift_table_name = get_normalized_object_name(
                str(raw_table) if raw_table is not None else "dblift_schema_history", "sqlserver"
            )
            qualified_table = self.query_executor.get_schema_qualified_name(
                schema, dblift_table_name
            )
            query = f"""
            SELECT description, installed_rank FROM {qualified_table}
            WHERE version = ? AND type IN {VERSIONED_HISTORY_TYPES_SQL_IN} AND success = 1
            ORDER BY installed_rank DESC
            """
            results = self.query_executor.execute_query(connection, query, params=[version])
            if not results or len(results) == 0:
                self.log.warning(
                    f"No successful versioned migration found with version {version} in schema {schema}"
                )
                return False

            description = results[0].get("description", "unknown")
            script_name = f"U{version}__{description}.sql"
            undo_info = {
                "script": script_name,
                "version": version,
                "description": description,
                "type": UNDO_HISTORY_TYPE,
                # Batch-6 BUG-02: typed NULL on an INT column fails on strict
                # drivers; ``0`` is the existing sentinel for "no checksum".
                "checksum": 0,
                "success": True,
                "execution_time": 0,
                "installed_on": datetime.datetime.now(),
                "installed_by": os.environ.get("USER", os.environ.get("USERNAME", "unknown")),
            }
            self.record_migration(connection, schema, undo_info, table_name)
            return True
        except Exception as e:
            self.log.error(f"Error recording undo for version {version}: {str(e)}")
            return False

    def repair_migration_history(
        self,
        connection: Any,
        schema: str,
        script_name: str,
        checksum: Union[int, str],
        success_value: Optional[bool] = None,
        table_name: Optional[str] = None,
    ) -> bool:
        """Repair a migration record in the history table.

        Args:
            schema: Schema name
            script_name: Script name to repair
            checksum: New checksum value
            success_value: Success status
            table_name: Custom history table name
        Returns:
            bool: True if a history row was updated, False otherwise.
        """
        raw_table = table_name or getattr(self.config, "history_table", "dblift_schema_history")
        table = get_normalized_object_name(
            str(raw_table) if raw_table is not None else "dblift_schema_history", "sqlserver"
        )

        # Build update SQL
        qualified_table = self.query_executor.get_schema_qualified_name(schema, table)
        if success_value is None:
            # Mark as failed (0) — success is NOT NULL since story 17-3; NULL is no longer valid
            update_sql = f"""
            UPDATE {qualified_table}
            SET checksum = ?, success = 0
            WHERE script = ?
            """
            params: List[Any] = [checksum, script_name]
        else:
            # Repair with explicit success value
            update_sql = f"""
            UPDATE {qualified_table}
            SET checksum = ?, success = ?
            WHERE script = ?
            """
            params = [checksum, success_value, script_name]

        try:
            affected_rows = cast(
                int, self.query_executor.execute_statement(connection, update_sql, params=params)
            )
            if affected_rows > 0:
                success_str = "NULL" if success_value is None else str(success_value)
                self.log.debug(
                    f"Migration record repaired in schema {schema}: {script_name} (success={success_str})"
                )
            else:
                self.log.warning(
                    f"No migration record found to repair in schema {schema}: {script_name}"
                )
            return affected_rows > 0
        except Exception as e:
            error_msg = f"Error repairing migration record in schema {schema}: {str(e)}"
            self.log.error(error_msg)
            raise

    def create_history_table(self, schema: str, table_name: str) -> str:
        """Generate the SQL to create a migration history table.

        Args:
            schema: Schema name
            table_name: Table name

        Returns:
            str: SQL for creating the history table
        """
        dblift_table_name = get_normalized_object_name(table_name, "sqlserver")
        qualified_table = self.query_executor.get_schema_qualified_name(schema, dblift_table_name)
        return f"""
        CREATE TABLE {qualified_table} (
            installed_rank INT IDENTITY(1,1) PRIMARY KEY,
            version NVARCHAR(50),
            description NVARCHAR(200) NOT NULL,
            type NVARCHAR(20) NOT NULL,
            script NVARCHAR(1000) NOT NULL,
            checksum INT,
            installed_by NVARCHAR(100) NOT NULL,
            installed_on DATETIME2 NOT NULL DEFAULT GETDATE(),
            execution_time INT NOT NULL,
            success BIT NOT NULL
        )
        """

    def _get_first_value(self, result: Any) -> Any:
        """Get the first value from the first row of a query result.

        Args:
            result: The result from execute_query

        Returns:
            The first value in the first row, or None if result is empty
        """
        if not result or len(result) == 0:
            return None

        # Get the first row
        first_row = result[0]

        # Extract the first value from the dictionary
        return list(first_row.values())[0] if first_row else None
