"""Base configuration for SQL dialect parsers.

This module provides the abstract base class for dialect-specific configurations
used by the unified regex parser framework.
"""

from abc import ABC, abstractmethod
from typing import Optional, Pattern, Set


class DialectConfig(ABC):
    """Abstract base class for dialect-specific configurations."""

    def __init__(self):
        """Initialize base configuration."""
        self.identifier_quote_char: str = '"'
        self.string_quote_char: str = "'"
        self.statement_separator: str = ";"
        self.line_comment_prefix: str = "--"
        self.block_comment_start: str = "/*"
        self.block_comment_end: str = "*/"

        # Dialect-specific features
        self.supports_dollar_quoting: bool = False
        self.supports_copy_statements: bool = False
        self.supports_plpgsql_blocks: bool = False
        self.supports_cte_with_recursive: bool = False
        self.supports_on_conflict: bool = False
        self.supports_returning: bool = False

        # Object patterns for enhanced parsing
        # Note: Subclasses provide this as a property, so we don't initialize it here

    @abstractmethod
    def get_ddl_keywords(self) -> Set[str]:
        """Get DDL keywords for this dialect."""

    @abstractmethod
    def get_dml_keywords(self) -> Set[str]:
        """Get DML keywords for this dialect."""

    @abstractmethod
    def get_query_keywords(self) -> Set[str]:
        """Get query keywords for this dialect."""

    @abstractmethod
    def get_identifier_pattern(self) -> Pattern[str]:
        """Get regex pattern for identifiers."""

    @abstractmethod
    def get_qualified_identifier_pattern(self) -> Pattern[str]:
        """Get regex pattern for qualified identifiers."""

    @abstractmethod
    def get_string_literal_pattern(self) -> Pattern[str]:
        """Get regex pattern for string literals."""

    @abstractmethod
    def get_comment_pattern(self) -> Pattern[str]:
        """Get regex pattern for comments."""

    @abstractmethod
    def get_statement_separator_pattern(self) -> Pattern[str]:
        """Get regex pattern for statement separators."""

    @abstractmethod
    def is_ddl_statement(self, statement: str) -> bool:
        """Check if statement is a DDL statement."""

    @abstractmethod
    def is_dml_statement(self, statement: str) -> bool:
        """Check if statement is a DML statement."""

    @abstractmethod
    def is_query_statement(self, statement: str) -> bool:
        """Check if statement is a query statement."""

    @abstractmethod
    def get_batch_separator(self) -> str:
        """Get batch separator for this dialect."""

    @abstractmethod
    def supports_block_comments(self) -> bool:
        """Check if dialect supports block comments."""

    @abstractmethod
    def supports_line_comments(self) -> bool:
        """Check if dialect supports line comments."""

    def get_transaction_keywords(self) -> Set[str]:
        """Get transaction control keywords for this dialect."""
        return {
            "BEGIN",
            "START",
            "COMMIT",
            "END",
            "ROLLBACK",
            "ABORT",
            "SAVEPOINT",
            "RELEASE",
            "TRANSACTION",
            "WORK",
        }

    def get_block_keywords_for_splitting(self) -> Set[str]:
        """Get block keywords that require special handling during splitting."""
        return {
            "BEGIN",
            "END",
            "DECLARE",
            "EXCEPTION",
            "WHEN",
            "THEN",
            "ELSE",
            "IF",
            "LOOP",
            "WHILE",
            "FOR",
            "CASE",
            "RETURN",
        }

    def get_default_schema(self) -> Optional[str]:
        """Get the default schema for this dialect."""
        return None
