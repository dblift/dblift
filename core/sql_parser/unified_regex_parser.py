"""Universal regex-based SQL parser framework.

This module provides a unified regex-based parsing approach for all SQL dialects,
combining the best patterns from Oracle parser success with comprehensive dialect support.
"""

import logging
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Pattern, Tuple

from core.sql_model.base import (
    ParseResult,
    SqlObject,
    SqlObjectType,
    SqlStatement,
    SqlStatementType,
)
from core.sql_parser.parser_interface import SqlParserInterface

logger = logging.getLogger(__name__)


class DialectConfig(ABC):
    """Abstract base class for dialect-specific configuration."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Dialect name."""

    @property
    @abstractmethod
    def batch_separators(self) -> List[Pattern[str]]:
        """Regex patterns for batch separators (e.g., GO in SQL Server)."""

    @property
    @abstractmethod
    def quoted_identifiers(self) -> List[Pattern[str]]:
        """Regex patterns for quoted identifiers."""

    @property
    @abstractmethod
    def comment_patterns(self) -> List[Pattern[str]]:
        """Regex patterns for comments."""

    @property
    @abstractmethod
    def block_keywords(self) -> List[str]:
        """Keywords that start block statements (procedures, functions, etc.)."""

    @property
    @abstractmethod
    def ddl_patterns(self) -> Dict[str, Pattern[str]]:
        """DDL statement regex patterns."""

    @property
    @abstractmethod
    def dml_patterns(self) -> Dict[str, Pattern[str]]:
        """DML statement regex patterns."""

    @property
    @abstractmethod
    def query_patterns(self) -> Dict[str, Pattern[str]]:
        """Query statement regex patterns."""

    @property
    @abstractmethod
    def object_patterns(self) -> Dict[str, Pattern[str]]:
        """Object extraction regex patterns."""

    def get_default_schema(self) -> str:
        """Get default schema name for this dialect."""
        return "default_schema"

    def normalize_identifier(self, identifier: str, is_quoted: bool = False) -> str:
        """Normalize identifier according to dialect rules (case, etc.)."""
        return identifier


