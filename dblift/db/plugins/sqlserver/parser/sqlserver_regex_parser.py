"""SQL Server parser using tokenization-based parsing.

This module provides a SQL Server parser that uses tokenization for robust
statement splitting with fallback to regex.
"""

import logging
import re
from typing import Any, Dict, List, Optional

from dblift.core.sql_model.base import (
    ParseResult,
)
from dblift.core.sql_parser.enhanced_regex_parser import EnhancedRegexParser
from dblift.core.sql_parser.parser_context import ParserContext
from dblift.db.plugins.sqlserver.parser.parser_config import SqlServerConfig
from dblift.db.plugins.sqlserver.parser.sqlserver_statement_parser import SQLServerStatementParser
from dblift.db.plugins.sqlserver.parser.sqlserver_tokenizer import SQLServerTokenizer

logger = logging.getLogger(__name__)


class SqlServerRegexParser(EnhancedRegexParser):
    """
    SQL Server parser using regex-based approach with intelligent splitting.

    This parser combines:
    - Universal regex framework from EnhancedRegexParser
    - SQL Server dialect configuration patterns
    - Proven intelligent splitting logic from original parser
    - GO batch separator handling
    - DDL block-aware statement detection
    """

    def __init__(self) -> None:
        """Initialize SQL Server regex parser."""
        super().__init__(SqlServerConfig())  # type: ignore[no-untyped-call,arg-type]
        logger.debug("SQL Server regex parser initialized")

    @property
    def dialect_name(self) -> str:
        """Return the dialect name."""
        return "sqlserver"  # lint: allow-dialect-string: dialect dispatch

    def split_statements(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """Split SQL content using tokenization-based logic.

        Uses tokenization to handle:
        1. GO batch separators
        2. BEGIN/END blocks
        3. BEGIN TRANSACTION vs BEGIN block disambiguation
        4. Preserve block statements (procedures, functions, etc.)

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
            tokenizer = SQLServerTokenizer(sql_content, strict_unknown_chars=strict_tokenizer)
            tokens = tokenizer.tokenize()

            context = ParserContext()
            parser = SQLServerStatementParser(tokens, context)

            statements = parser.split_statements()
            logger.debug(f"SQL Server: Tokenization split into {len(statements)} statements")
            return statements

        except Exception as e:
            if strict_tokenizer:
                raise
            # Fallback to old regex-based splitting if tokenization fails
            logger.warning(f"SQL Server tokenization failed, falling back to regex: {str(e)}")

        logger.debug(
            f"[ENTRY] SQL Server split_statements called with input: {repr(sql_content[:100])}..."
        )

        if not sql_content.strip():
            return []

        # Check if this is a batch script with GO statements
        if re.search(r"(?i)^\s*GO\s*(?:--.*)?$", sql_content, flags=re.MULTILINE):
            logger.debug("[SPLIT] Using SQL Server GO batch splitting")
            return self._split_sqlserver_with_go(sql_content)

        # Use intelligent batch splitting that preserves DDL blocks
        logger.debug("[SPLIT] Using SQL Server intelligent batch splitting")
        return self._split_batch_intelligently(sql_content)

    def _split_sqlserver_with_go(self, sql_content: str) -> List[str]:
        """Split SQL content on GO statements (preserved from original parser).

        This method implements the exact logic from the original SQL Server parser
        for handling GO batch separators.
        """
        logger.debug("[ENTRY] _split_sqlserver_with_go called")

        # Split on GO statements (case-insensitive, at line start, with optional whitespace and comments)
        batches = re.split(r"(?im)^\s*GO\s*(?:--.*)?$", sql_content)

        statements: List[str] = []

        for batch in batches:
            # Skip completely empty batches
            if not batch.strip():
                continue

            # Split the batch into lines
            lines = batch.splitlines()
            cleaned_lines = []

            # Process each line - keep only non-GO lines and non-empty lines
            for line in lines:
                line_stripped = line.strip()
                # Skip if this line is a GO statement (possibly with comments)
                if re.match(r"(?i)^GO\s*(?:--.*)?$", line_stripped):
                    continue
                # Include all lines (including empty ones) for formatting
                cleaned_lines.append(line)

            # Skip batches with no content
            if not cleaned_lines:
                continue

            # Check if there's at least one non-comment line
            has_content = any(
                line.strip() and not line.strip().startswith("--") for line in cleaned_lines
            )
            if not has_content:
                continue

            # Join the cleaned lines into a single batch
            batch_content = "\n".join(cleaned_lines).strip()
            if batch_content:
                logger.debug(f"[SPLIT] Processing GO batch: {repr(batch_content[:100])}...")
                # Further split each batch on semicolons, but preserve DDL blocks
                batch_statements = self._split_batch_intelligently(batch_content)
                statements.extend(batch_statements)

        logger.debug(f"[SPLIT] _split_sqlserver_with_go output: {len(statements)} statements")
        return statements

    def _split_batch_intelligently(self, batch_content: str) -> List[str]:
        """Intelligent batch splitting that preserves DDL blocks (preserved from original parser).

        This method implements the exact logic from the original SQL Server parser
        for intelligent DDL-aware statement splitting.
        """
        logger.debug("[ENTRY] _split_batch_intelligently called")
        statements: List[str] = []
        batch_content = batch_content.strip()

        if not batch_content:
            return statements

        # DDL keywords for splitting (preserved from original parser)
        ddl_keywords = [
            "CREATE TABLE",
            "CREATE OR ALTER TABLE",
            "CREATE PROCEDURE",
            "CREATE OR ALTER PROCEDURE",
            "CREATE FUNCTION",
            "CREATE OR ALTER FUNCTION",
            "CREATE TRIGGER",
            "CREATE OR ALTER TRIGGER",
            "CREATE VIEW",
            "CREATE OR ALTER VIEW",
            "CREATE INDEX",
            "ALTER TABLE",
            "ALTER PROCEDURE",
            "ALTER FUNCTION",
            "ALTER VIEW",
            "DROP TABLE",
            "DROP PROCEDURE",
            "DROP FUNCTION",
            "DROP VIEW",
            "DROP INDEX",
        ]

        # If this batch contains any DDL keywords, we need special handling
        batch_upper = batch_content.upper()
        contains_ddl = any(keyword in batch_upper for keyword in ddl_keywords)
        logger.debug(f"[DDL DETECTION] Batch contains DDL: {contains_ddl}")

        if contains_ddl:
            logger.debug("[DDL DETECTION] Checking for multiple DDL statements")

            # Build regex to match DDL keywords at the start of a line (ignoring leading whitespace)
            ddl_pattern = r"^\s*(" + r"|".join([re.escape(k) for k in ddl_keywords]) + r")"
            matches = list(re.finditer(ddl_pattern, batch_upper, re.MULTILINE))

            logger.debug(f"[DDL DETECTION] Found {len(matches)} DDL matches")

            if len(matches) > 1:
                logger.debug(f"[DDL DETECTION] Splitting {len(matches)} DDL statements")
                split_positions = [m.start() for m in matches] + [len(batch_content)]

                for i in range(len(split_positions) - 1):
                    part = batch_content[split_positions[i] : split_positions[i + 1]].strip()
                    if part:
                        statements.append(part)
                return statements
            else:
                logger.debug("[DDL DETECTION] Single DDL statement, treating as single batch")
                statements.append(batch_content)
                return statements

        # For non-DDL batches, split by semicolon using safe parsing
        non_ddl_statements = self._split_non_ddl_statements(batch_content)
        statements.extend(non_ddl_statements)

        logger.debug(f"[SPLIT] _split_batch_intelligently output: {len(statements)} statements")
        return statements

    def _split_non_ddl_statements(self, batch_content: str) -> List[str]:
        """Split non-DDL statements by semicolon (preserved from original parser).

        This method uses safe semicolon detection that respects strings,
        identifiers, and comments.
        """
        logger.debug("[ENTRY] _split_non_ddl_statements called")
        statements = []
        safe_indices = self._find_safe_semicolon_splits(batch_content)

        logger.debug(f"[SPLIT] Found {len(safe_indices)} safe semicolon positions")

        if not safe_indices:
            # No safe semicolons found, return the whole batch as a single statement
            if batch_content:
                return [batch_content]
            return []

        last_idx = 0
        for idx in safe_indices:
            stmt = batch_content[last_idx : idx + 1].strip()
            if stmt:
                statements.append(stmt)
            last_idx = idx + 1

        # Add any remaining statement
        if last_idx < len(batch_content):
            stmt = batch_content[last_idx:].strip()
            if stmt:
                statements.append(stmt)

        logger.debug(f"[SPLIT] _split_non_ddl_statements output: {len(statements)} statements")
        return statements

    def _find_safe_semicolon_splits(self, sql: str) -> List[int]:
        """Find semicolons outside of strings, identifiers, and comments (preserved from original parser).

        This method implements the exact logic from the original SQL Server parser
        for finding safe semicolon split positions.
        """
        safe_indices = []
        in_string = False
        in_identifier = False
        in_line_comment = False
        in_block_comment = False
        i = 0

        while i < len(sql):
            char = sql[i]

            # Handle string literals
            if char == "'" and not in_line_comment and not in_block_comment:
                in_string = not in_string
                i += 1
                continue

            # Handle SQL Server identifiers [...]
            elif char == "[" and not in_string and not in_line_comment and not in_block_comment:
                in_identifier = True
                i += 1
                continue
            elif char == "]" and in_identifier:
                in_identifier = False
                i += 1
                continue

            # Handle line comments --
            elif (
                char == "-"
                and i < len(sql) - 1
                and sql[i + 1] == "-"
                and not in_string
                and not in_identifier
                and not in_block_comment
            ):
                in_line_comment = True
                i += 2
                continue

            # Handle block comments /* ... */
            elif (
                char == "/"
                and i < len(sql) - 1
                and sql[i + 1] == "*"
                and not in_string
                and not in_identifier
                and not in_line_comment
            ):
                in_block_comment = True
                i += 2
                continue
            elif char == "*" and i < len(sql) - 1 and sql[i + 1] == "/" and in_block_comment:
                in_block_comment = False
                i += 2
                continue

            # End line comments at newline
            elif char in ["\n", "\r"] and in_line_comment:
                in_line_comment = False
                i += 1
                continue

            # Safe semicolon
            if (
                char == ";"
                and not in_string
                and not in_identifier
                and not in_line_comment
                and not in_block_comment
            ):
                safe_indices.append(i)

            i += 1

        return safe_indices

    def parse_sql(self, sql_content: str, default_schema: Optional[str] = None) -> ParseResult:
        """Parse SQL content using SQL Server regex-based approach.

        This method combines the enhanced regex parsing with SQL Server-specific
        intelligent splitting logic.
        """
        logger.debug("[ENTRY] SQL Server parse_sql called")

        # Use SQL Server default schema if none provided
        if default_schema is None:
            default_schema = "dbo"

        # Use the enhanced regex parser's parse_sql method
        return super().parse_sql(sql_content, default_schema)

    def validate_sql(self, sql_content: str) -> Dict[str, Any]:
        """Validate SQL content using SQL Server regex-based validation.

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
