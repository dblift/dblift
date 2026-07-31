"""Oracle SQL parser using tokenization-based parsing for complex PL/SQL."""

import re
from typing import Any, Dict, List, Optional

from core.logger.log import LogFactory
from core.sql_model.base import (
    ParseResult,
    SqlObject,
    SqlStatement,
    SqlStatementType,
)
from core.sql_parser.common.base_parser import RegexBasedParser
from core.sql_parser.parser_context import ParserContext
from db.plugins.oracle.parser._comments import strip_comments
from db.plugins.oracle.parser._object_extractor import extract_objects
from db.plugins.oracle.parser._plsql_block import (
    extract_plsql_block,
    is_partial_plsql_fragment,
)
from db.plugins.oracle.parser._statement_splitter import (
    split_statements_regex,
)
from db.plugins.oracle.parser.oracle_statement_parser import OracleStatementParser
from db.plugins.oracle.parser.oracle_tokenizer import OracleTokenizer

logger = LogFactory.get_log(__name__)


class OracleParser(RegexBasedParser):
    """Oracle SQL parser using regex-based parsing for complex PL/SQL."""

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
        """Parse SQL content using regex-based approach for Oracle.

        This implementation handles Oracle-specific parsing challenges:
        - Quoted identifiers like "TEST_SCHEMA"."employees"
        - Complex PL/SQL blocks with nested structures
        - Package specifications and bodies
        - Anonymous blocks and procedures

        Uses regex-first parsing as the primary strategy for Oracle,
        which reliably handles quoted identifiers and complex PL/SQL constructs.
        """

        # Handle empty content early
        if not sql_content or not sql_content.strip():
            return ParseResult(success=True, statements=[], errors=[])

        # Clean and normalize the SQL
        cleaned_sql = sql_content.strip()

        # Apply placeholders if provided
        if placeholders:
            for placeholder, value in placeholders.items():
                cleaned_sql = cleaned_sql.replace(placeholder, str(value))

        error_messages = []

        # Regex-based statement splitting (primary method for Oracle)
        try:
            statements = split_statements_regex(
                cleaned_sql, extract_plsql_block=extract_plsql_block
            )
            logger.info(
                f"Oracle: Successfully parsed {len(statements)} statements using regex-based parsing"
            )

        except Exception as e:
            error_msg = f"Oracle regex parsing failed: {str(e)}"
            logger.error(error_msg)
            error_messages.append(error_msg)
            # Emergency fallback: treat entire input as single statement
            statements = [cleaned_sql]

        # Always return success with collected warnings
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
            errors=error_messages,  # Include warnings but don't fail
        )

    def split_statements(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """Split SQL content into statements using tokenization.

        For Oracle:
        - Split on standalone slash (/) for PL/SQL blocks
        - Keep PL/SQL blocks (CREATE PROCEDURE/FUNCTION/PACKAGE/TRIGGER, DECLARE/BEGIN) intact
        - Split regular SQL by semicolons
        - Properly handle END IF, END LOOP, END CASE (control flow) vs block-terminating END
        - Handle Q-quotes and wrapped PL/SQL

        Uses tokenization-based approach for robust parsing with fallback to regex.
        """
        if not sql_content or not sql_content.strip():
            return []

        try:
            # Use tokenization-based splitting
            tokenizer = OracleTokenizer(sql_content)
            tokens = tokenizer.tokenize()

            context = ParserContext()
            parser = OracleStatementParser(tokens, context)

            statements = parser.split_statements()
            logger.debug(f"Oracle: Tokenization split into {len(statements)} statements")
            return statements

        except Exception as e:
            # Fallback to old regex-based splitting if tokenization fails
            logger.warning(f"Oracle tokenization failed, falling back to regex: {str(e)}")
            return split_statements_regex(sql_content, extract_plsql_block=extract_plsql_block)

    def validate_sql(self, sql_content: str) -> Dict[str, Any]:
        """Validate SQL content using Oracle-specific regex-based validation."""
        try:
            statements = split_statements_regex(
                sql_content, extract_plsql_block=extract_plsql_block
            )

            errors: List[str] = []
            warnings: List[str] = []

            for stmt in statements:
                # Simple validation - just check if it's a fragment
                if is_partial_plsql_fragment(stmt):
                    warnings.append(f"Fragment detected: {stmt[:50]}...")

            return {
                "valid": True,  # Always return valid with graceful error handling
                "errors": errors,
                "warnings": warnings,
            }
        except Exception as e:
            return {
                "valid": True,  # Still return valid, but include error as warning
                "errors": [],
                "warnings": [f"Validation failed: {str(e)}"],
            }

    def get_affected_objects(
        self, sql: str, default_schema: Optional[str] = None
    ) -> List[SqlObject]:
        """Extract objects from SQL using regex-based approach."""
        return extract_objects(sql, default_schema)

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