class RegexParser(SqlParserInterface):
    """
    Universal regex-based SQL parser that supports multiple dialects.

    This parser combines the proven patterns from Oracle parser with
    dialect-specific customization for comprehensive SQL support.
    """

    def __init__(self, dialect_config: DialectConfig):
        """Initialize parser with dialect-specific configuration.

        Args:
            dialect_config: Dialect-specific configuration object
        """
        self.config = dialect_config
        self._last_statement: Optional[str] = None
        self._last_objects: List[SqlObject] = []
        self._last_errors: List[str] = []
        self._last_type: Optional[SqlStatementType] = None

        # Compile regex patterns for performance
        self._compiled_patterns = self._compile_patterns()

    @property
    def dialect_name(self) -> str:
        """Return the dialect name."""
        return self.config.name

    def parse_sql(self, sql_content: str, default_schema: Optional[str] = None) -> ParseResult:
        """Parse SQL content into statements using regex-based approach.

        Args:
            sql_content: SQL content to parse
            default_schema: Default schema name

        Returns:
            ParseResult with statements and any errors
        """
        statements = []
        errors = []

        try:
            # Clean and normalize SQL
            cleaned_sql = self._clean_sql(sql_content)

            # Split into individual statements using dialect-aware logic
            sql_statements = self.split_statements(cleaned_sql)

            # Parse each statement
            for sql in sql_statements:
                if not sql.strip():
                    continue

                try:
                    stmt_type = self._classify_statement(sql)
                    objects = self.extract_objects(sql, default_schema)

                    statement = SqlStatement(
                        sql_text=sql,
                        statement_type=stmt_type,
                        objects=objects,
                        affected_objects=objects,
                        dialect=self.dialect_name,
                        schema=default_schema or self.config.get_default_schema(),
                    )
                    statements.append(statement)
                except Exception as e:
                    error_msg = f"Error parsing statement: {str(e)}"
                    logger.warning(error_msg)
                    errors.append(error_msg)

        except Exception as e:
            error_msg = f"Error splitting SQL: {str(e)}"
            logger.error(error_msg)
            errors.append(error_msg)

        # Return success if we got statements, even with some errors
        success = len(statements) > 0 or len(errors) == 0
        return ParseResult(success=success, statements=statements, errors=errors)

    def split_statements(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """Split SQL content into individual statements using dialect-aware logic.

        Args:
            sql_content: SQL content to split

        Returns:
            List of SQL statement strings
        """
        if not sql_content.strip():
            return []

        # Check for dialect-specific batch separators
        if self._has_batch_separators(sql_content):
            return self._split_with_batch_separators(sql_content)

        # Check for block statements (procedures, functions, etc.)
        if self._has_block_statements(sql_content):
            return self._split_with_block_awareness(sql_content)

        # Default to semicolon-based splitting
        return self._split_by_semicolon(sql_content)

    def validate_sql(self, sql_content: str) -> Dict[str, Any]:
        """Validate SQL by attempting to parse into statements.

        Args:
            sql_content: SQL content to validate

        Returns:
            Dict with 'valid' (bool), 'statements_found' (int), and 'errors' (list)
        """
        try:
            statements = self.split_statements(sql_content)
            return {"valid": True, "statements_found": len(statements), "errors": []}
        except Exception as e:
            return {"valid": False, "statements_found": 0, "errors": [str(e)]}

    def extract_objects(
        self, sql_content: str, default_schema: Optional[str] = None
    ) -> List[SqlObject]:
        """Extract database objects from SQL content using regex patterns.

        Args:
            sql_content: SQL content to extract objects from
            default_schema: Default schema name

        Returns:
            List of SqlObject instances
        """
        objects: List[SqlObject] = []

        if not sql_content or not sql_content.strip():
            return objects

        sql = sql_content.strip()
        schema = default_schema or self.config.get_default_schema()

        # Extract objects using dialect-specific patterns
        for pattern_name, pattern in self.config.object_patterns.items():
            matches = pattern.finditer(sql)
            for match in matches:
                obj = self._create_object_from_match(match, pattern_name, schema)
                if obj:
                    objects.append(obj)

        return objects

    # Private helper methods

    def _compile_patterns(self) -> Dict[str, Any]:
        """Compile regex patterns for better performance."""
        compiled = {}

        # Compile all pattern categories
        for category in ["ddl_patterns", "dml_patterns", "query_patterns", "object_patterns"]:
            patterns = getattr(self.config, category)
            compiled[category] = {name: pattern for name, pattern in patterns.items()}

        return compiled

    def _clean_sql(self, sql: str) -> str:
        """Clean SQL content by removing or normalizing problematic elements."""
        # Remove dialect-specific comments
        for comment_pattern in self.config.comment_patterns:
            sql = comment_pattern.sub("", sql)

        # Normalize whitespace
        sql = re.sub(r"\s+", " ", sql)

        return sql.strip()

    def _has_batch_separators(self, sql: str) -> bool:
        """Check if SQL contains dialect-specific batch separators."""
        for separator_pattern in self.config.batch_separators:
            if separator_pattern.search(sql):
                return True
        return False

    def _has_block_statements(self, sql: str) -> bool:
        """Check if SQL contains block statements that need special handling."""
        sql_upper = sql.upper()
        for keyword in self.config.block_keywords:
            if keyword in sql_upper:
                return True
        return False

    def _split_with_batch_separators(self, sql: str) -> List[str]:
        """Split SQL using dialect-specific batch separators."""
        statements = []

        # Find the primary batch separator for this dialect
        primary_separator = (
            self.config.batch_separators[0] if self.config.batch_separators else None
        )

        if primary_separator:
            batches = primary_separator.split(sql)
            for batch in batches:
                batch = batch.strip()
                if batch:
                    # Further split each batch if needed
                    batch_statements = self._split_with_block_awareness(batch)
                    statements.extend(batch_statements)
        else:
            statements = [sql]

        return statements

    def _split_with_block_awareness(self, sql: str) -> List[str]:
        """Split SQL while preserving block statements (procedures, functions, etc.)."""
        statements = []
        i = 0
        text = sql.strip()

        while i < len(text):
            # Skip whitespace
            while i < len(text) and text[i].isspace():
                i += 1

            if i >= len(text):
                break

            # Extract next complete statement
            statement, next_pos = self._extract_next_statement(text, i)

            if statement and not self._is_empty_or_comment(statement):
                statements.append(statement.strip())

            i = next_pos

        return statements

    def _split_by_semicolon(self, sql: str) -> List[str]:
        """Split SQL by semicolons while respecting string literals and comments."""
        statements = []
        current = []
        in_string = False
        in_identifier = False
        in_line_comment = False
        in_block_comment = False
        string_char = None
        i = 0

        while i < len(sql):
            char = sql[i]

            # Handle string literals
            if not in_line_comment and not in_block_comment:
                if not in_string and char in ("'", '"'):
                    in_string = True
                    string_char = char
                elif in_string and char == string_char:
                    # Check for escaped quotes
                    if i + 1 < len(sql) and sql[i + 1] == string_char:
                        current.append(char)
                        current.append(sql[i + 1])
                        i += 2
                        continue
                    else:
                        in_string = False
                        string_char = None

            # Handle quoted identifiers (dialect-specific)
            if not in_string and not in_line_comment and not in_block_comment:
                # This would use dialect-specific quoted identifier patterns
                pass

            # Handle comments
            if not in_string:
                # Line comments
                if char == "-" and i + 1 < len(sql) and sql[i + 1] == "-":
                    in_line_comment = True
                    current.append(char)
                    current.append(sql[i + 1])
                    i += 2
                    continue
                # Block comments
                elif char == "/" and i + 1 < len(sql) and sql[i + 1] == "*":
                    in_block_comment = True
                    current.append(char)
                    current.append(sql[i + 1])
                    i += 2
                    continue
                elif char == "*" and i + 1 < len(sql) and sql[i + 1] == "/" and in_block_comment:
                    in_block_comment = False
                    current.append(char)
                    current.append(sql[i + 1])
                    i += 2
                    continue

            # End line comments at newline
            if char in ["\n", "\r"] and in_line_comment:
                in_line_comment = False

            # Handle statement terminators
            if (
                char == ";"
                and not in_string
                and not in_identifier
                and not in_line_comment
                and not in_block_comment
            ):
                current.append(char)
                stmt = "".join(current).strip()
                if stmt:
                    statements.append(stmt)
                current = []
                i += 1
                continue

            current.append(char)
            i += 1

        # Add any remaining statement
        if current:
            stmt = "".join(current).strip()
            if stmt:
                statements.append(stmt)

        return statements

    def _extract_next_statement(self, text: str, start_pos: int) -> Tuple[str, int]:
        """Extract the next complete SQL statement starting at the given position."""
        if start_pos >= len(text):
            return "", start_pos

        remaining = text[start_pos:].strip()
        if not remaining:
            return "", len(text)

        # Check if this starts a block statement
        if self._starts_with_block_keyword(remaining):
            return self._extract_block_statement(text, start_pos)
        else:
            return self._extract_regular_statement(text, start_pos)

    def _starts_with_block_keyword(self, text: str) -> bool:
        """Check if text starts with a block keyword."""
        text_upper = text.upper().strip()
        return any(text_upper.startswith(keyword) for keyword in self.config.block_keywords)

    def _extract_block_statement(self, text: str, start_pos: int) -> Tuple[str, int]:
        """Extract a complete block statement (handles nested BEGIN/END)."""
        # This would implement the sophisticated block extraction logic
        # similar to Oracle parser's _extract_plsql_block method
        return self._extract_regular_statement(text, start_pos)  # Simplified for now

    def _extract_regular_statement(self, text: str, start_pos: int) -> Tuple[str, int]:
        """Extract a regular SQL statement ending with semicolon."""
        i = start_pos
        statement = ""

        while i < len(text):
            char = text[i]

            # Simple implementation - would need string/comment awareness
            if char == ";":
                statement += char
                return statement.strip(), i + 1

            statement += char
            i += 1

        return statement.strip(), len(text)

    def _is_empty_or_comment(self, stmt: str) -> bool:
        """Check if statement is empty or just comments."""
        if not stmt or not stmt.strip():
            return True

        # Remove comments and check if anything remains
        for comment_pattern in self.config.comment_patterns:
            stmt = comment_pattern.sub("", stmt)

        return not stmt.strip()

    def _classify_statement(self, sql: str) -> SqlStatementType:
        """Classify SQL statement type using regex patterns."""
        sql_upper = sql.strip().upper()

        # Check DDL patterns
        for pattern in self.config.ddl_patterns.values():
            if pattern.search(sql_upper):
                return SqlStatementType.DDL

        # Check DML patterns
        for pattern in self.config.dml_patterns.values():
            if pattern.search(sql_upper):
                return SqlStatementType.DML

        # Check query patterns
        for pattern in self.config.query_patterns.values():
            if pattern.search(sql_upper):
                return SqlStatementType.QUERY

        return SqlStatementType.UNKNOWN

    def _create_object_from_match(
        self, match: "re.Match[str]", pattern_name: str, default_schema: str
    ) -> Optional[SqlObject]:
        """Create SqlObject from regex match based on pattern type."""
        # This would implement object creation logic based on the pattern name
        # and match groups, similar to Oracle parser's object extraction

        # Simplified implementation
        if "table" in pattern_name.lower():
            return SqlObject(
                name=match.group(1) if match.groups() else "unknown",
                object_type=SqlObjectType.TABLE,
                schema=default_schema,
                dialect=self.dialect_name,
            )

        return None
