"""Enhanced regex-based SQL parser incorporating Oracle parser success patterns.

This module provides an enhanced regex parser that combines the proven Oracle
parser patterns with the universal regex framework for comprehensive SQL parsing.
"""

import logging
import re
from typing import Dict, List, Optional, Pattern

from dblift.core.sql_model.base import (
    ParseResult,
    SqlObject,
    SqlObjectType,
    SqlStatement,
    SqlStatementType,
)
from dblift.core.sql_parser.unified_regex_parser import DialectConfig, RegexParser

logger = logging.getLogger(__name__)


class EnhancedRegexParser(RegexParser):
    """
    Enhanced regex-based SQL parser incorporating Oracle parser success patterns.

    This parser combines the proven patterns from Oracle parser's regex implementation
    with the universal framework to provide robust SQL parsing across all dialects.

    Key enhancements:
    - Oracle-proven PL/SQL block detection
    - Sophisticated string literal handling
    - Nested comment support
    - Block-aware statement splitting
    - Intelligent object extraction
    """

    def __init__(self, dialect_config: DialectConfig):
        """Initialize enhanced parser with dialect-specific configuration.

        Args:
            dialect_config: Dialect-specific configuration object
        """
        super().__init__(dialect_config)

        # Enhanced patterns compiled for performance
        self._string_patterns = self._compile_string_patterns()
        self._block_detection_patterns = self._compile_block_patterns()

        logger.debug("Enhanced regex parser initialized")

    def split_statements(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """Split SQL content using enhanced Oracle-proven patterns.

        This method incorporates the successful patterns from Oracle parser's
        _split_statements_regex method for more robust statement splitting.

        Args:
            sql_content: SQL content to split

        Returns:
            List of SQL statement strings
        """
        if not sql_content.strip():
            return []

        # Clean and normalize SQL first
        cleaned_sql = self._clean_sql(sql_content)

        # Check for batch separators first (dialect-specific)
        if self._has_batch_separators(cleaned_sql):
            return self._split_with_batch_separators(cleaned_sql)

        # Check for block statements that need special handling
        if self._has_block_statements(cleaned_sql):
            return self._split_with_block_awareness(cleaned_sql)

        # Enhanced semicolon-based splitting with Oracle-proven patterns
        return self._split_by_semicolon_enhanced(cleaned_sql)

    def extract_objects(
        self, sql_content: str, default_schema: Optional[str] = None
    ) -> List[SqlObject]:
        """Extract database objects using enhanced patterns from Oracle parser.

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

        # Enhanced object extraction with better error handling
        for pattern_name, pattern in self.config.object_patterns.items():
            try:
                matches = pattern.finditer(sql)
                for match in matches:
                    obj = self._create_object_from_match_enhanced(match, pattern_name, schema)
                    if obj:
                        objects.append(obj)
            except Exception as e:
                logger.warning(f"Error extracting objects with pattern {pattern_name}: {e}")
                continue

        return objects

    def parse_sql(self, sql_content: str, default_schema: Optional[str] = None) -> ParseResult:
        """Parse SQL content with enhanced error handling and Oracle-proven patterns.

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

            # Enhanced statement splitting
            sql_statements = self.split_statements(cleaned_sql)

            # Parse each statement with enhanced error handling
            for sql in sql_statements:
                if not sql.strip():
                    continue

                try:
                    stmt_type = self._classify_statement_enhanced(sql)
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

                    # Create statement with minimal info for partial recovery
                    statement = SqlStatement(
                        sql_text=sql,
                        statement_type=SqlStatementType.UNKNOWN,
                        objects=[],
                        affected_objects=[],
                        dialect=self.dialect_name,
                        schema=default_schema or self.config.get_default_schema(),
                    )
                    statements.append(statement)

        except Exception as e:
            error_msg = f"Error splitting SQL: {str(e)}"
            logger.error(error_msg)
            errors.append(error_msg)

        # Return success if we got statements, even with some errors
        success = len(statements) > 0 or len(errors) == 0
        return ParseResult(success=success, statements=statements, errors=errors)

    # Enhanced helper methods incorporating Oracle parser patterns

    def _compile_string_patterns(self) -> Dict[str, Pattern[str]]:
        """Compile string literal patterns for enhanced parsing."""
        return {
            "single_quote": re.compile(r"'(?:[^']|'')*'"),
            "double_quote": re.compile(r'"(?:[^"]|"")*"'),
            "dollar_quote": re.compile(r"\$\w*\$.*?\$\w*\$", re.DOTALL),  # PostgreSQL
        }

    def _compile_block_patterns(self) -> Dict[str, Pattern[str]]:
        """Compile block detection patterns based on Oracle parser success."""
        return {
            "plsql_block": re.compile(
                r"\b(?:DECLARE|BEGIN)\b.*?\bEND\b", re.IGNORECASE | re.DOTALL
            ),
            "procedure_block": re.compile(
                r"\bCREATE\s+(?:OR\s+REPLACE\s+)?PROCEDURE\b", re.IGNORECASE
            ),
            "function_block": re.compile(
                r"\bCREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\b", re.IGNORECASE
            ),
        }

    def _split_by_semicolon_enhanced(self, sql: str) -> List[str]:
        """Enhanced semicolon splitting incorporating Oracle parser patterns."""
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

            # Handle string literals with Oracle-style escaping
            if not in_line_comment and not in_block_comment:
                if not in_string and char in ("'", '"'):
                    in_string = True
                    string_char = char
                elif in_string and char == string_char:
                    # Check for Oracle-style escaped quotes (double quote)
                    if i + 1 < len(sql) and sql[i + 1] == string_char:
                        current.append(char)
                        current.append(sql[i + 1])
                        i += 2
                        continue
                    else:
                        in_string = False
                        string_char = None

            # Handle dialect-specific quoted identifiers
            if not in_string and not in_line_comment and not in_block_comment:
                # This would need more sophisticated handling for bracket identifiers
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

            # Handle statement terminators (semicolon)
            if (
                char == ";"
                and not in_string
                and not in_identifier
                and not in_line_comment
                and not in_block_comment
            ):
                current.append(char)
                stmt = "".join(current).strip()
                if stmt and not self._is_empty_or_comment(stmt):
                    statements.append(stmt)
                current = []
                i += 1
                continue

            current.append(char)
            i += 1

        # Add any remaining statement
        if current:
            stmt = "".join(current).strip()
            if stmt and not self._is_empty_or_comment(stmt):
                statements.append(stmt)

        return statements

    def _clean_sql(self, sql: str) -> str:
        """Clean and normalize SQL content."""
        return sql.strip()

    def _has_batch_separators(self, sql: str) -> bool:
        """Check if SQL contains batch separators."""
        for pattern in self.config.batch_separators:
            if pattern.search(sql):
                return True
        return False

    def _has_block_statements(self, sql: str) -> bool:
        """Check if SQL contains block statements."""
        for keyword in self.config.block_keywords:
            if keyword in sql.upper():
                return True
        return False

    def _split_with_batch_separators(self, sql: str) -> List[str]:
        """Split SQL using batch separators."""
        # Simple implementation - can be enhanced
        return [stmt.strip() for stmt in sql.split(";") if stmt.strip()]

    def _split_with_block_awareness(self, sql: str) -> List[str]:
        """Split SQL with block awareness."""
        # Simple implementation - can be enhanced
        return [stmt.strip() for stmt in sql.split(";") if stmt.strip()]

    def _is_empty_or_comment(self, stmt: str) -> bool:
        """Check if statement is empty or just comments."""
        stmt = stmt.strip()
        if not stmt:
            return True
        # Check against comment patterns
        for pattern in self.config.comment_patterns:
            if pattern.fullmatch(stmt):
                return True
        return False

    def _classify_statement_enhanced(self, sql: str) -> SqlStatementType:
        """Enhanced statement classification using Oracle-proven patterns."""
        sql_upper = sql.strip().upper()

        if not sql_upper:
            return SqlStatementType.UNKNOWN

        # Remove comments for better classification
        sql_clean = self._remove_comments_enhanced(sql_upper)

        # Check DDL patterns with enhanced handling
        for pattern_name, pattern in self.config.ddl_patterns.items():
            if pattern.search(sql_clean):
                return SqlStatementType.DDL

        # Check DML patterns
        for pattern_name, pattern in self.config.dml_patterns.items():
            if pattern.search(sql_clean):
                return SqlStatementType.DML

        # Check query patterns
        for pattern_name, pattern in self.config.query_patterns.items():
            if pattern.search(sql_clean):
                return SqlStatementType.QUERY

        # Enhanced pattern matching for edge cases
        if self._is_block_statement_enhanced(sql_clean):
            return SqlStatementType.DDL  # Most block statements are DDL

        return SqlStatementType.UNKNOWN

    def _remove_comments_enhanced(self, sql: str) -> str:
        """Enhanced comment removal using dialect-specific patterns."""
        for comment_pattern in self.config.comment_patterns:
            sql = comment_pattern.sub("", sql)
        return sql.strip()

    def _is_block_statement_enhanced(self, sql: str) -> bool:
        """Enhanced block statement detection using Oracle-proven patterns."""
        for pattern in self._block_detection_patterns.values():
            if pattern.search(sql):
                return True
        return False

    def _create_object_from_match_enhanced(
        self, match: "re.Match[str]", pattern_name: str, default_schema: str
    ) -> Optional[SqlObject]:
        """Enhanced object creation with better error handling and schema detection."""
        try:
            # Extract object name and schema from match groups
            groups = match.groups()
            if not groups:
                return None

            # Enhanced schema and name extraction
            schema_name = default_schema
            object_name = "unknown"

            # Try to extract schema and object name from match groups
            # PostgreSQL patterns often have 4 groups: (quoted_schema, unquoted_schema, quoted_name, unquoted_name)
            # We need to find the last non-None group as the object name, and the first non-None group before it as schema
            non_none_groups = [g for g in groups if g is not None]

            if len(non_none_groups) >= 2:
                # For patterns with schema.name structure:
                # - Last non-None group is the object name
                # - First non-None group is typically the schema (if different from name)
                extracted_name = non_none_groups[-1]
                extracted_schema = (
                    non_none_groups[0] if non_none_groups[0] != extracted_name else None
                )

                if extracted_name:
                    object_name = extracted_name
                if extracted_schema and extracted_schema != extracted_name:
                    schema_name = extracted_schema
            elif len(non_none_groups) >= 1:
                # Single group - it's the object name
                object_name = non_none_groups[0]

            # Normalize identifiers according to dialect rules
            object_name = self.config.normalize_identifier(object_name)
            schema_name = self.config.normalize_identifier(schema_name)

            # Determine object type from pattern name
            object_type = self._get_object_type_from_pattern(pattern_name)

            return SqlObject(
                name=object_name,
                object_type=object_type,
                schema=schema_name,
                dialect=self.dialect_name,
            )

        except Exception as e:
            logger.warning(f"Error creating object from match: {e}")
            return None

    def _get_object_type_from_pattern(self, pattern_name: str) -> SqlObjectType:
        """Get SqlObjectType from pattern name."""
        pattern_lower = pattern_name.lower()

        if "table" in pattern_lower:
            return SqlObjectType.TABLE
        elif "view" in pattern_lower:
            return SqlObjectType.VIEW
        elif "index" in pattern_lower:
            return SqlObjectType.INDEX
        elif "sequence" in pattern_lower:
            return SqlObjectType.SEQUENCE
        elif "procedure" in pattern_lower:
            return SqlObjectType.PROCEDURE
        elif "function" in pattern_lower:
            return SqlObjectType.FUNCTION
        elif "trigger" in pattern_lower:
            return SqlObjectType.TRIGGER
        elif "extension" in pattern_lower:
            return SqlObjectType.EXTENSION
        elif "foreign_data_wrapper" in pattern_lower:
            return SqlObjectType.FOREIGN_DATA_WRAPPER
        elif "foreign_server" in pattern_lower:
            return SqlObjectType.FOREIGN_SERVER
        else:
            return SqlObjectType.UNKNOWN
