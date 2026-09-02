"""MySQL tokenization-based SQL parser implementation.

This module provides a MySQL-specific parser that uses tokenization to handle MySQL's unique
features including DELIMITER statements, backtick identifiers, and stored procedures.
"""

import logging
import re
from typing import Any, Dict, List, Optional

from dblift.core.sql_model.base import ParseResult, SqlStatement, SqlStatementType
from dblift.core.sql_parser.enhanced_regex_parser import EnhancedRegexParser
from dblift.core.sql_parser.parser_context import ParserContext
from dblift.db.plugins.mysql.parser.mysql_statement_parser import MySQLStatementParser
from dblift.db.plugins.mysql.parser.mysql_tokenizer import MySQLTokenizer
from dblift.db.plugins.mysql.parser.parser_config import MySqlConfig

logger = logging.getLogger(__name__)


class MySqlRegexParser(EnhancedRegexParser):
    """MySQL-specific regex parser with enhanced MySQL feature support."""

    dialect_name = "mysql"  # lint: allow-dialect-string: dialect dispatch

    def __init__(self) -> None:
        """Initialize MySQL regex parser."""
        config = MySqlConfig()
        super().__init__(config)  # type: ignore[arg-type]
        self.config: MySqlConfig = config  # type: ignore[assignment]

    def split_statements(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """Split SQL content with MySQL-specific handling.

        Handles DELIMITER statements, backtick identifiers, and MySQL comments.
        Uses tokenization-based approach for robust parsing with fallback to regex.

        Args:
            sql_content: SQL content to split

        Returns:
            List of SQL statement strings
        """
        if not sql_content or not sql_content.strip():
            return []

        try:
            # Use tokenization-based splitting
            tokenizer = MySQLTokenizer(sql_content, strict_unknown_chars=strict_tokenizer)
            tokens = tokenizer.tokenize()

            context = ParserContext()
            parser = MySQLStatementParser(tokens, context)

            statements = parser.split_statements()
            logger.debug(f"MySQL: Tokenization split into {len(statements)} statements")
            return statements

        except Exception as e:
            if strict_tokenizer:
                raise
            # Fallback to old regex-based splitting if tokenization fails
            logger.warning(f"MySQL tokenization failed, falling back to regex: {str(e)}")

        # Fallback: Handle DELIMITER statements specially
        if self._has_delimiter_statements(sql_content):
            return self._split_with_delimiter_awareness(sql_content)

        # Clean MySQL-specific comments first
        cleaned_sql = self._clean_mysql_comments(sql_content)

        # Check for stored procedures/functions that might use BEGIN/END
        if self._has_stored_procedures(cleaned_sql):
            return self._split_with_procedure_awareness(cleaned_sql)

        # Use enhanced semicolon splitting with backtick awareness
        return self._split_by_semicolon_mysql(cleaned_sql)

    def _has_delimiter_statements(self, sql: str) -> bool:
        """Check if SQL contains DELIMITER statements outside comments/strings."""
        # Quick check first
        if not re.search(r"^\s*DELIMITER\s+", sql, re.IGNORECASE | re.MULTILINE):
            return False

        # Verify DELIMITER appears outside comments/strings
        in_single = False
        in_double = False
        in_backtick = False
        in_line_comment = False
        in_block_comment = False
        i = 0
        while i < len(sql):
            ch = sql[i]
            # End of line comment
            if in_line_comment:
                if ch in ("\n", "\r"):
                    in_line_comment = False
                i += 1
                continue
            # End of block comment
            if in_block_comment:
                if ch == "*" and i + 1 < len(sql) and sql[i + 1] == "/":
                    in_block_comment = False
                    i += 2
                else:
                    i += 1
                continue
            # Toggle string/backtick states
            if ch == "'" and not in_double and not in_backtick:
                in_single = not in_single
                i += 1
                continue
            if ch == '"' and not in_single and not in_backtick:
                in_double = not in_double
                i += 1
                continue
            if ch == "`" and not in_single and not in_double:
                in_backtick = not in_backtick
                i += 1
                continue
            # Start comments when not in strings
            if not in_single and not in_double and not in_backtick:
                if ch == "#":
                    in_line_comment = True
                    i += 1
                    continue
                if ch == "-" and i + 1 < len(sql) and sql[i + 1] == "-":
                    in_line_comment = True
                    i += 2
                    continue
                if ch == "/" and i + 1 < len(sql) and sql[i + 1] == "*":
                    in_block_comment = True
                    i += 2
                    continue
                # Check for DELIMITER at start of line when not in comment/string
                if ch in ("\n", "\r") or i == 0:
                    # Find start of this line
                    line_start = i if i == 0 else i + 1
                    # Extract until end of line
                    line_end = sql.find("\n", line_start)
                    if line_end == -1:
                        line_end = len(sql)
                    line = sql[line_start:line_end]
                    if re.match(r"^\s*DELIMITER\s+", line, re.IGNORECASE):
                        return True
            i += 1
        return False

    def _has_stored_procedures(self, sql: str) -> bool:
        """Check if SQL contains stored procedures, functions, events, or triggers with BEGIN/END blocks."""
        return bool(
            re.search(
                r"\b(?:CREATE|ALTER)\s+(?:PROCEDURE|FUNCTION|EVENT|TRIGGER)\b", sql, re.IGNORECASE
            )
        )

    def _clean_mysql_comments(self, sql: str) -> str:
        """Clean MySQL-specific comments from SQL."""
        # Remove hash comments
        sql = re.sub(r"#.*$", "", sql, flags=re.MULTILINE)

        # Remove -- comments
        sql = re.sub(r"--.*$", "", sql, flags=re.MULTILINE)

        # Remove /* */ comments but preserve /*! */ MySQL-specific comments
        sql = re.sub(r"/\*(?!!)(.*?)\*/", "", sql, flags=re.DOTALL)

        return sql

    def _split_with_delimiter_awareness(self, sql: str) -> List[str]:
        """Split SQL with DELIMITER statement awareness."""
        statements = []
        delimiter_blocks = self.config.extract_delimiter_blocks(sql)

        for block in delimiter_blocks:
            content = block["content"].strip()
            delimiter = block["delimiter"]

            if not content:
                continue

            # Skip DELIMITER statements themselves
            if content.upper().startswith("DELIMITER"):
                continue

            # With custom delimiter, each extracted block already ends at a delimiter.
            # Treat the whole block content as a single statement.
            if delimiter != ";":
                if content and not self._is_empty_or_comment(content):
                    statements.append(content)
            else:
                # Standard semicolon - split normally
                sub_statements = self._split_by_semicolon_mysql(content)
                statements.extend(sub_statements)

        return statements

    def _split_with_procedure_awareness(self, sql: str) -> List[str]:
        """Split SQL with stored procedure/function/event/trigger awareness."""
        # First check if we have CREATE PROCEDURE/FUNCTION/EVENT/TRIGGER with BEGIN...END
        # If not, use the more robust semicolon splitter
        has_begin_end = bool(
            re.search(
                r"\b(?:CREATE|ALTER)\s+(?:PROCEDURE|FUNCTION|EVENT|TRIGGER)\b.*\bBEGIN\b",
                sql,
                re.IGNORECASE | re.DOTALL,
            )
        )

        if not has_begin_end:
            # No BEGIN...END blocks, use regular semicolon splitting
            return self._split_by_semicolon_mysql(sql)

        # Has BEGIN...END, use line-by-line procedure-aware splitting
        statements = []
        current_statement = []
        lines = sql.split("\n")

        in_procedure = False
        begin_depth = 0

        for line in lines:
            line_stripped = line.strip()

            # Check for procedure/function/event/trigger start
            if re.match(
                r"^\s*(?:CREATE|ALTER)\s+(?:PROCEDURE|FUNCTION|EVENT|TRIGGER)\b",
                line_stripped,
                re.IGNORECASE,
            ):
                in_procedure = True
                begin_depth = 0

            # Track BEGIN/END depth in procedures/events/triggers
            if in_procedure:
                begin_matches = len(re.findall(r"\bBEGIN\b", line_stripped, re.IGNORECASE))
                end_matches = len(re.findall(r"\bEND\b", line_stripped, re.IGNORECASE))
                begin_depth += begin_matches - end_matches

            current_statement.append(line)

            # Check for statement end
            if line_stripped.endswith(";"):
                if not in_procedure or begin_depth <= 0:
                    # End of statement
                    stmt = "\n".join(current_statement).strip()
                    if stmt and not self._is_empty_or_comment(stmt):
                        statements.append(stmt)
                    current_statement = []
                    in_procedure = False
                    begin_depth = 0

        # Add any remaining statement
        if current_statement:
            stmt = "\n".join(current_statement).strip()
            if stmt and not self._is_empty_or_comment(stmt):
                statements.append(stmt)

        return statements

    def _split_by_semicolon_mysql(self, sql: str) -> List[str]:
        """Enhanced semicolon splitting with MySQL backtick identifier support."""
        statements = []
        current = []
        in_string = False
        in_backtick = False
        in_line_comment = False
        in_block_comment = False
        string_char = None
        i = 0

        while i < len(sql):
            char = sql[i]

            # Handle string literals
            if not in_line_comment and not in_block_comment and not in_backtick:
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

            # Handle backtick identifiers
            if not in_string and not in_line_comment and not in_block_comment:
                if not in_backtick and char == "`":
                    in_backtick = True
                elif in_backtick and char == "`":
                    in_backtick = False

            # Handle comments
            if not in_string and not in_backtick:
                # Hash comments
                if char == "#":
                    in_line_comment = True
                    current.append(char)
                    i += 1
                    continue
                # -- comments
                elif char == "-" and i + 1 < len(sql) and sql[i + 1] == "-":
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
                and not in_backtick
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

    def _extract_delimiter_statement(self, sql: str) -> Optional[str]:
        """Extract DELIMITER statement if present."""
        match = re.search(r"^\s*DELIMITER\s+(.+)\s*$", sql, re.IGNORECASE | re.MULTILINE)
        if match:
            return match.group(1).strip()
        return None

    def _extract_backtick_identifier(self, sql: str) -> Optional[str]:
        """Extract backtick-quoted identifier from SQL."""
        identifiers = self.config.extract_backtick_identifiers(sql)
        return identifiers[0] if identifiers else None

    def _extract_stored_procedure_name(self, sql: str) -> Optional[str]:
        """Extract stored procedure name from CREATE PROCEDURE statement."""
        match = re.search(
            r"\b(?:CREATE|ALTER)\s+(?:DEFINER\s*=\s*[^@]+@[^\s]+\s+)?PROCEDURE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:`([^`]+)`|([a-zA-Z_][a-zA-Z0-9_]*))(?:\.(?:`([^`]+)`|([a-zA-Z_][a-zA-Z0-9_]*)))?",
            sql,
            re.IGNORECASE,
        )
        if match:
            # Return the first non-None group
            return next((g for g in match.groups() if g), None)
        return None

    def _extract_stored_function_name(self, sql: str) -> Optional[str]:
        """Extract stored function name from CREATE FUNCTION statement."""
        match = re.search(
            r"\b(?:CREATE|ALTER)\s+(?:DEFINER\s*=\s*[^@]+@[^\s]+\s+)?FUNCTION\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:`([^`]+)`|([a-zA-Z_][a-zA-Z0-9_]*))(?:\.(?:`([^`]+)`|([a-zA-Z_][a-zA-Z0-9_]*)))?",
            sql,
            re.IGNORECASE,
        )
        if match:
            # Return the first non-None group
            return next((g for g in match.groups() if g), None)
        return None

    def parse_sql(self, sql_content: str, default_schema: Optional[str] = None) -> ParseResult:
        """Parse SQL content with MySQL-specific enhancements.

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
            cleaned_sql = self._clean_mysql_comments(sql_content)

            # Enhanced statement splitting
            sql_statements = self.split_statements(cleaned_sql)

            # Parse each statement with MySQL-specific handling
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
                    error_msg = f"Error parsing MySQL statement: {str(e)}"
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
            error_msg = f"Error splitting MySQL SQL: {str(e)}"
            logger.error(error_msg)
            errors.append(error_msg)

        # Return success if we got statements, even with some errors
        success = len(statements) > 0 or len(errors) == 0
        return ParseResult(success=success, statements=statements, errors=errors)

    def validate_sql(self, sql_content: str) -> Dict[str, Any]:
        """Validate MySQL SQL content.

        Args:
            sql_content: SQL content to validate

        Returns:
            Dictionary with validation results
        """
        try:
            # Parse the SQL
            result = self.parse_sql(sql_content)

            # Check for parsing errors
            if result.errors:
                return {
                    "valid": False,
                    "errors": result.errors,
                    "statement_count": len(result.statements) if result.statements else 0,
                }

            # Basic structural validation
            if not result.statements:
                return {
                    "valid": False,
                    "errors": ["No valid statements found"],
                    "statement_count": 0,
                }

            # Check for MySQL-specific syntax issues
            mysql_errors = []
            for stmt in result.statements:
                mysql_errors.extend(self._validate_mysql_syntax(stmt.sql_text))

            if mysql_errors:
                return {
                    "valid": False,
                    "errors": mysql_errors,
                    "statement_count": len(result.statements) if result.statements else 0,
                }

            return {
                "valid": True,
                "errors": [],
                "statement_count": len(result.statements) if result.statements else 0,
            }

        except Exception as e:
            return {
                "valid": False,
                "errors": [f"MySQL validation error: {str(e)}"],
                "statement_count": 0,
            }

    def _validate_mysql_syntax(self, sql: str) -> List[str]:
        """Validate MySQL-specific syntax."""
        errors = []

        # Check for unmatched backticks
        backtick_count = sql.count("`")
        if backtick_count % 2 != 0:
            errors.append("Unmatched backtick identifier")

        # Check for unmatched DELIMITER statements
        delimiter_matches = re.findall(r"^\s*DELIMITER\s+", sql, re.IGNORECASE | re.MULTILINE)
        if len(delimiter_matches) > 1:
            errors.append("Multiple DELIMITER statements in single statement")

        # Check for invalid MySQL keywords in wrong contexts
        if re.search(r"\bDELIMITER\b", sql, re.IGNORECASE) and not re.search(
            r"^\s*DELIMITER\s+", sql, re.IGNORECASE
        ):
            errors.append("DELIMITER keyword used outside of DELIMITER statement")

        return errors
