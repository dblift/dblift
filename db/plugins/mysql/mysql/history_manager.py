"""
MySQL migration history manager.

This module handles MySQL-specific migration history table operations including
creation, recording migrations, retrieving applied migrations, and repair operations.
"""

from typing import Any, Dict, List, Optional

from core.logger import Log
from db.object_naming import get_normalized_object_name
from db.plugins.base_history_manager import BaseHistoryManager


class MySqlHistoryManager(BaseHistoryManager):
    """Manages MySQL migration history operations."""

    # MySQL stores identifiers as-is (case-sensitive on Linux, insensitive on Windows)
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
            config: Configuration object (reserved; not used by this implementation)
            log: Optional logger
        """
        super().__init__(query_executor, schema_operations, config, log)

    def create_migration_history_table_if_not_exists(
        self,
        connection: Any,
        schema: str,
        create_schema: bool = False,
        table_name: str = "dblift_schema_history",
    ) -> None:
        """Create the migration history table if it doesn't exist.

        Args:
            connection: Active database connection (provided by Provider)
            schema: Database name
            create_schema: Whether to create database if it doesn't exist
            table_name: Custom history table name
        """
        self.log.debug(f"Creating migration history table if not exists: {schema}")

        try:
            if create_schema:
                self.schema_operations.create_schema_if_not_exists(connection, schema)

            # Get database-specific case for dblift object
            dblift_table_name = get_normalized_object_name(table_name, "mysql")

            # Check if table exists
            table_exists = self.query_executor.table_exists(connection, schema, dblift_table_name)
            if table_exists:
                if create_schema:
                    self._check_baseline_safety(connection, schema, dblift_table_name)
                self.log.debug(
                    f"Migration history table {schema}.{dblift_table_name} already exists"
                )
                return

            # Create the table with MySQL-specific syntax and data types
            qualified_table = self.query_executor.get_schema_qualified_name(
                schema, dblift_table_name
            )
            create_sql = f"""
            CREATE TABLE {qualified_table} (
                installed_rank INT NOT NULL AUTO_INCREMENT,
                version VARCHAR(50),
                description VARCHAR(200) NOT NULL,
                type VARCHAR(20) NOT NULL,
                script VARCHAR(1000) NOT NULL,
                checksum INT,
                installed_by VARCHAR(100) NOT NULL,
                installed_on TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                execution_time INT NOT NULL,
                success BOOLEAN NOT NULL,
                PRIMARY KEY (installed_rank)
            ) ENGINE=InnoDB
            """

            self.query_executor.execute_statement(connection, create_sql)
            self.log.debug(f"Migration history table created successfully in database {schema}")

        except Exception as e:
            error_msg = f"Error creating migration history table in database {schema}: {str(e)}"
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
            schema: Database name
            migration_info: Dictionary containing migration information
            table_name: Custom history table name
        """
        raw_table = table_name or "dblift_schema_history"
        table = get_normalized_object_name(raw_table, "mysql")

        if not self.query_executor.table_exists(connection, schema, table):
            self.create_migration_history_table_if_not_exists(connection, schema, True, raw_table)

        try:
            # MySQL uses AUTO_INCREMENT for installed_rank, no manual calculation needed
            qualified_table = self.query_executor.get_schema_qualified_name(schema, table)
            insert_sql = f"""
            INSERT INTO {qualified_table} (
                version, description, type, script,
                checksum, installed_by, installed_on, execution_time, success
            ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?)
            """

            # MySQL supports native BOOLEAN type
            success_value = bool(migration_info.get("success", True))

            params = self._build_migration_params(migration_info, success_value)

            self.query_executor.execute_statement(connection, insert_sql, params=params)

            self.log.debug(
                f"Migration recorded in database {schema}: {migration_info.get('script')}"
            )
        except Exception as e:
            error_msg = f"Error recording migration in database {schema}: {str(e)}"
            self.log.error(error_msg)
            raise

    def get_applied_migrations(
        self, connection: Any, schema: str, table_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get list of applied migrations from history table.

        Args:
            connection: Active database connection (provided by Provider)
            schema: Database name
            table_name: Custom history table name

        Returns:
            List of dictionaries containing migration information
        """
        raw_table = table_name or "dblift_schema_history"
        table = get_normalized_object_name(raw_table, "mysql")

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

            # MySQL returns proper boolean values, but ensure consistency
            for row in results:
                if "success" in row and row["success"] is not None:
                    row["success"] = bool(row["success"])

            return results
        except Exception as exc:
            error_msg = f"Error getting applied migrations from database {schema}: {str(exc)}"
            self.log.error(error_msg)
            raise

    def create_history_table(self, schema: str, table_name: str) -> str:
        """Generate the SQL to create a migration history table.

        Args:
            schema: Database name
            table_name: Table name

        Returns:
            str: SQL for creating the history table with MySQL-specific data types
        """
        dblift_table_name = get_normalized_object_name(table_name, "mysql")
        qualified_table = self.query_executor.get_schema_qualified_name(schema, dblift_table_name)
        return f"""
        CREATE TABLE {qualified_table} (
            installed_rank INT NOT NULL AUTO_INCREMENT,
            version VARCHAR(50),
            description VARCHAR(200) NOT NULL,
            type VARCHAR(20) NOT NULL,
            script VARCHAR(1000) NOT NULL,
            checksum INT,
            installed_by VARCHAR(100) NOT NULL,
            installed_on TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            execution_time INT NOT NULL,
            success BOOLEAN NOT NULL,
            PRIMARY KEY (installed_rank)
        ) ENGINE=InnoDB
        """

    def get_current_version(
        self, connection: Any, schema: str, table_name: Optional[str] = None
    ) -> Optional[str]:
        """Get the current schema version from the history table.

        Args:
            connection: Active database connection (provided by Provider)
            schema: Database name
            table_name: Custom history table name

        Returns:
            Current version string or None if no migrations applied
        """
        raw_table = table_name or "dblift_schema_history"
        table = get_normalized_object_name(raw_table, "mysql")

        if not self.query_executor.table_exists(connection, schema, table):
            return None

        try:
            # Get the latest successful migration version
            qualified_table = self.query_executor.get_schema_qualified_name(schema, table)
            query = f"""
            SELECT version
            FROM {qualified_table}
            WHERE success = TRUE AND type != 'DELETE'
            ORDER BY installed_rank DESC
            LIMIT 1
            """

            results: List[Dict[str, Any]] = self.query_executor.execute_query(connection, query)

            if results and len(results) > 0:
                return results[0].get("version")

            return None

        except Exception as e:
            error_msg = f"Error getting current version from database {schema}: {str(e)}"
            self.log.error(error_msg)
            return None
