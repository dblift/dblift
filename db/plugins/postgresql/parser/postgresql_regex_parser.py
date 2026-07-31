"""PostgreSQL regex-based parser implementation.

This module provides a tokenization-based PostgreSQL parser with fallback to regex
for complex PostgreSQL features.
"""

import logging
import re
from typing import Any, Dict, List, Optional

from core.sql_model.base import (
    ParseResult,
    SqlStatement,
    SqlStatementType,
)
from core.sql_parser.enhanced_regex_parser import EnhancedRegexParser
from core.sql_parser.parser_context import ParserContext
from db.plugins.postgresql.parser.parser_config import PostgreSqlConfig
from db.plugins.postgresql.parser.postgresql_statement_parser import PostgreSQLStatementParser
from db.plugins.postgresql.parser.postgresql_tokenizer import PostgreSQLTokenizer

logger = logging.getLogger(__name__)


class PostgreSqlRegexParser(EnhancedRegexParser):
    """PostgreSQL regex-based parser with comprehensive PostgreSQL support."""

    dialect_name = "postgresql"  # lint: allow-dialect-string: dialect dispatch

    def __init__(self) -> None:
        """Initialize PostgreSQL regex parser."""
        # Initialize with PostgreSQL configuration
        config = PostgreSqlConfig()
        super().__init__(config)  # type: ignore[arg-type]

        # Store PostgreSQL-specific config for easy access
        self.postgresql_config = config

        # Set dialect attribute expected by tests
        self._dialect = "postgresql"  # lint: allow-dialect-string: dialect dispatch

        logger.debug("PostgreSQL regex parser initialized")

    def split_statements(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """Split SQL content into statements using tokenization.

        Handles:
        - Dollar-quoted function/procedure definitions
        - PL/pgSQL blocks with nested BEGIN/END
        - COPY statements with data blocks
        - Standard semicolon-separated statements

        Uses tokenization-based approach for robust parsing with fallback to regex.
        """
        if not sql_content or not sql_content.strip():
            return []

        try:
            # Use tokenization-based splitting
            tokenizer = PostgreSQLTokenizer(sql_content, strict_unknown_chars=strict_tokenizer)
            tokens = tokenizer.tokenize()

            context = ParserContext()
            parser = PostgreSQLStatementParser(tokens, context)

            statements = parser.split_statements()
            logger.debug(f"PostgreSQL: Tokenization split into {len(statements)} statements")
            return statements

        except Exception as e:
            if strict_tokenizer:
                raise
            # Fallback to old regex-based splitting if tokenization fails
            logger.warning(f"PostgreSQL tokenization failed, falling back to regex: {str(e)}")

        # Fallback: Remove comments with awareness of strings and dollar-quoted blocks
        cleaned_sql = self._remove_comments(sql_content)

        # Split by semicolons while respecting quotes and dollar-quoted blocks
        statements = self._split_by_semicolon(cleaned_sql)
        return self._filter_empty_statements(statements)

    def _extract_dollar_quoted_function(self, sql: str) -> Optional[str]:
        """Extract a complete function definition with dollar quoting."""
        # Look for the first dollar quote
        dollar_match = re.search(r"\$([a-zA-Z_][a-zA-Z0-9_]*)?\$", sql)
        if not dollar_match:
            return None

        dollar_tag = dollar_match.group(0)
        dollar_match.start()

        # Find the matching closing dollar quote
        after_dollar = sql[dollar_match.end() :]
        dollar_end_match = re.search(re.escape(dollar_tag), after_dollar)

        if not dollar_end_match:
            return None

        dollar_end_pos = dollar_match.end() + dollar_end_match.end()

        # Look for LANGUAGE clause after the closing dollar quote
        after_dollar_end = sql[dollar_end_pos:]

        # Match LANGUAGE clause with optional function attributes
        language_match = re.match(
            r'\s*LANGUAGE\s+(?:[\'"][\w-]+[\'"]|[\w-]+)(?:\s+[\w\s,()]*?)?\s*;',
            after_dollar_end,
            re.IGNORECASE,
        )

        if language_match:
            complete_end = dollar_end_pos + language_match.end()
        else:
            # Look for semicolon to end the function
            semicolon_match = re.match(r"\s*;", after_dollar_end)
            if semicolon_match:
                complete_end = dollar_end_pos + semicolon_match.end()
            else:
                complete_end = dollar_end_pos

        return sql[:complete_end].strip()

    def _extract_do_block(self, sql: str) -> Optional[str]:
        """Extract a complete DO block with dollar quoting."""
        # Look for DO $$ pattern
        do_match = re.match(r"DO\s+\$\$", sql, re.IGNORECASE)
        if not do_match:
            return None

        # Find the matching closing $$
        after_do = sql[do_match.end() :]
        end_match = re.search(r"\$\$", after_do)

        if not end_match:
            return None

        # Look for optional LANGUAGE clause after $$
        end_pos = do_match.end() + end_match.end()
        after_end = sql[end_pos:]

        # Check for optional LANGUAGE clause
        language_match = re.match(r"\s*LANGUAGE\s+[\w-]+\s*;?", after_end, re.IGNORECASE)

        if language_match:
            complete_end = end_pos + language_match.end()
        else:
            # Look for semicolon
            semicolon_match = re.match(r"\s*;", after_end)
            if semicolon_match:
                complete_end = end_pos + semicolon_match.end()
            else:
                complete_end = end_pos

        return sql[:complete_end].strip()

    def _extract_copy_statement(self, sql: str) -> Optional[str]:
        """Extract a complete COPY statement, handling data blocks."""
        # Basic COPY statement pattern
        copy_match = re.match(r"COPY\s+(?:\([^)]+\)|[^(]+?)\s+(?:FROM|TO)\s+", sql, re.IGNORECASE)

        if not copy_match:
            return None

        # Look for STDIN/STDOUT or file path
        after_copy = sql[copy_match.end() :]

        # Check for STDIN (indicates data follows)
        if re.match(r"STDIN", after_copy, re.IGNORECASE):
            # Look for data block ending with \. on a line by itself
            data_end = re.search(r"\n\\\.(?:\s*\n|$)", after_copy)
            if data_end:
                return sql[: copy_match.end() + data_end.end()].strip()

        # For other COPY statements, look for semicolon
        semicolon_match = re.search(r";", after_copy)
        if semicolon_match:
            return sql[: copy_match.end() + semicolon_match.end()].strip()

        # If no semicolon found, return the whole remaining content
        return sql.strip()

    def _split_by_semicolon(self, sql: str) -> List[str]:
        """Split SQL by semicolon, respecting PostgreSQL string literals and comments."""
        statements = []
        current_statement = ""
        i = 0

        while i < len(sql):
            char = sql[i]

            # Handle PostgreSQL escape string literals (E'...')
            if char == "E" and i + 1 < len(sql) and sql[i + 1] == "'":
                current_statement += char
                i += 1
                current_statement += sql[i]  # Add the quote
                i += 1

                # Find end of escape string literal
                while i < len(sql):
                    current_statement += sql[i]
                    if sql[i] == "\\" and i + 1 < len(sql):
                        # Escaped character
                        i += 1
                        current_statement += sql[i]
                    elif sql[i] == "'":
                        break
                    i += 1
                i += 1
                continue

            # Handle regular string literals
            elif char == "'":
                current_statement += char
                i += 1

                # Find end of string literal
                while i < len(sql):
                    current_statement += sql[i]
                    if sql[i] == "'":
                        if i + 1 < len(sql) and sql[i + 1] == "'":
                            # Doubled quote (escaped)
                            i += 1
                            current_statement += sql[i]
                        else:
                            break
                    i += 1
                i += 1
                continue

            # Handle double-quoted identifiers
            elif char == '"':
                current_statement += char
                i += 1

                # Find end of identifier
                while i < len(sql):
                    current_statement += sql[i]
                    if sql[i] == '"':
                        if i + 1 < len(sql) and sql[i + 1] == '"':
                            # Doubled quote (escaped)
                            i += 1
                            current_statement += sql[i]
                        else:
                            break
                    i += 1
                i += 1
                continue

            # Handle dollar quoting
            elif char == "$":
                # Check for dollar quote tag
                tag_match = re.match(r"\$([a-zA-Z_][a-zA-Z0-9_]*)?\$", sql[i:])
                if tag_match:
                    tag = tag_match.group(0)
                    current_statement += tag
                    i += len(tag)

                    # Find matching closing tag
                    while i < len(sql):
                        if sql[i : i + len(tag)] == tag:
                            current_statement += tag
                            i += len(tag)
                            break
                        else:
                            current_statement += sql[i]
                            i += 1
                    continue
                else:
                    current_statement += char
                    i += 1
                    continue

            # Handle semicolon (statement separator)
            elif char == ";":
                current_statement += char
                stmt = current_statement.strip()
                if stmt:
                    statements.append(stmt)
                current_statement = ""
                i += 1
                continue

            else:
                current_statement += char
                i += 1

        # Add final statement if any
        final_stmt = current_statement.strip()
        if final_stmt:
            statements.append(final_stmt)

        return statements

    def _filter_empty_statements(self, statements: List[str]) -> List[str]:
        """Filter out empty statements and comments."""
        filtered = []
        for stmt in statements:
            stmt = stmt.strip()
            if stmt and not self._is_empty_or_comment(stmt) and stmt != ";":
                filtered.append(stmt)
        return filtered

    def _is_empty_or_comment(self, stmt: str) -> bool:
        """Check if statement is empty or just comments."""
        stmt = stmt.strip()
        if not stmt:
            return True

        # Check if it's just comments
        lines = stmt.split("\n")
        for line in lines:
            line = line.strip()
            if (
                line
                and not line.startswith("--")
                and not (line.startswith("/*") and line.endswith("*/"))
            ):
                return False
        return True

    def _remove_comments(self, sql: str) -> str:
        """Remove SQL comments while preserving content inside quotes.

        This implementation tracks state across the entire script and ignores
        comment markers when inside single quotes, double quotes, or
        dollar-quoted strings (e.g., $tag$ ... $tag$).
        """
        result_chars: List[str] = []

        in_single_quote = False
        in_double_quote = False
        in_line_comment = False
        in_block_comment = False
        block_depth = 0
        dollar_tag: Optional[str] = None

        i = 0
        length = len(sql)

        while i < length:
            ch = sql[i]

            # End of line comment
            if in_line_comment:
                if ch in ("\n", "\r"):
                    in_line_comment = False
                    result_chars.append(ch)
                i += 1
                continue

            # End or nested block comments
            if in_block_comment:
                # Handle nested start
                if ch == "/" and i + 1 < length and sql[i + 1] == "*":
                    block_depth += 1
                    i += 2
                    continue
                # Handle end of current level
                if ch == "*" and i + 1 < length and sql[i + 1] == "/":
                    block_depth -= 1
                    i += 2
                    if block_depth <= 0:
                        in_block_comment = False
                        block_depth = 0
                    continue
                # Skip content within block comments
                i += 1
                continue

            # Inside dollar-quoted string: consume until matching tag
            if dollar_tag is not None:
                # Look ahead for closing tag match at current position
                if sql.startswith(dollar_tag, i):
                    result_chars.append(dollar_tag)
                    i += len(dollar_tag)
                    dollar_tag = None
                    continue
                # Otherwise, copy character
                result_chars.append(ch)
                i += 1
                continue

            # Handle start of dollar-quoted string (only when not in any comment/quote)
            if ch == "$" and not in_single_quote and not in_double_quote:
                # Match $tag$ or $$
                m = re.match(r"\$([a-zA-Z_][a-zA-Z0-9_]*)?\$", sql[i:])
                if m:
                    tag = m.group(0)  # includes the $...$
                    dollar_tag = tag
                    result_chars.append(tag)
                    i += len(tag)
                    continue

            # Handle start/end of single-quoted string
            if ch == "'" and not in_double_quote:
                result_chars.append(ch)
                i += 1
                # Handle doubled single-quote escape inside string
                if in_single_quote and i < length and sql[i : i + 1] == "'":
                    result_chars.append("'")
                    i += 1
                else:
                    in_single_quote = not in_single_quote
                continue

            # Handle start/end of double-quoted identifier
            if ch == '"' and not in_single_quote:
                result_chars.append(ch)
                i += 1
                # Handle doubled double-quote escape inside identifier
                if in_double_quote and i < length and sql[i : i + 1] == '"':
                    result_chars.append('"')
                    i += 1
                else:
                    in_double_quote = not in_double_quote
                continue

            # If not inside any quote, handle comment starts
            if not in_single_quote and not in_double_quote:
                # Line comment --
                if ch == "-" and i + 1 < length and sql[i + 1] == "-":
                    in_line_comment = True
                    i += 2
                    continue
                # Block comment /* ... */
                if ch == "/" and i + 1 < length and sql[i + 1] == "*":
                    in_block_comment = True
                    block_depth = 1
                    i += 2
                    continue

            # Default: copy character
            result_chars.append(ch)
            i += 1

        return "".join(result_chars)

    def _identify_statement_type(self, sql: str) -> SqlStatementType:
        """Identify PostgreSQL statement type using regex patterns."""
        if not sql or not sql.strip():
            return SqlStatementType.UNKNOWN

        sql = sql.strip()

        # Check DDL statements
        if self.postgresql_config.is_ddl_statement(sql):
            return SqlStatementType.DDL

        # Check DML statements
        if self.postgresql_config.is_dml_statement(sql):
            return SqlStatementType.DML

        # Check query statements
        if self.postgresql_config.is_query_statement(sql):
            return SqlStatementType.QUERY

        # Check transaction control
        transaction_keywords = self.postgresql_config.get_transaction_keywords()
        words = sql.split()
        if not words:
            # Defensive guard: unreachable in practice (outer guard + strip() guarantee
            # non-empty sql here), but protects against future refactoring of this method.
            return SqlStatementType.UNKNOWN
        first_word = words[0].upper()
        if first_word in transaction_keywords:
            return SqlStatementType.DDL  # Transaction control is treated as DDL

        return SqlStatementType.UNKNOWN

    def parse_sql(
        self,
        sql_content: str,
        default_schema: Optional[str] = None,
        placeholders: Optional[Dict[str, Any]] = None,
    ) -> ParseResult:
        """Parse SQL content into statements using regex-based approach."""
        # Handle placeholders if provided
        if placeholders:
            for key, value in placeholders.items():
                placeholder_pattern = f"${{{key}}}"
                sql_content = sql_content.replace(placeholder_pattern, str(value))

        try:
            # Split statements using PostgreSQL-specific logic
            statements = self.split_statements(sql_content)

            # Create SqlStatement objects
            sql_statements = []
            errors = []

            for stmt_text in statements:
                try:
                    # Create statement object
                    statement = SqlStatement(
                        sql_text=stmt_text,
                        statement_type=self._identify_statement_type(stmt_text),
                        affected_objects=self.get_affected_objects(stmt_text, default_schema),
                    )
                    sql_statements.append(statement)

                except Exception as e:
                    error_msg = f"Error processing statement: {str(e)}"
                    errors.append(error_msg)
                    logger.warning(error_msg)

            return ParseResult(
                statements=sql_statements,
                errors=errors,
                success=len(errors) == 0,
            )

        except Exception as e:
            error_msg = f"PostgreSQL regex parser error: {str(e)}"
            logger.error(error_msg)
            return ParseResult(statements=[], errors=[error_msg], success=False)

    def validate_sql(self, sql_content: str) -> Dict[str, Any]:
        """Validate SQL content using structural checks."""
        errors = []

        try:
            # Basic structural validation
            statements = self.split_statements(sql_content)

            for stmt in statements:
                # Check for basic syntax issues
                if not stmt.strip():
                    continue

                # Check for unmatched quotes
                if self._has_unmatched_quotes(stmt):
                    errors.append(f"Unmatched quotes in statement: {stmt[:50]}...")

                # Check for unmatched parentheses
                if self._has_unmatched_parentheses(stmt):
                    errors.append(f"Unmatched parentheses in statement: {stmt[:50]}...")

                # Check for unmatched dollar quotes
                if self._has_unmatched_dollar_quotes(stmt):
                    errors.append(f"Unmatched dollar quotes in statement: {stmt[:50]}...")

        except Exception as e:
            errors.append(f"Validation error: {str(e)}")

        return {"success": len(errors) == 0, "errors": errors}

    def _has_unmatched_quotes(self, sql: str) -> bool:
        """Check for unmatched single or double quotes, respecting dollar quotes."""
        in_single_quote = False
        in_double_quote = False
        dollar_tag: Optional[str] = None
        i = 0

        while i < len(sql):
            char = sql[i]

            # Handle dollar-quoted strings first (highest priority)
            if char == "$" and not in_single_quote and not in_double_quote:
                if dollar_tag is None:
                    # Check for opening dollar quote
                    m = re.match(r"\$([a-zA-Z_][a-zA-Z0-9_]*)?\$", sql[i:])
                    if m:
                        dollar_tag = m.group(0)
                        i += len(dollar_tag)
                        continue
                else:
                    # Check for closing dollar quote
                    if sql.startswith(dollar_tag, i):
                        i += len(dollar_tag)
                        dollar_tag = None
                        continue

            # Only process quotes outside dollar-quoted strings
            if dollar_tag is None:
                # Handle single quotes
                if char == "'" and not in_double_quote:
                    # Check for escaped single quote
                    if i + 1 < len(sql) and sql[i + 1] == "'":
                        i += 2
                        continue
                    in_single_quote = not in_single_quote
                    i += 1
                    continue

                # Handle double quotes
                if char == '"' and not in_single_quote:
                    # Check for escaped double quote
                    if i + 1 < len(sql) and sql[i + 1] == '"':
                        i += 2
                        continue
                    in_double_quote = not in_double_quote
                    i += 1
                    continue

            i += 1

        # Check if we ended in a valid state
        return in_single_quote or in_double_quote or dollar_tag is not None

    def _has_unmatched_parentheses(self, sql: str) -> bool:
        """Check for unmatched parentheses, respecting all quote types."""
        count = 0
        in_single_quote = False
        in_double_quote = False
        dollar_tag: Optional[str] = None
        i = 0

        while i < len(sql):
            char = sql[i]

            # Handle dollar-quoted strings
            if char == "$" and not in_single_quote and not in_double_quote:
                if dollar_tag is None:
                    # Check for opening dollar quote
                    m = re.match(r"\$([a-zA-Z_][a-zA-Z0-9_]*)?\$", sql[i:])
                    if m:
                        dollar_tag = m.group(0)
                        i += len(dollar_tag)
                        continue
                else:
                    # Check for closing dollar quote
                    if sql.startswith(dollar_tag, i):
                        i += len(dollar_tag)
                        dollar_tag = None
                        continue

            # Handle single quotes
            if char == "'" and not in_double_quote and dollar_tag is None:
                # Check for escaped single quote
                if i + 1 < len(sql) and sql[i + 1] == "'":
                    i += 2
                    continue
                in_single_quote = not in_single_quote
                i += 1
                continue

            # Handle double quotes
            if char == '"' and not in_single_quote and dollar_tag is None:
                # Check for escaped double quote
                if i + 1 < len(sql) and sql[i + 1] == '"':
                    i += 2
                    continue
                in_double_quote = not in_double_quote
                i += 1
                continue

            # Count parentheses only when not in any quote
            if not in_single_quote and not in_double_quote and dollar_tag is None:
                if char == "(":
                    count += 1
                elif char == ")":
                    count -= 1
                    if count < 0:
                        return True

            i += 1

        return count != 0

    def _has_unmatched_dollar_quotes(self, sql: str) -> bool:
        """Check for unmatched dollar quotes."""
        dollar_quotes = self.postgresql_config.extract_dollar_quoted_blocks(sql)

        # If we successfully extracted blocks, then quotes are matched
        # If extraction failed, there might be unmatched quotes
        for block in dollar_quotes:
            if not block.get("content"):
                return True

        return False
