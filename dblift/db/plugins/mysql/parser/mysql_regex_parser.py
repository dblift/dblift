"""MySQL object parser backed by the client-aware script scanner."""

import logging
import re
from typing import Any, Dict, List, Optional, Type

from dblift.core.sql_model.base import ParseResult, SqlStatement, SqlStatementType
from dblift.core.sql_parser.base_tokenizer import BaseTokenizer
from dblift.core.sql_parser.enhanced_regex_parser import EnhancedRegexParser
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.lexical_spec import LexicalSpec
from dblift.core.sql_parser.statement import Statement, analysis_sql
from dblift.db.plugins.mysql.parser.lexical_spec import MYSQL_SPEC
from dblift.db.plugins.mysql.parser.mysql_tokenizer import MySQLTokenizer
from dblift.db.plugins.mysql.parser.parser_config import MySqlConfig

logger = logging.getLogger(__name__)


class MySqlRegexParser(EnhancedRegexParser):
    """MySQL-specific regex parser with enhanced MySQL feature support."""

    dialect_name = "mysql"  # lint: allow-dialect-string: dialect dispatch

    #: Object extraction and SQL redaction still use the tokenizer's MySQL
    #: comment and literal rules; statement boundaries come from the shared engine.
    tokenizer_class: Type[BaseTokenizer] = MySQLTokenizer

    #: The rules the engine cuts scripts with. Deliberately not named ``lexical_spec``: object
    #: extraction blanks comments through the engine when a parser has that attribute.
    _splitter_spec: LexicalSpec = MYSQL_SPEC

    def __init__(self) -> None:
        """Initialize MySQL regex parser."""
        config = MySqlConfig()
        super().__init__(config)  # type: ignore[arg-type]
        self.config: MySqlConfig = config  # type: ignore[assignment]

    def split(self, sql_content: str) -> List[Statement]:
        """The statements and ``DELIMITER`` directives of a script, as the client reads it."""
        return LexicalEngine(self._splitter_spec).split(sql_content)

    def split_statements(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """The statements the server receives; refuses what the client would not run as SQL.

        The scanner has no unknown characters, so ``strict_tokenizer`` changes nothing.
        """
        return LexicalEngine(self._splitter_spec).split_statements(sql_content)

    def split_for_analysis(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """Project analysable SQL from the client scanner, including custom-delimiter fragments."""
        return analysis_sql(self.split(sql_content))

    def split_for_extraction(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """Use the same scanner projection for object extraction."""
        return self.split_for_analysis(sql_content, strict_tokenizer=strict_tokenizer)

    def _clean_mysql_comments(self, sql: str) -> str:
        """Remove ordinary comments while retaining executable MySQL comments."""
        sql = re.sub(r"#.*$", "", sql, flags=re.MULTILINE)
        sql = re.sub(r"--.*$", "", sql, flags=re.MULTILINE)
        return re.sub(r"/\*(?!!)(.*?)\*/", "", sql, flags=re.DOTALL)

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
            sql_statements = self.split_for_extraction(sql_content)

            # Parse each statement with MySQL-specific handling
            for sql in sql_statements:
                if not sql.strip():
                    continue

                try:
                    stmt_type = self._classify_statement_enhanced(sql)
                    objects = self.extract_objects(self._clean_mysql_comments(sql), default_schema)

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
