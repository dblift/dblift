"""Neutral base converter for paid diff-to-SQL converters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from core.sql_model.dialect import quote_identifier
from core.state.sql_statement import GenerationOptions, SqlStatement


class BaseConverter(ABC):
    """Abstract base class for diff converters."""

    def __init__(self, dialect: str = "postgresql"):  # lint: allow-dialect-string
        """Initialize the converter with its target dialect."""
        self.dialect = dialect

    @abstractmethod
    def convert(
        self, diff: object, context: object, options: GenerationOptions
    ) -> List[SqlStatement]:
        """Convert diff to SQL statements."""

    def _quote_identifier(self, identifier: str) -> str:
        """Quote identifier based on dialect."""
        return quote_identifier(self.dialect, identifier)

    def _format_table_name(self, schema: Optional[str], table_name: str) -> str:
        """Format schema-qualified table name."""
        if schema:
            return f"{self._quote_identifier(schema)}.{self._quote_identifier(table_name)}"
        return self._quote_identifier(table_name)


__all__ = ["BaseConverter"]
