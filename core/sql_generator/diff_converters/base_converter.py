"""Base converter for diff-to-SQL conversion."""

from abc import ABC, abstractmethod
from typing import List, Optional

from core.sql_generator.sql_statement import GenerationOptions, SqlStatement
from core.sql_model.dialect import DialectEnum


class BaseConverter(ABC):
    """Abstract base class for diff converters."""

    def __init__(self, dialect: str = "postgresql"):  # lint: allow-dialect-string: dialect dispatch
        """Initialize the converter.

        Args:
            dialect: SQL dialect to use
        """
        self.dialect = dialect

    @abstractmethod
    def convert(
        self, diff: object, context: object, options: GenerationOptions
    ) -> List[SqlStatement]:
        """Convert diff to SQL statements.

        Args:
            diff: Diff object to convert
            context: Context object (e.g., table name)
            options: Generation options

        Returns:
            List of SQL statements
        """

    def _quote_identifier(self, identifier: str) -> str:
        """Quote identifier based on dialect.

        Delegates to DialectEnum.quote_identifier (story 21-14 dispatch).

        Args:
            identifier: Identifier to quote

        Returns:
            Quoted identifier
        """
        return DialectEnum.quote_identifier(self.dialect, identifier)

    def _format_table_name(self, schema: Optional[str], table_name: str) -> str:
        """Format schema-qualified table name.

        Args:
            schema: Schema name (optional)
            table_name: Table name

        Returns:
            Formatted table name
        """
        if schema:
            return f"{self._quote_identifier(schema)}.{self._quote_identifier(table_name)}"
        return self._quote_identifier(table_name)
