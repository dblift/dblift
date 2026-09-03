"""
SQLite query execution and result processing.

This module handles SQL execution, parameter binding, and result set conversion
for SQLite operations using Python's native sqlite3 module.
"""

import sqlite3
from typing import Any, Dict, List, Optional

from dblift.core.logger import Log, NullLog


class SQLiteQueryExecutor:
    """Handles SQLite query execution and result processing."""

    def __init__(self, connection_manager: Any, log: Optional[Log] = None) -> None:
        """Initialize the query executor.

        Args:
            connection_manager: Connection manager instance
            log: Optional logger
        """
        self.connection_manager: Any = connection_manager
        self.log: Log = log if log is not None else NullLog()

    def execute_statement(
        self,
        connection: sqlite3.Connection,
        sql: str,
        params: Optional[List[Any]] = None,
        return_generated_keys: bool = False,
    ) -> int:
        """Execute a SQL statement (INSERT, UPDATE, DELETE) and return affected rows.

        Args:
            connection: Active SQLite connection (provided by Provider)
            sql: SQL statement to execute
            params: Optional parameters for statement
            return_generated_keys: Whether to return generated keys

        Returns:
            int: Number of affected rows, or generated key value if requested

        Raises:
            RuntimeError: If connection is None
        """
        self._validate_connection(connection)

        self.log.debug(f"Executing statement: {sql[:200]}...")

        try:
            cursor = connection.cursor()

            if params:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)

            affected_rows = cursor.rowcount

            if return_generated_keys:
                # Return the last inserted row id
                return cursor.lastrowid or affected_rows

            return affected_rows if affected_rows >= 0 else 0

        except Exception as e:
            error_msg = f"Error executing SQL statement: {str(e)}"
            self.log.error(error_msg)
            self.log.error(f"SQL: {sql}")
            if params:
                self.log.error(f"Parameters: {params}")
            raise

    def execute_query(
        self, connection: sqlite3.Connection, sql: str, params: Optional[List[Any]] = None
    ) -> List[Dict[str, Any]]:
        """Execute a SELECT query and return results as list of dictionaries.

        Args:
            connection: Active SQLite connection (provided by Provider)
            sql: SQL query to execute
            params: Optional parameters for statement

        Returns:
            List[Dict[str, Any]]: Query results
        """
        self._validate_connection(connection)

        self.log.debug(f"Executing query: {sql[:200]}{'...' if len(sql) > 200 else ''}")

        try:
            cursor = connection.cursor()

            if params:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)

            # Get column names
            column_names = [description[0] for description in cursor.description or []]

            # Convert rows to dictionaries
            results = []
            for row in cursor.fetchall():
                row_dict = {}
                for i, value in enumerate(row):
                    col_name = column_names[i] if i < len(column_names) else f"col_{i}"
                    # Convert value to Python types
                    row_dict[col_name] = self._convert_sqlite_to_python(value)
                    # Also add lowercase version for compatibility
                    row_dict[col_name.lower()] = row_dict[col_name]
                results.append(row_dict)

            self.log.debug(f"Query returned {len(results)} rows")

            return results

        except Exception as e:
            error_msg = f"Error executing query: {str(e)}"
            self.log.error(error_msg)
            self.log.error(f"SQL: {sql}")
            if params:
                self.log.error(f"Parameters: {params}")
            raise

    def _convert_sqlite_to_python(self, value: Any) -> Any:
        """Convert SQLite values to Python equivalents.

        Args:
            value: SQLite value to convert

        Returns:
            Converted Python value
        """
        if value is None:
            return None

        # SQLite stores booleans as integers
        # We can't reliably distinguish between boolean and integer,
        # so we leave as-is and let the caller handle interpretation

        # Handle bytes (BLOB)
        if isinstance(value, bytes):
            try:
                return value.decode("utf-8")
            except UnicodeDecodeError:
                return value

        return value

    def table_exists(self, connection: sqlite3.Connection, schema: str, table_name: str) -> bool:
        """Check if a table exists in the database.

        Note: SQLite doesn't have schemas, so the schema parameter is ignored.

        Args:
            connection: Active SQLite connection (provided by Provider)
            schema: Schema name (ignored for SQLite)
            table_name: Table name to check

        Returns:
            bool: True if table exists, False otherwise
        """
        self._validate_connection(connection)

        self.log.debug(f"Checking if table exists: {table_name}")

        try:
            # Query SQLite's sqlite_master table
            query = """
            SELECT COUNT(*) as table_count
            FROM sqlite_master
            WHERE type = 'table' AND name = ?
            """

            result = self.execute_query(connection, query, params=[table_name])

            if result and len(result) > 0:
                count = result[0].get("table_count", 0)
                exists = count > 0

                self.log.debug(f"Table {table_name} {'exists' if exists else 'does not exist'}")

                return bool(exists)
            else:
                return False

        except Exception as e:
            self.log.error(f"Error checking if table exists {table_name}: {str(e)}")
            return False

    def get_column_names(
        self, connection: sqlite3.Connection, schema: str, table: str
    ) -> List[str]:
        """Return column names for a table using PRAGMA table_info."""
        rows = self.execute_query(connection, f'PRAGMA table_info("{table}")')
        return [row["name"] for row in rows if "name" in row]

    def get_schema_qualified_name(self, schema: str, object_name: str) -> str:
        """Get a properly formatted object name for SQLite.

        Note: SQLite doesn't support schemas, so we just quote the object name.

        Args:
            schema: Schema name (ignored for SQLite)
            object_name: Object name (table, view, etc.)

        Returns:
            Properly quoted object name for SQLite
        """
        # SQLite uses double quotes for identifier quoting
        # Escape any double quotes within the identifier by doubling them
        clean_object = object_name.replace('"', '""')
        return f'"{clean_object}"'

    def _validate_connection(self, connection: Optional[sqlite3.Connection]) -> None:
        """Validate that a connection is provided and open.

        Args:
            connection: Connection to validate

        Raises:
            RuntimeError: If connection is None or closed
        """
        if connection is None:
            raise RuntimeError(
                "No database connection provided. Provider must pass an active connection "
                "to QueryExecutor methods."
            )

        # Check if connection is still open by attempting a simple query
        try:
            connection.execute("SELECT 1")
        except sqlite3.ProgrammingError as e:
            if "closed" in str(e).lower():
                raise RuntimeError(
                    "Database connection is closed. Provider must ensure connection is open "
                    "before calling QueryExecutor methods."
                )
            # Re-raise other programming errors
            raise
