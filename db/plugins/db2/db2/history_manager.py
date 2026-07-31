"""
DB2 migration history manager.

This module handles DB2-specific migration history table operations including
creation, recording migrations, retrieving applied migrations, and repair operations.
"""

from typing import Any, Dict, List, Optional

from core.logger import Log
from db.object_naming import get_normalized_object_name
from db.plugins.base_history_manager import BaseHistoryManager


class Db2HistoryManager(BaseHistoryManager):
    """Manages DB2 migration history operations."""

    # DB2 stores unquoted identifiers as UPPERCASE
    DEFAULT_HISTORY_TABLE = "DBLIFT_SCHEMA_HISTORY"

    def _get_default_table_name(self) -> str:
        """Return the default history table name in DB2's native UPPERCASE."""
        return self.DEFAULT_HISTORY_TABLE

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
        table_name: str = "DBLIFT_SCHEMA_HISTORY",
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

            # Use database-specific default case for dblift objects
            dblift_table_name = get_normalized_object_name(table_name, "db2")

            # Check if table exists
            table_exists = self.query_executor.table_exists(connection, schema, dblift_table_name)
            if table_exists:
                if create_schema:
                    self._check_baseline_safety(connection, schema, dblift_table_name)
                self.log.debug(
                    f"Migration history table {schema}.{dblift_table_name} already exists"
                )
                return

            # Create the table with DB2-specific syntax and data types
            # Use quoted identifiers to preserve case
            qualified_table = self.query_executor.get_schema_qualified_name(
                schema, dblift_table_name
            )
            create_sql = f"""
            CREATE TABLE {qualified_table} (
                installed_rank INTEGER NOT NULL GENERATED ALWAYS AS IDENTITY,
                version VARCHAR(50),
                description VARCHAR(200) NOT NULL,
                type VARCHAR(20) NOT NULL,
                script VARCHAR(1000) NOT NULL,
                checksum INTEGER,
                installed_by VARCHAR(100) NOT NULL,
                installed_on TIMESTAMP NOT NULL DEFAULT CURRENT TIMESTAMP,
                execution_time INTEGER NOT NULL,
                success SMALLINT NOT NULL,
                PRIMARY KEY (installed_rank)
            )
            """

            self.query_executor.execute_statement(connection, create_sql)

            # CRITICAL: Commit table creation immediately (DB2 uses autoCommit=False)
            try:
                connection.commit()
                self.log.debug("Committed history table creation")
            except Exception as commit_e:
                self.log.warning(f"Could not commit history table creation: {commit_e}")

            self.log.debug(f"Migration history table created successfully in schema {schema}")

        except Exception as e:
            # Rollback on error
            try:
                connection.rollback()
            except Exception as rb_e:
                self.log.debug(f"Could not rollback DB2 history table creation transaction: {rb_e}")
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
            connection: Active database connection (provided by Provider)
            schema: Schema name
            migration_info: Dictionary containing migration information
            table_name: Custom history table name
        """
        raw_table = table_name or "DBLIFT_SCHEMA_HISTORY"

        # Use database-specific default case for dblift objects
        table = get_normalized_object_name(raw_table, "db2")

        if not self.query_executor.table_exists(connection, schema, table):
            self.create_migration_history_table_if_not_exists(connection, schema, True, raw_table)

        try:
            # DB2 uses IDENTITY columns for auto-increment, no manual rank calculation needed
            qualified_table = self.query_executor.get_schema_qualified_name(schema, table)
            insert_sql = f"""
            INSERT INTO {qualified_table} (
                version, description, type, script,
                checksum, installed_by, installed_on, execution_time, success
            ) VALUES (?, ?, ?, ?, ?, ?, CURRENT TIMESTAMP, ?, ?)
            """

            # Convert boolean success to SMALLINT (DB2 doesn't have native BOOLEAN)
            success_value = 1 if migration_info.get("success", True) else 0

            params = self._build_migration_params(migration_info, success_value)

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
            connection: Active database connection (provided by Provider)
            schema: Schema name
            table_name: Custom history table name

        Returns:
            List of dictionaries containing migration information
        """
        raw_table = table_name or "DBLIFT_SCHEMA_HISTORY"

        # Use database-specific default case for dblift objects
        table = get_normalized_object_name(raw_table, "db2")

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
            results: List[Dict[str, Any]] = self.query_executor.execute_query(connection, query)

            # Convert SMALLINT success values to boolean
            for row in results:
                if "success" in row and row["success"] is not None:
                    row["success"] = bool(row["success"])

            return results
        except Exception as exc:
            error_msg = f"Error getting applied migrations from schema {schema}: {str(exc)}"
            self.log.error(error_msg)
            raise

    def create_history_table(self, schema: str, table_name: str) -> str:
        """Generate the SQL to create a migration history table.

        Args:
            schema: Schema name
            table_name: Table name

        Returns:
            str: SQL for creating the history table with DB2-specific data types
        """
        # Use database-specific default case for dblift objects
        dblift_table_name = get_normalized_object_name(table_name, "db2")
        qualified_table = self.query_executor.get_schema_qualified_name(schema, dblift_table_name)
        return f"""
        CREATE TABLE {qualified_table} (
            installed_rank INTEGER NOT NULL GENERATED ALWAYS AS IDENTITY,
            version VARCHAR(50),
            description VARCHAR(200) NOT NULL,
            type VARCHAR(20) NOT NULL,
            script VARCHAR(1000) NOT NULL,
            checksum INTEGER,
            installed_by VARCHAR(100) NOT NULL,
            installed_on TIMESTAMP NOT NULL DEFAULT CURRENT TIMESTAMP,
            execution_time INTEGER NOT NULL,
            success SMALLINT NOT NULL,
            PRIMARY KEY (installed_rank)
        )
        """

    def get_current_version(
        self, connection: Any, schema: str, table_name: Optional[str] = None
    ) -> Optional[str]:
        """Get the current schema version from the history table.

        Args:
            connection: Active database connection (provided by Provider)
            schema: Schema name
            table_name: Custom history table name

        Returns:
            Current version string or None if no migrations applied
        """
        raw_table = table_name or "DBLIFT_SCHEMA_HISTORY"

        # Use database-specific default case for dblift objects
        table = get_normalized_object_name(raw_table, "db2")

        if not self.query_executor.table_exists(connection, schema, table):
            return None

        try:
            # Get the latest successful migration version
            qualified_table = self.query_executor.get_schema_qualified_name(schema, table)
            query = f"""
            SELECT version
            FROM {qualified_table}
            WHERE success = 1 AND type != 'DELETE'
            ORDER BY installed_rank DESC
            FETCH FIRST 1 ROWS ONLY
            """

            results: List[Dict[str, Any]] = self.query_executor.execute_query(connection, query)

            if results and len(results) > 0:
                return results[0].get("version")

            return None

        except Exception as e:
            error_msg = f"Error getting current version from schema {schema}: {str(e)}"
            self.log.error(error_msg)
            return None
