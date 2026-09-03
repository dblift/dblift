"""
MySQL schema operations and metadata queries.

This module handles MySQL-specific schema operations including database creation,
cleaning, and metadata queries for tables, columns, and other database objects.
"""

from typing import Any, List, Optional

from dblift.core.logger import Log, NullLog
from dblift.core.migration.clean_summary import CleanExecutionSummary
from dblift.db.plugins.base_schema_operations import BaseSchemaOperations


class MySqlSchemaOperations(BaseSchemaOperations):
    """Handles MySQL schema operations and metadata queries."""

    def __init__(self, query_executor: Any, log: Optional[Log] = None) -> None:
        """Initialize the schema operations manager.

        Args:
            query_executor: Query executor instance
            log: Optional logger
        """
        self.query_executor: Any = query_executor
        self.log: Log = log if log is not None else NullLog()

    def create_schema_if_not_exists(self, connection: Any, schema: str) -> None:
        """Create a database if it doesn't exist in MySQL.

        Args:
            connection: Active database connection (provided by Provider)
            schema: Database name to create (MySQL uses databases instead of schemas)
        """
        self.log.info(f"Creating database if not exists: {schema}")

        # MySQL uses CREATE DATABASE instead of CREATE SCHEMA
        # Check if database exists using information_schema
        check_sql = """
        SELECT SCHEMA_NAME
        FROM information_schema.SCHEMATA
        WHERE SCHEMA_NAME = ?
        """
        database_exists = (
            len(self.query_executor.execute_query(connection, check_sql, [schema])) > 0
        )

        if not database_exists:
            # Route through the centralized quoted-schema helper (which picks
            # backtick quoting for MySQL via _identifier_quote_chars()) so every
            # dblift SQL construction site references schemas identically.
            quoted_schema = self.query_executor.get_quoted_schema_name(schema)
            create_sql = f"CREATE DATABASE IF NOT EXISTS {quoted_schema}"
            self.query_executor.execute_statement(connection, create_sql)
            # OBS-03: warn so a typo in --db-schema is loud, not silent.
            self.log.warning(
                f"Database '{schema}' did not exist — created automatically. "
                "Check for typos in --db-schema."
            )
        else:
            self.log.debug(f"Database already exists: {schema}")

        # Always set the current database to ensure we're using it
        self.set_current_schema(connection, schema)

    def set_current_schema(self, connection: Any, schema: str) -> None:
        """Set the current database for the connection.

        Args:
            connection: Active database connection (provided by Provider)
            schema: Database name (MySQL uses USE statement)
        """
        self.log.debug(f"Setting current database to: {schema}")

        quoted_schema = self.query_executor.get_quoted_schema_name(schema)
        use_sql = f"USE {quoted_schema}"
        try:
            self.query_executor.execute_statement(connection, use_sql)
            self.log.debug(f"Current database set to: {schema}")
        except Exception as e:
            error_msg = f"Failed to set current database: {str(e)}"
            self.log.warning(error_msg)
            raise

    def get_database_version(self, connection: Any) -> str:
        """Get the MySQL version information.

        Args:
            connection: Active database connection (provided by Provider)

        Returns:
            Database version string
        """
        try:
            # Query MySQL version using VERSION() function
            version_sql = "SELECT VERSION() as version"
            results = self.query_executor.execute_query(connection, version_sql)

            if results and len(results) > 0:
                version = results[0].get("version", "Unknown")
                return f"MySQL {version}"

            return "MySQL Unknown Version"
        except Exception as e:
            self.log.warning(f"Error getting MySQL version: {str(e)}")
            return "MySQL Unknown Version"

    def clean_schema(self, connection: Any, schema: str) -> CleanExecutionSummary:
        """Clean a MySQL database by dropping all objects in the correct order.

        Args:
            connection: Active database connection (provided by Provider)
            schema: Database name

        Returns:
            CleanExecutionSummary describing executed statements and dropped objects.
        """
        self.log.info(f"Cleaning MySQL database: {schema}")

        summary = CleanExecutionSummary()

        # Set current database
        self.set_current_schema(connection, schema)

        try:
            # Disable foreign key checks to avoid dependency issues
            try:
                disable_fk_sql = "SET FOREIGN_KEY_CHECKS = 0"
                self.query_executor.execute_statement(connection, disable_fk_sql)
                summary.add_statement(disable_fk_sql)
                self.log.debug("Disabled foreign key checks")
            except Exception as e:
                self.log.warning(f"Failed to disable foreign key checks: {str(e)}")

            # 1. Drop triggers first
            self._drop_triggers(connection, schema, summary)

            # 2. Drop views
            self._drop_views(connection, schema, summary)

            # 3. Drop tables (except history table)
            self._drop_tables(connection, schema, summary)

            # 4. Drop functions
            self._drop_functions(connection, schema, summary)

            # 5. Drop procedures
            self._drop_procedures(connection, schema, summary)

            # 6. Drop events (MySQL-specific)
            self._drop_events(connection, schema, summary)

            # Re-enable foreign key checks
            try:
                enable_fk_sql = "SET FOREIGN_KEY_CHECKS = 1"
                self.query_executor.execute_statement(connection, enable_fk_sql)
                summary.add_statement(enable_fk_sql)
                self.log.debug("Re-enabled foreign key checks")
            except Exception as e:
                self.log.warning(f"Failed to re-enable foreign key checks: {str(e)}")

            # CRITICAL: Commit cleanup operations for MySQL to prevent hanging
            # MySQL DDL operations need explicit commit when autoCommit=False
            try:
                if hasattr(connection, "commit"):
                    if hasattr(connection, "getAutoCommit"):
                        if not connection.getAutoCommit():
                            connection.commit()
                            self.log.debug("Committed MySQL cleanup transaction")
                    else:
                        # If we can't check autoCommit, commit anyway for safety
                        connection.commit()
                        self.log.debug("Committed MySQL cleanup transaction (autoCommit unknown)")
            except Exception as commit_err:
                self.log.warning(f"Failed to commit cleanup transaction: {commit_err}")
                # Try rollback if commit fails
                try:
                    if hasattr(connection, "rollback"):
                        connection.rollback()
                        self.log.debug("Rolled back MySQL cleanup transaction after commit failure")
                except Exception as rb_e:
                    self.log.debug(f"Could not rollback MySQL cleanup transaction: {rb_e}")

            self.log.info(
                f"Database cleanup completed. Executed {len(summary.statements)} statements."
            )

            return summary

        except Exception as e:
            error_msg = f"Error cleaning database {schema}: {str(e)}"
            self.log.error(error_msg)
            raise

    def get_clean_preview(self, connection: Any, schema: str) -> CleanExecutionSummary:
        """Return the objects a MySQL clean would drop, without executing the DROPs.

        BUG-03: dry-run must mirror ``clean_schema`` exactly so the user sees
        every object that will be dropped, including dblift-internal tables
        (history / lock). Enumerates the same six kinds
        ``clean_schema`` processes: triggers, views, tables, functions,
        procedures, events.
        """
        summary = CleanExecutionSummary()

        # Triggers
        self._enumerate_objects_by_type(
            connection,
            "trigger",
            "SELECT TRIGGER_NAME FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA = ?",
            [schema],
            "TRIGGER_NAME",
            lambda n: (
                f"DROP TRIGGER IF EXISTS "
                f"{self.query_executor.get_schema_qualified_name(schema, n)}"
            ),
            summary,
            schema=schema,
        )

        # Views
        self._enumerate_objects_by_type(
            connection,
            "view",
            "SELECT TABLE_NAME FROM information_schema.VIEWS WHERE TABLE_SCHEMA = ?",
            [schema],
            "TABLE_NAME",
            lambda n: (
                f"DROP VIEW IF EXISTS "
                f"{self.query_executor.get_schema_qualified_name(schema, n)}"
            ),
            summary,
            schema=schema,
        )

        # Tables
        self._enumerate_objects_by_type(
            connection,
            "table",
            (
                "SELECT TABLE_NAME FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = ? AND TABLE_TYPE = 'BASE TABLE'"
            ),
            [schema],
            "TABLE_NAME",
            lambda n: (
                f"DROP TABLE IF EXISTS "
                f"{self.query_executor.get_schema_qualified_name(schema, n)}"
            ),
            summary,
            schema=schema,
        )

        # Functions
        self._enumerate_objects_by_type(
            connection,
            "function",
            (
                "SELECT ROUTINE_NAME FROM information_schema.ROUTINES "
                "WHERE ROUTINE_SCHEMA = ? AND ROUTINE_TYPE = 'FUNCTION'"
            ),
            [schema],
            "ROUTINE_NAME",
            lambda n: (
                f"DROP FUNCTION IF EXISTS "
                f"{self.query_executor.get_schema_qualified_name(schema, n)}"
            ),
            summary,
            schema=schema,
        )

        # Procedures
        self._enumerate_objects_by_type(
            connection,
            "procedure",
            (
                "SELECT ROUTINE_NAME FROM information_schema.ROUTINES "
                "WHERE ROUTINE_SCHEMA = ? AND ROUTINE_TYPE = 'PROCEDURE'"
            ),
            [schema],
            "ROUTINE_NAME",
            lambda n: (
                f"DROP PROCEDURE IF EXISTS "
                f"{self.query_executor.get_schema_qualified_name(schema, n)}"
            ),
            summary,
            schema=schema,
        )

        # Events
        self._enumerate_objects_by_type(
            connection,
            "event",
            "SELECT EVENT_NAME FROM information_schema.EVENTS WHERE EVENT_SCHEMA = ?",
            [schema],
            "EVENT_NAME",
            lambda n: (
                f"DROP EVENT IF EXISTS "
                f"{self.query_executor.get_schema_qualified_name(schema, n)}"
            ),
            summary,
            schema=schema,
        )

        return summary

    def _drop_triggers(self, connection: Any, schema: str, summary: CleanExecutionSummary) -> None:
        """Drop all triggers in the database."""
        triggers_query = """
        SELECT TRIGGER_NAME
        FROM information_schema.TRIGGERS
        WHERE TRIGGER_SCHEMA = ?
        """
        self._drop_objects_by_type(
            connection,
            "trigger",
            triggers_query,
            [schema],
            "TRIGGER_NAME",
            lambda n: (
                f"DROP TRIGGER IF EXISTS "
                f"{self.query_executor.get_schema_qualified_name(schema, n)}"
            ),
            summary,
            schema=schema,
        )

    def _drop_views(self, connection: Any, schema: str, summary: CleanExecutionSummary) -> None:
        """Drop all views in the database."""
        views_query = """
        SELECT TABLE_NAME
        FROM information_schema.VIEWS
        WHERE TABLE_SCHEMA = ?
        """
        self._drop_objects_by_type(
            connection,
            "view",
            views_query,
            [schema],
            "TABLE_NAME",
            lambda n: (
                f"DROP VIEW IF EXISTS "
                f"{self.query_executor.get_schema_qualified_name(schema, n)}"
            ),
            summary,
            schema=schema,
        )

    def _drop_tables(self, connection: Any, schema: str, summary: CleanExecutionSummary) -> None:
        """Drop all tables in the database (excluding migration lock table)."""
        tables_query = """
        SELECT TABLE_NAME
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = ? AND TABLE_TYPE = 'BASE TABLE'
        """
        self._drop_objects_by_type(
            connection,
            "table",
            tables_query,
            [schema],
            "TABLE_NAME",
            lambda n: (
                f"DROP TABLE IF EXISTS "
                f"{self.query_executor.get_schema_qualified_name(schema, n)}"
            ),
            summary,
            schema=schema,
            # OBS-04: lock table is dropped during clean; lock manager
            # auto-recreates it on the next acquire_migration_lock call.
        )

    def _drop_functions(self, connection: Any, schema: str, summary: CleanExecutionSummary) -> None:
        """Drop all functions in the database."""
        functions_query = """
        SELECT ROUTINE_NAME
        FROM information_schema.ROUTINES
        WHERE ROUTINE_SCHEMA = ? AND ROUTINE_TYPE = 'FUNCTION'
        """
        self._drop_objects_by_type(
            connection,
            "function",
            functions_query,
            [schema],
            "ROUTINE_NAME",
            lambda n: (
                f"DROP FUNCTION IF EXISTS "
                f"{self.query_executor.get_schema_qualified_name(schema, n)}"
            ),
            summary,
            schema=schema,
        )

    def _drop_procedures(
        self, connection: Any, schema: str, summary: CleanExecutionSummary
    ) -> None:
        """Drop all procedures in the database."""
        procedures_query = """
        SELECT ROUTINE_NAME
        FROM information_schema.ROUTINES
        WHERE ROUTINE_SCHEMA = ? AND ROUTINE_TYPE = 'PROCEDURE'
        """
        self._drop_objects_by_type(
            connection,
            "procedure",
            procedures_query,
            [schema],
            "ROUTINE_NAME",
            lambda n: (
                f"DROP PROCEDURE IF EXISTS "
                f"{self.query_executor.get_schema_qualified_name(schema, n)}"
            ),
            summary,
            schema=schema,
        )

    def _drop_events(self, connection: Any, schema: str, summary: CleanExecutionSummary) -> None:
        """Drop all events in the database (MySQL-specific)."""
        events_query = """
        SELECT EVENT_NAME
        FROM information_schema.EVENTS
        WHERE EVENT_SCHEMA = ?
        """
        try:
            self._drop_objects_by_type(
                connection,
                "event",
                events_query,
                [schema],
                "EVENT_NAME",
                lambda n: (
                    f"DROP EVENT IF EXISTS "
                    f"{self.query_executor.get_schema_qualified_name(schema, n)}"
                ),
                summary,
                schema=schema,
            )
        except Exception as e:
            self.log.warning(f"Error checking for events: {str(e)}")

    def get_columns_query(self, schema: str, table: str) -> str:
        """Get a MySQL-specific query to retrieve column information from a table.

        Args:
            schema: Database name
            table: Table name

        Returns:
            str: SQL query to get column information
        """
        return f"""
        SELECT COLUMN_NAME as column_name, DATA_TYPE as data_type,
               COLUMN_TYPE as column_type
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = '{schema}' AND TABLE_NAME = '{table}'
        ORDER BY ORDINAL_POSITION
        """

    def get_add_column_sql(self, schema: str, table: str, column: str, type_def: str) -> str:
        """Generate MySQL-specific SQL to add a column to a table.

        Args:
            schema: Database name
            table: Table name
            column: Column name to add
            type_def: Column data type definition

        Returns:
            str: SQL for adding the column
        """
        qualified_table = self.query_executor.get_schema_qualified_name(schema, table)
        return f"ALTER TABLE {qualified_table} ADD COLUMN `{column}` {type_def}"

    def get_parameter_placeholders(self, count: int) -> str:
        """Get MySQL-specific parameter placeholders for prepared statements.

        Args:
            count: Number of parameters

        Returns:
            str: Parameter placeholders string
        """
        # MySQL uses ? placeholders
        return ", ".join(["?" for _ in range(count)])

    def get_tables(self, connection: Any, schema: str) -> List[str]:
        """Get list of table names in the specified database.

        Args:
            connection: Active database connection (provided by Provider)
            schema: Database name

        Returns:
            List of table names in the database
        """
        self.log.debug(f"Getting tables in database: {schema}")

        try:
            # Use information_schema to get table names
            query = """
            SELECT TABLE_NAME as table_name
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = ? AND TABLE_TYPE = 'BASE TABLE'
            ORDER BY TABLE_NAME
            """

            result = self.query_executor.execute_query(connection, query, params=[schema])
            tables = [
                str(row["table_name"] if "table_name" in row else row["TABLE_NAME"])
                for row in result
            ]

            self.log.debug(f"Found {len(tables)} tables in database {schema}: {tables}")

            return tables
        except Exception as e:
            error_msg = f"Error getting tables in database {schema}: {str(e)}"
            self.log.error(error_msg)
            return []

    def get_schemas(self, connection: Any) -> List[str]:
        """Get list of database names available in the MySQL server.

        Args:
            connection: Active database connection (provided by Provider)

        Returns:
            List of database names that the current user can access
        """
        self.log.debug("Getting available databases from MySQL")

        try:
            # Query to get databases that the current user can access
            # Exclude system databases
            query = """
            SELECT SCHEMA_NAME as schema_name
            FROM information_schema.SCHEMATA
            WHERE SCHEMA_NAME NOT IN (
                'information_schema', 'performance_schema', 'mysql', 'sys'
            )
            ORDER BY SCHEMA_NAME
            """

            result = self.query_executor.execute_query(connection, query)
            schemas = [
                str(row["schema_name"] if "schema_name" in row else row["SCHEMA_NAME"])
                for row in result
            ]

            self.log.debug(f"Found {len(schemas)} accessible databases")

            return schemas
        except Exception as e:
            error_msg = f"Error getting databases: {str(e)}"
            self.log.error(error_msg)
            return []
