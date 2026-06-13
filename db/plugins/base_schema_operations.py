"""Base abstract class for database schema operations."""

from abc import ABC, abstractmethod
from typing import Any, Callable, List, Optional, Set, Tuple, Union

from core.introspection._utils import get_row_value
from core.logger import Log, NullLog
from core.migration.clean_summary import CleanExecutionSummary


class BaseSchemaOperations(ABC):
    """Abstract base class for database-specific schema operations.

    This class defines the common interface that all database providers must implement
    for schema operations. Each database provider implements these methods according
    to their specific SQL dialect and capabilities.
    """

    def __init__(self, query_executor: Any, log: Optional[Log] = None) -> None:
        """Initialize the schema operations manager.

        Args:
            query_executor: Database-specific query executor instance
            log: Logger for operation tracking (defaults to NullLog if None)
        """
        self.query_executor: Any = query_executor
        self.log: Log = log if log is not None else NullLog()

    @abstractmethod
    def create_schema_if_not_exists(self, connection: Any, schema: str) -> None:
        """Create schema if it doesn't exist.

        Implementation varies by database:
        - PostgreSQL: CREATE SCHEMA IF NOT EXISTS
        - Oracle: CREATE USER (schemas are users in Oracle)
        - MySQL: CREATE DATABASE (databases are schemas in MySQL)
        - SQL Server: CREATE SCHEMA
        - DB2: CREATE SCHEMA

        Args:
            connection: Active database connection (provided by Provider)
            schema: Schema name to create
        """

    @abstractmethod
    def clean_schema(self, connection: Any, schema: str) -> CleanExecutionSummary:
        """Clean all objects from a schema.

        This method drops all database objects in the specified schema in the correct
        order to handle dependencies. The implementation is highly database-specific
        due to different object types and dependency handling.

        Args:
            connection: Active database connection (provided by Provider)
            schema: Schema name to clean

        Returns:
            Summary of cleaning operations performed
        """

    @abstractmethod
    def get_database_version(self, connection: Any) -> str:
        """Get the database version string.

        Args:
            connection: Active database connection (provided by Provider)

        Returns:
            Database version string (format varies by database)
        """

    @abstractmethod
    def set_current_schema(self, connection: Any, schema: str) -> None:
        """Set the current/default schema for the connection.

        Implementation varies by database:
        - PostgreSQL: SET search_path
        - Oracle: ALTER SESSION SET CURRENT_SCHEMA
        - MySQL: USE database
        - SQL Server: No direct equivalent (uses fully qualified names)
        - DB2: SET CURRENT SCHEMA

        Args:
            connection: Active database connection (provided by Provider)
            schema: Schema name to set as current
        """

    @abstractmethod
    def get_columns_query(self, schema: str, table: str) -> Union[str, Tuple[str, List[Any]]]:
        """Get SQL query to retrieve column information for a table.

        Args:
            schema: Schema name
            table: Table name

        Returns:
            str or (sql, params) tuple for parameterized queries
        """

    @abstractmethod
    def get_add_column_sql(self, schema: str, table: str, column: str, type_def: str) -> str:
        """Generate SQL to add a column to a table.

        Args:
            schema: Schema name
            table: Table name
            column: Column name to add
            type_def: Column type definition

        Returns:
            SQL statement to add the column
        """

    @abstractmethod
    def get_parameter_placeholders(self, count: int) -> str:
        """Generate parameter placeholders for prepared statements.

        Most databases use '?' but some may use different formats.

        Args:
            count: Number of placeholders needed

        Returns:
            Comma-separated placeholder string (e.g., "?, ?, ?")
        """

    @abstractmethod
    def get_tables(self, connection: Any, schema: str) -> List[str]:
        """Get list of table names in the specified schema.

        Args:
            connection: Active database connection (provided by Provider)
            schema: Schema name to query

        Returns:
            List of table names
        """

    @abstractmethod
    def get_schemas(self, connection: Any) -> List[str]:
        """Get list of all schema names in the database.

        Args:
            connection: Active database connection (provided by Provider)

        Returns:
            List of schema names
        """

    def _drop_objects_by_type(
        self,
        connection: Any,
        object_type: str,
        query: str,
        query_params: List[Any],
        name_key: str,
        drop_sql_builder: Callable[[str], str],
        summary: CleanExecutionSummary,
        schema: str = "",
        skip_names: Optional[Set[str]] = None,
    ) -> None:
        """Template method to drop all objects of a given type from a schema.

        Executes a query to find objects, iterates over results, and drops each one.
        Errors on individual drops are logged as warnings and processing continues.

        Args:
            connection: Active database connection
            object_type: Type label for summary recording (e.g. "trigger", "view")
            query: SQL query to list objects to drop
            query_params: Parameters for the query
            name_key: Key to extract object name from each result row
            drop_sql_builder: Callable that builds the DROP SQL from an object name
            summary: CleanExecutionSummary to record drops
            schema: Schema name for summary context
            skip_names: Optional set of uppercase names to skip

        Raises:
            Exception: If execute_query fails (query-level errors propagate to the caller).
                Individual DROP failures are caught, logged as warnings, and processing continues.
        """
        objects = self.query_executor.execute_query(connection, query, params=query_params)
        for row in objects:
            name = get_row_value(row, name_key.lower())
            if not name:
                continue
            if skip_names and name.upper() in skip_names:
                self.log.debug(f"Preserving {object_type} {name} (excluded by skip_names)")
                continue
            drop_sql = drop_sql_builder(name)
            try:
                self.query_executor.execute_statement(connection, drop_sql)
                summary.record_drop(drop_sql, object_type=object_type, name=name, schema=schema)
                self.log.debug(f"Dropped {object_type} {schema}.{name}")
            except Exception as e:
                self.log.warning(f"Failed to drop {object_type} {schema}.{name}: {str(e)}")

    def _enumerate_objects_by_type(
        self,
        connection: Any,
        object_type: str,
        query: str,
        query_params: List[Any],
        name_key: str,
        drop_sql_builder: Callable[[str], str],
        summary: CleanExecutionSummary,
        schema: str = "",
    ) -> None:
        """Preview-only sibling of ``_drop_objects_by_type``.

        BUG-03: ``get_clean_preview`` needs the exact same enumeration the
        real clean does — same query, same DROP SQL — but must not execute
        the DROP. Records each candidate via ``summary.record_drop`` instead.

        Query failures are caught and logged at debug level so a missing
        object kind on a given backend does not abort the preview.
        """
        try:
            objects = self.query_executor.execute_query(connection, query, params=query_params)
        except Exception as e:
            self.log.debug(f"Could not query {object_type}s for clean preview: {str(e)}")
            return

        for row in objects:
            name = get_row_value(row, name_key.lower())
            if not name:
                continue
            drop_sql = drop_sql_builder(name)
            summary.record_drop(drop_sql, object_type=object_type, name=name, schema=schema)

    # Common utility methods that can be shared across implementations

    def _validate_schema_name(self, schema: str) -> None:
        """Validate schema name for basic requirements.

        Args:
            schema: Schema name to validate

        Raises:
            ValueError: If schema name is invalid
        """
        if not schema or not schema.strip():
            raise ValueError("Schema name cannot be empty")

        if len(schema) > 128:  # Most databases have limits around 128 characters
            raise ValueError(f"Schema name too long: {len(schema)} characters (max 128)")

    def _format_schema_identifier(self, schema: str) -> str:
        """Format schema identifier for SQL queries.

        Default implementation returns the schema as-is. Database-specific
        implementations can override this to add quotes, case conversion, etc.

        Args:
            schema: Schema name to format

        Returns:
            Formatted schema identifier
        """
        return schema

    def _format_table_identifier(self, table: str) -> str:
        """Format table identifier for SQL queries.

        Default implementation returns the table as-is. Database-specific
        implementations can override this to add quotes, case conversion, etc.

        Args:
            table: Table name to format

        Returns:
            Formatted table identifier
        """
        return table

    def _get_qualified_table_name(self, schema: str, table: str) -> str:
        """Get fully qualified table name.

        Args:
            schema: Schema name
            table: Table name

        Returns:
            Qualified table name (e.g., "schema.table")
        """
        formatted_schema = self._format_schema_identifier(schema)
        formatted_table = self._format_table_identifier(table)
        return f"{formatted_schema}.{formatted_table}"
