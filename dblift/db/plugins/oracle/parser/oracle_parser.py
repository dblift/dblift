"""Oracle SQL parser using tokenization-based parsing for complex PL/SQL."""

import logging
import re
from typing import Any, Dict, List, Optional

from dblift.core.logger.log import LogFactory
from dblift.core.sql_model.base import (
    ParseResult,
    SqlObject,
    SqlStatement,
    SqlStatementType,
)
from dblift.core.sql_parser.common.base_parser import RegexBasedParser
from dblift.core.sql_parser.parser_context import ParserContext
from dblift.core.sql_parser.statement import Statement, analysis_sql
from dblift.db.plugins.oracle.parser._comments import strip_comments
from dblift.db.plugins.oracle.parser._object_extractor import extract_objects
from dblift.db.plugins.oracle.parser.oracle_statement_parser import OracleStatementParser
from dblift.db.plugins.oracle.parser.oracle_tokenizer import OracleTokenizer

try:
    logger: Any = LogFactory.get_log(__name__)
except ModuleNotFoundError as exc:
    if exc.name != "rich":
        raise
    logger = logging.getLogger(__name__)


class OracleParser(RegexBasedParser):
    """Oracle SQL parser using the tokenizer's SQL*Plus execution selection."""

    dialect_name = "oracle"  # lint: allow-dialect-string: dialect dispatch

    def __init__(self) -> None:
        """Initialize the Oracle parser."""
        super().__init__("oracle")  # lint: allow-dialect-string: dialect dispatch
        logger.debug("[DEBUG] OracleParser initialized with regex-based parsing")

    def parse_sql(
        self,
        sql_content: str,
        default_schema: Optional[str] = None,
        placeholders: Optional[Dict[str, Any]] = None,
    ) -> ParseResult:
        """Parse the SQL units selected by the Oracle tokenizer."""

        # Handle empty content early
        if not sql_content or not sql_content.strip():
            return ParseResult(success=True, statements=[], errors=[])

        cleaned_sql = sql_content

        # Apply placeholders if provided
        if placeholders:
            for placeholder, value in placeholders.items():
                cleaned_sql = cleaned_sql.replace(placeholder, str(value))

        try:
            statements = self.split_for_analysis(cleaned_sql)
        except Exception as e:
            error_msg = f"Oracle parsing failed: {str(e)}"
            logger.error(error_msg)
            return ParseResult(success=False, statements=[], errors=[error_msg])

        sql_statements: List[SqlStatement] = [
            SqlStatement(
                sql_text=stmt,
                statement_type=SqlStatementType.UNKNOWN,
                dialect=self.dialect_name,
                objects=[],
            )
            for stmt in statements
        ]
        return ParseResult(
            success=True,
            statements=sql_statements,
            errors=[],
        )

    def split(self, sql_content: str, strict_tokenizer: bool = False) -> List[Statement]:
        """Return Oracle execution records from the authoritative tokenizer."""
        if not sql_content or not sql_content.strip():
            return []
        tokenizer = OracleTokenizer(sql_content, strict_unknown_chars=strict_tokenizer)
        return OracleStatementParser(
            tokenizer.tokenize(), ParserContext(), source=sql_content
        ).split()

    def split_for_analysis(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """Project the selected SQL records for analysis."""
        return analysis_sql(self.split(sql_content, strict_tokenizer=strict_tokenizer))

    def split_for_extraction(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """Project the same selected SQL records for object extraction."""
        return self.split_for_analysis(sql_content, strict_tokenizer=strict_tokenizer)

    def split_statements(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """Split SQL content into statements using tokenization.

        For Oracle:
        - Split on standalone slash (/) for PL/SQL blocks
        - Keep PL/SQL blocks (CREATE PROCEDURE/FUNCTION/PACKAGE/TRIGGER, DECLARE/BEGIN) intact
        - Split regular SQL by semicolons
        - Properly handle END IF, END LOOP, END CASE (control flow) vs block-terminating END
        - Handle Q-quotes and wrapped PL/SQL

        A statement the tokenizer or parser cannot place raises (``UnsafeStatementSplitError``
        from the caller's view); the regex splitter is never consulted here. There is no fallback.
        """
        if not sql_content or not sql_content.strip():
            return []

        tokenizer = OracleTokenizer(sql_content, strict_unknown_chars=strict_tokenizer)
        parser = OracleStatementParser(tokenizer.tokenize(), ParserContext(), source=sql_content)
        return parser.split_statements()

    def validate_sql(self, sql_content: str) -> Dict[str, Any]:
        """Validate the SQL units selected for Oracle execution."""
        try:
            statements = self.split_for_analysis(sql_content)

            errors: List[str] = []
            warnings: List[str] = []

            for stmt in statements:
                # Simple validation - just check if it's a fragment
                if re.fullmatch(r"(?:END\s*;?|BEGIN|DECLARE|/|;)", stmt.strip(), re.IGNORECASE):
                    warnings.append(f"Fragment detected: {stmt[:50]}...")

            return {
                "valid": True,
                "errors": errors,
                "warnings": warnings,
            }
        except Exception as e:
            return {
                "valid": False,
                "errors": [f"Validation failed: {str(e)}"],
                "warnings": [],
            }

    def extract_objects(self, sql: str, default_schema: Optional[str] = None) -> List[SqlObject]:
        """Extract objects from SQL using Oracle-specific regex patterns.

        Overrides the generic ``RegexBasedParser`` fallback, which knows
        nothing of Oracle syntax (sequences, quoted-identifier case rules).
        """
        return extract_objects(sql, default_schema)

    def get_affected_objects(
        self, sql: str, default_schema: Optional[str] = None
    ) -> List[SqlObject]:
        """Extract objects from SQL using regex-based approach."""
        return self.extract_objects(sql, default_schema)

    def _identify_statement_type(self, sql: str) -> SqlStatementType:
        """Identify statement type using enhanced Oracle-specific patterns."""
        sql_stripped = sql.strip()
        if sql_stripped.startswith("\ufeff"):
            sql_stripped = sql_stripped.lstrip("\ufeff").lstrip()
        sql_upper = sql_stripped.upper()

        if not sql_upper:
            return SqlStatementType.UNKNOWN

        # Remove comments first
        sql_clean = strip_comments(sql_upper)

        # Handle Oracle-specific statement types

        # DDL statements
        if any(
            sql_clean.startswith(ddl)
            for ddl in [
                "CREATE",
                "ALTER",
                "DROP",
                "TRUNCATE",
                "RENAME",
                "COMMENT",
                "GRANT",
                "REVOKE",
                "ANALYZE",
                "AUDIT",
                "NOAUDIT",
            ]
        ):
            return SqlStatementType.DDL

        # DML statements (including Oracle CALL statements)
        if any(
            sql_clean.startswith(dml)
            for dml in ["INSERT", "UPDATE", "DELETE", "MERGE", "UPSERT", "CALL"]
        ):
            return SqlStatementType.DML

        # Handle EXEC/EXECUTE patterns
        if re.match(r"^EXEC(?:\s|\t|\n|\r)", sql_clean) or sql_clean.startswith("EXECUTE "):
            return SqlStatementType.DML

        # Query statements
        if any(
            sql_clean.startswith(query)
            for query in ["SELECT", "WITH", "SHOW", "DESCRIBE", "DESC", "EXPLAIN"]
        ):
            return SqlStatementType.QUERY

        return SqlStatementType.UNKNOWN

    def _classify_with_string_analysis(self, sql: str) -> SqlStatementType:
        """Classify SQL statement using string analysis patterns."""
        sql_upper = sql.upper().strip()

        # DDL patterns
        ddl_patterns = [
            r"^\s*CREATE\s+",
            r"^\s*ALTER\s+",
            r"^\s*DROP\s+",
            r"^\s*TRUNCATE\s+",
            r"^\s*COMMENT\s+ON\s+",
        ]

        for pattern in ddl_patterns:
            if re.match(pattern, sql_upper):
                return SqlStatementType.DDL

        # DML patterns
        dml_patterns = [
            r"^\s*INSERT\s+",
            r"^\s*UPDATE\s+",
            r"^\s*DELETE\s+",
            r"^\s*MERGE\s+",
        ]

        for pattern in dml_patterns:
            if re.match(pattern, sql_upper):
                return SqlStatementType.DML

        # Query patterns
        query_patterns = [
            r"^\s*SELECT\s+",
            r"^\s*WITH\s+",
        ]

        for pattern in query_patterns:
            if re.match(pattern, sql_upper):
                return SqlStatementType.QUERY

        return SqlStatementType.UNKNOWN
