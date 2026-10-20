"""PostgreSQL regex-based parser implementation.

This module provides a tokenization-based PostgreSQL parser.
"""

import logging
import re
from typing import Any, Dict, List, Optional

from dblift.core.sql_model.base import (
    ParseResult,
    SqlStatement,
    SqlStatementType,
)
from dblift.core.sql_model.dialect import get_sqlglot_dialect
from dblift.core.sql_parser.enhanced_regex_parser import EnhancedRegexParser
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.lexical_statement_parser import LexicalStatementParser
from dblift.core.sql_parser.lexical_tokenizer import LexicalTokenizer
from dblift.core.sql_parser.parser_context import ParserContext
from dblift.core.sql_parser.statement import Statement, analysis_sql
from dblift.core.sql_parser.tokens import TokenType
from dblift.db.dml_analysis import cte_outer_statement_type
from dblift.db.plugins.postgresql.parser.lexical_spec import POSTGRESQL_SPEC
from dblift.db.plugins.postgresql.parser.parser_config import PostgreSqlConfig

logger = logging.getLogger(__name__)

# A CTE list can feed a SELECT or a modifying statement (INSERT/UPDATE/DELETE) —
# the leading WITH keyword alone doesn't say which.
_LEADING_WITH_RE = re.compile(r"^\s*WITH\s+", re.IGNORECASE)


class PostgreSqlRegexParser(EnhancedRegexParser):
    """PostgreSQL regex-based parser with comprehensive PostgreSQL support."""

    dialect_name = "postgresql"  # lint: allow-dialect-string: dialect dispatch

    lexical_spec = POSTGRESQL_SPEC

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
        """Project execution text from the shared engine. There is no fallback.

        The compatibility flag does not weaken lexical refusals.
        """
        return LexicalEngine(self.lexical_spec).split_statements(sql_content)

    def split(self, sql_content: str, strict_tokenizer: bool = False) -> List[Statement]:
        """Return executable units and their scanner-derived analysis parts."""
        return LexicalEngine(self.lexical_spec).split(sql_content)

    def split_for_analysis(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """Return every executable SQL constituent for analysis."""
        return analysis_sql(self.split(sql_content, strict_tokenizer=strict_tokenizer))

    def split_for_extraction(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """Extract objects from the same SQL constituents as analysis."""
        return self.split_for_analysis(sql_content, strict_tokenizer=strict_tokenizer)

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
            # A data-modifying CTE (RETURNING) can feed an outer INSERT/UPDATE/
            # DELETE, which doesn't return rows even though the statement starts
            # with WITH — ask sqlglot for the outer statement in that case.
            if _LEADING_WITH_RE.match(sql):
                sqlglot_dialect = get_sqlglot_dialect(self.dialect_name)
                if cte_outer_statement_type(sql, sqlglot_dialect=sqlglot_dialect) == "DML":
                    return SqlStatementType.DML
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
            statements = self.split_for_analysis(sql_content)

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
        """Validate client selection and structural parentheses with the tokenizer."""
        errors = []

        try:
            tokens = LexicalTokenizer(sql_content, spec=self.lexical_spec).tokenize()
            LexicalStatementParser(
                tokens, ParserContext(), source=sql_content, spec=self.lexical_spec
            ).split()
            depth = 0
            for token in tokens:
                if token.type != TokenType.SYMBOL:
                    continue
                if token.text == "(":
                    depth += 1
                elif token.text == ")":
                    depth -= 1
                    if depth < 0:
                        break
            if depth != 0:
                errors.append("Unmatched parentheses in SQL")

        except Exception as e:
            errors.append(f"Validation error: {str(e)}")

        return {"valid": len(errors) == 0, "errors": errors}
