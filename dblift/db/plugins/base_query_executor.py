"""Base abstract class for database query executors."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

from dblift.core.logger import Log, NullLog


class BaseQueryExecutor(ABC):
    """Abstract base class for database-specific query executors.

    This class defines the common interface that all database providers must implement
    for query execution. Each database provider implements these methods according
    to its SQL dialect and driver binding requirements.
    """

    def __init__(self, connection_manager: Any, log: Optional[Log] = None) -> None:
        """Initialize the query executor.

        Args:
            connection_manager: Database-specific connection manager instance
            log: Logger for operation tracking (defaults to NullLog if None)
        """
        self.connection_manager: Any = connection_manager
        self.log: Log = log if log is not None else NullLog()

    @abstractmethod
    def execute_statement(
        self,
        connection: Any,
        sql: str,
        params: Optional[List[Any]] = None,
        return_generated_keys: bool = False,
    ) -> int:
        """Execute a SQL statement (INSERT, UPDATE, DELETE) and return affected rows.

        Implementation varies by database due to different parameter binding
        mechanisms and generated key handling.

        Args:
            connection: Active database connection to use (provided by Provider)
            sql: SQL statement to execute
            params: Optional parameters for prepared statement
            return_generated_keys: Whether to return generated keys (database-specific)

        Returns:
            Number of affected rows, or generated key value if requested
        """

    @abstractmethod
    def execute_query(
        self, connection: Any, sql: str, params: Optional[List[Any]] = None
    ) -> List[Dict[str, Any]]:
        """Execute a SQL query and return results as list of dictionaries.

        Implementation varies by database due to different result handling and
        data type conversions.

        Args:
            connection: Active database connection to use (provided by Provider)
            sql: SQL query to execute
            params: Optional parameters for prepared statement

        Returns:
            List of dictionaries representing query results
        """

    @abstractmethod
    def table_exists(self, connection: Any, schema: str, table_name: str) -> bool:
        """Check if a table exists in the specified schema.

        Implementation varies by database due to different system catalog queries
        and schema/catalog handling approaches.

        Args:
            connection: Active database connection to use (provided by Provider)
            schema: Schema name to check
            table_name: Table name to check

        Returns:
            True if table exists, False otherwise
        """

    def get_quoted_schema_name(self, schema: str) -> str:
        """Return the schema name correctly quoted for this dialect.

        Preserves the user-provided case exactly and applies dialect-specific
        quote characters (from ``_identifier_quote_chars()``) with proper
        escaping of the closing quote.  Use this helper wherever a bare
        schema reference must appear in SQL (e.g. ``ALTER SESSION SET
        CURRENT_SCHEMA``, ``CREATE USER``, ``GRANT ... TO``) so that all
        schema references are quoted consistently throughout the codebase.

        Callers must strip any existing quotes from ``schema`` before
        passing it in — this helper does not interpret pre-existing quotes.

        Args:
            schema: Unquoted schema name

        Returns:
            Schema name wrapped in dialect-specific quotes
        """
        open_q, close_q, escape = self._identifier_quote_chars()
        clean_schema = schema.strip().replace(close_q, escape)
        return f"{open_q}{clean_schema}{close_q}"

    def get_schema_qualified_name(self, schema: str, object_name: str) -> str:
        """Get fully qualified object name for the database.

        Default implementation uses ``_identifier_quote_chars()`` to quote
        identifiers.  Subclasses can override ``_identifier_quote_chars()``
        for dialect-specific quoting (e.g. backticks for MySQL, brackets for
        SQL Server) or override this method entirely for more complex rules.

        Args:
            schema: Schema name
            object_name: Object name

        Returns:
            Fully qualified object name
        """
        open_q, close_q, escape = self._identifier_quote_chars()
        clean_object = object_name.strip().replace(close_q, escape)
        return f"{self.get_quoted_schema_name(schema)}.{open_q}{clean_object}{close_q}"

    def _identifier_quote_chars(self) -> Tuple[str, str, str]:
        """Return (open_quote, close_quote, escape_sequence) for identifiers.

        Default uses ANSI double-quotes. Override for dialect-specific quoting.
        """
        return ('"', '"', '""')

    def _validate_connection(self, connection: Any) -> None:
        """Validate that a connection is provided and open.

        This replaces the old _ensure_connection() which could create connections.
        Now, QueryExecutor is stateless and requires connections to be passed in.

        Args:
            connection: Connection to validate

        Raises:
            RuntimeError: If connection is None or closed
        """
        if connection is None:
            raise RuntimeError(
                "No database connection provided. Provider must pass an active connection "
                "to QueryExecutor methods. QueryExecutor does not create or manage connections."
            )
        if connection.isClosed():
            raise RuntimeError(
                "Database connection is closed. Provider must ensure connection is open "
                "before calling QueryExecutor methods."
            )
