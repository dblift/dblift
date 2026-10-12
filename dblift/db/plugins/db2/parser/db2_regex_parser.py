"""DB2 object parser backed by the CLP-aware script scanner."""

import logging
import re
from typing import Any, Dict, List, Optional, Type

from dblift.core.sql_model.base import ParseResult, SqlStatement, SqlStatementType
from dblift.core.sql_parser.base_tokenizer import BaseTokenizer
from dblift.core.sql_parser.enhanced_regex_parser import EnhancedRegexParser
from dblift.core.sql_parser.statement import Statement, analysis_sql
from dblift.db.plugins.db2.parser._script import scan_script
from dblift.db.plugins.db2.parser.parser_config import DB2Config

logger = logging.getLogger(__name__)


class _DB2NestingCommentTokenizer(BaseTokenizer):
    """Carries only the flag: Db2 nests ``/* ... */`` (checked with the CLP
    and ``ibm_db``). The Db2 splitter scans characters itself and never
    instantiates a tokenizer."""

    NESTED_BLOCK_COMMENTS = True


class DB2RegexParser(EnhancedRegexParser):
    """DB2-specific regex parser with enhanced DB2 feature support."""

    dialect_name = "db2"  # lint: allow-dialect-string: dialect dispatch

    #: Object extraction's comment stripper reads Db2's nested-comment rule
    #: here. Statement boundaries come from ``_script``.
    tokenizer_class: Type[BaseTokenizer] = _DB2NestingCommentTokenizer

    def __init__(self) -> None:
        """Initialize DB2 regex parser."""
        config = DB2Config()
        super().__init__(config)  # type: ignore[arg-type]
        self.config: DB2Config = config  # type: ignore[assignment]

    def split(self, sql_content: str) -> List[Statement]:
        """The statements of a script as the CLP sends them (docs/sql-parsing/db2.md)."""
        return [
            Statement(
                text=unit.text,
                line=unit.line,
                terminator=unit.terminator,
                kind=unit.kind,
                source_start=unit.source_start,
                source_end=unit.source_end,
            )
            for unit in scan_script(sql_content)
        ]

    def split_statements(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """The statements execution sends; ``split()`` also records directives.

        The scanner has no unknown characters, so ``strict_tokenizer`` changes nothing.
        """
        return [record.text for record in self.split(sql_content) if record.kind == "sql"]

    def split_for_extraction(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """Project analysable SQL from the CLP scanner."""
        return analysis_sql(self.split(sql_content))

    def _extract_sqlpl_procedure_name(self, sql: str) -> Optional[str]:
        """Extract SQL/PL procedure name from CREATE PROCEDURE statement."""
        match = re.search(
            r"\b(?:CREATE|ALTER)\s+(?:OR\s+REPLACE\s+)?PROCEDURE\s+(?:\"([^\"]+)\"|([a-zA-Z0-9_$#@]+))(?:\.(?:\"([^\"]+)\"|([a-zA-Z0-9_$#@]+)))?",
            sql,
            re.IGNORECASE,
        )
        if match:
            # Return the first non-None group
            return next((g for g in match.groups() if g), None)
        return None

    def _extract_sqlpl_function_name(self, sql: str) -> Optional[str]:
        """Extract SQL/PL function name from CREATE FUNCTION statement."""
        match = re.search(
            r"\b(?:CREATE|ALTER)\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+(?:\"([^\"]+)\"|([a-zA-Z0-9_$#@]+))(?:\.(?:\"([^\"]+)\"|([a-zA-Z0-9_$#@]+)))?",
            sql,
            re.IGNORECASE,
        )
        if match:
            # Return the first non-None group
            return next((g for g in match.groups() if g), None)
        return None

    def _extract_trigger_name(self, sql: str) -> Optional[str]:
        """Extract trigger name from CREATE TRIGGER statement."""
        match = re.search(
            r"\b(?:CREATE|ALTER)\s+(?:OR\s+REPLACE\s+)?TRIGGER\s+(?:\"([^\"]+)\"|([a-zA-Z0-9_$#@]+))(?:\.(?:\"([^\"]+)\"|([a-zA-Z0-9_$#@]+)))?",
            sql,
            re.IGNORECASE,
        )
        if match:
            # Return the first non-None group
            return next((g for g in match.groups() if g), None)
        return None

    def _extract_tablespace_name(self, sql: str) -> Optional[str]:
        """Extract tablespace name from CREATE TABLESPACE statement."""
        match = re.search(
            r"\b(?:CREATE|ALTER|DROP)\s+(?:LOB\s+)?TABLESPACE\s+(?:\"([^\"]+)\"|([a-zA-Z0-9_$#@]+))",
            sql,
            re.IGNORECASE,
        )
        if match:
            # Return the first non-None group
            return next((g for g in match.groups() if g), None)
        return None

    def _extract_stogroup_name(self, sql: str) -> Optional[str]:
        """Extract storage group name from CREATE STOGROUP statement."""
        match = re.search(
            r"\b(?:CREATE|ALTER|DROP)\s+STOGROUP\s+(?:\"([^\"]+)\"|([a-zA-Z0-9_$#@]+))",
            sql,
            re.IGNORECASE,
        )
        if match:
            # Return the first non-None group
            return next((g for g in match.groups() if g), None)
        return None

    def parse_sql(self, sql_content: str, default_schema: Optional[str] = None) -> ParseResult:
        """Parse SQL content with DB2-specific enhancements.

        Args:
            sql_content: SQL content to parse
            default_schema: Default schema name

        Returns:
            ParseResult with statements and any errors
        """
        statements = []
        errors = []

        try:
            sql_statements = self.split_for_extraction(sql_content)

            # Parse each statement with DB2-specific handling
            for sql in sql_statements:
                if not sql.strip():
                    continue

                try:
                    stmt_type = self._classify_statement_enhanced(sql)
                    objects = self.extract_objects(self._clean_db2_comments(sql), default_schema)

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
                    error_msg = f"Error parsing DB2 statement: {str(e)}"
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
            error_msg = f"Error splitting DB2 SQL: {str(e)}"
            logger.error(error_msg)
            errors.append(error_msg)

        # Return success if we got statements, even with some errors
        success = len(statements) > 0 or len(errors) == 0
        return ParseResult(success=success, statements=statements, errors=errors)

    def _clean_db2_comments(self, sql: str) -> str:
        """Clean DB2-specific comments from SQL.

        Uses the shared quote-aware stripper, which nests ``/* ... */`` as
        Db2 does (``tokenizer_class``); a first-``*/`` regex left the tail
        of a nested comment behind as live SQL.
        """
        return self._strip_comments_preserving_quotes(sql)

    def _is_empty_or_comment(self, stmt: str) -> bool:
        """True if *stmt* holds nothing but whitespace and Db2 comments.

        Nesting-aware, like the splitter: ``/* a /* b */ c */`` is one
        comment. The inherited pattern check also mistook a statement that
        merely starts with ``/*`` and ends with ``*/`` for a comment.
        """
        return not self._strip_comments_preserving_quotes(stmt).strip()

    def validate_sql(self, sql_content: str) -> Dict[str, Any]:
        """Validate DB2 SQL content.

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

            # Check for DB2-specific syntax issues
            db2_errors = []
            for stmt in result.statements:
                db2_errors.extend(self._validate_db2_syntax(stmt.sql_text))

            if db2_errors:
                return {
                    "valid": False,
                    "errors": db2_errors,
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
                "errors": [f"DB2 validation error: {str(e)}"],
                "statement_count": 0,
            }

    def _validate_db2_syntax(self, sql: str) -> List[str]:
        """Validate DB2-specific syntax."""
        errors = []

        # Check for unmatched quoted identifiers
        quote_count = sql.count('"')
        if quote_count % 2 != 0:
            errors.append("Unmatched quoted identifier")

        # Check for proper SQL/PL block structure
        if re.search(r"\bBEGIN\s+(?:ATOMIC|NOT\s+ATOMIC)\b", sql, re.IGNORECASE):
            begin_count = len(re.findall(r"\bBEGIN\b", sql, re.IGNORECASE))
            end_count = len(re.findall(r"\bEND\b", sql, re.IGNORECASE))
            if begin_count != end_count:
                errors.append("Unmatched BEGIN/END blocks in SQL/PL")

        # Check for EXEC SQL without END-EXEC
        if re.search(r"\bEXEC\s+SQL\b", sql, re.IGNORECASE):
            if not re.search(r"\bEND-EXEC\b", sql, re.IGNORECASE):
                errors.append("EXEC SQL block without END-EXEC")

        # Check for DB2-specific identifier conventions
        if re.search(r"[a-zA-Z_][a-zA-Z0-9_$#@]*", sql):
            # Valid DB2 identifier pattern
            pass

        return errors

    def is_utility_statement(self, sql: str) -> bool:
        """Check if SQL is a DB2 utility statement.

        Args:
            sql: SQL content to check

        Returns:
            True if it's a DB2 utility statement
        """
        return self.config.is_db2_utility_statement(sql)
