"""SQL Formatter for DDL Statements.

This module provides SQL formatting functionality using sqlglot for proper
indentation and formatting of DDL statements.
"""

import logging

from core.sql_model.dialect import SQLGLOT_DIALECT_MAP as _SQLGLOT_DIALECT_MAP  # noqa: F401
from core.sql_model.dialect import _ensure_sqlglot_dialect_map as _populate_sqlglot_map

logger = logging.getLogger(__name__)


class SqlFormatter:
    """Formats SQL DDL statements with proper indentation using sqlglot.

    This formatter uses sqlglot to parse and format SQL statements with
    proper indentation and structure. It gracefully falls back to
    unformatted SQL if formatting fails.

    Examples:
        >>> formatter = SqlFormatter(dialect="postgresql")
        >>> sql = "CREATE TABLE users(id INTEGER,name VARCHAR(100))"
        >>> formatted = formatter.format(sql)
        >>> print(formatted)
        CREATE TABLE users (
          id INT,
          name VARCHAR(100)
        )
    """

    def __init__(self, dialect: str):
        """Initialize formatter with target dialect.

        Args:
            dialect: SQL dialect (postgresql, oracle, mysql, sqlserver)
                    Note: DB2 is not supported and will use fallback
        """
        self.dialect = dialect.lower()
        # Populate the lazy map before reading — Epic 26 followup
        # moved the entries onto plugin Quirks.
        _populate_sqlglot_map()
        self.sqlglot_dialect = _SQLGLOT_DIALECT_MAP.get(self.dialect) or self.dialect

    def format(self, sql: str) -> str:
        """Format SQL DDL statement with proper indentation.

        Uses sqlglot to parse and format SQL statements. Falls back to
        unformatted SQL if formatting fails (e.g., for DB2 or complex statements).

        Args:
            sql: Raw SQL DDL string to format

        Returns:
            Formatted SQL string with proper indentation, or original SQL
            if formatting fails
        """
        if not sql or not sql.strip():
            return sql

        # Skip formatting for dialects with no sqlglot equivalent
        # (DB2). The quirks attribute is the canonical signal.
        from db.provider_registry import ProviderRegistry

        if ProviderRegistry.get_quirks(self.dialect).sqlglot_dialect is None:
            logger.debug(f"{self.dialect} has no sqlglot dialect — returning unformatted SQL")
            return sql

        try:
            import sqlglot
        except ImportError:
            logger.warning("sqlglot not available, returning unformatted SQL")
            return sql

        try:
            # Parse SQL using sqlglot
            ast = sqlglot.parse_one(sql, read=self.sqlglot_dialect)

            # Format with pretty printing
            formatted = ast.sql(dialect=self.sqlglot_dialect, pretty=True)
            # sqlglot's sql() returns Any, but we know it's always a string
            # Use type: ignore to suppress mypy warning about Any return type
            formatted_str: str = formatted

            if formatted_str and formatted_str.strip():
                return formatted_str
            else:
                logger.debug("sqlglot returned empty result, using original SQL")
                return sql

        except Exception as e:
            # Graceful fallback: return original SQL if formatting fails
            # This handles:
            # - Complex PROCEDURE/FUNCTION statements that sqlglot can't parse
            # - Unsupported syntax variations
            # - Any parsing errors
            logger.debug(f"SQL formatting failed: {e}, using original SQL")
            return sql

    def format_batch(self, sql_statements: list[str], separator: str = "\n\n") -> str:
        """Format multiple SQL statements.

        Args:
            sql_statements: List of SQL statements to format
            separator: Separator between statements (default: double newline)

        Returns:
            Formatted SQL string with all statements
        """
        formatted_statements = [self.format(stmt) for stmt in sql_statements]
        return separator.join(stmt for stmt in formatted_statements if stmt.strip())
