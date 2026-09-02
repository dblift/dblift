"""Abstract base interface every dialect-specific SQL parser must implement."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from dblift.core.sql_model.base import ParseResult, SqlObject, SqlStatement


class SqlParserInterface(ABC):
    """Interface for SQL parsers."""

    @property
    @abstractmethod
    def dialect_name(self) -> str:
        """Return the name of the SQL dialect this parser handles."""

    @abstractmethod
    def parse_sql(self, sql_content: str, default_schema: Optional[str] = None) -> ParseResult:
        """Parse SQL content into statements.

        Args:
            sql_content: SQL content to parse
            default_schema: Default schema name

        Returns:
            ParseResult containing statements and/or errors
        """

    @abstractmethod
    def split_statements(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """Split SQL content into individual statements.

        Args:
            sql_content: SQL content to split

        Returns:
            List of SQL statement strings
        """

    @abstractmethod
    def validate_sql(self, sql_content: str) -> Dict[str, Any]:
        """Validate SQL syntax.

        Args:
            sql_content: SQL content to validate

        Returns:
            Dict with 'valid' (bool) and 'errors' (list of error messages)
        """

    @abstractmethod
    def extract_objects(
        self, sql_content: str, default_schema: Optional[str] = None
    ) -> List[SqlObject]:
        """Extract objects from SQL content.

        Args:
            sql_content: SQL content to extract objects from
            default_schema: Default schema name

        Returns:
            List of extracted SQL objects
        """

    def parse(self, sql: str, default_schema: Optional[str] = None) -> SqlStatement:
        """Parse a single SQL statement.

        Args:
            sql: SQL statement to parse
            default_schema: Default schema name

        Returns:
            SqlStatement object representing the parsed statement
        """
        result = self.parse_sql(sql, default_schema)
        if result.success and result.statements:
            return result.statements[0]
        raise ValueError(f"Failed to parse SQL: {', '.join(result.errors or [])}")

    def get_affected_objects(
        self, sql: str, default_schema: Optional[str] = None
    ) -> List[SqlObject]:
        """Get objects affected by a SQL statement.

        Args:
            sql: SQL statement to analyze
            default_schema: Default schema name

        Returns:
            List of affected SQL objects
        """
        objects = self.extract_objects(sql, default_schema)
        return objects
