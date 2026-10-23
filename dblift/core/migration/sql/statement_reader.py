"""Statement reader: splits migration SQL and reads each statement's kind and objects from facts."""

import logging
import re
from typing import Any, Dict, List, Literal, Optional

from dblift.core.logger import Log
from dblift.core.migration.sql.statement_splitter import StatementSplitter
from dblift.core.sql_model.dialect import get_sqlglot_dialect
from dblift.core.sql_parser.dialects.identifier_tokens import (
    BACKTICK_IDENTIFIER,
    BRACKET_IDENTIFIER,
    DOUBLE_QUOTED_IDENTIFIER,
)
from dblift.db.dml_analysis import (
    DEFAULT_QUOTE_PAIRS,
    _find_top_level_keyword,
    cte_outer_statement_type,
    scan_cte_outer_statement_type,
    strip_leading_sql_comments,
)
from dblift.db.provider_registry import ProviderRegistry

# Configure logging
logger = logging.getLogger(__name__)

# The schema reported when a statement names none. An internal placeholder, not
# an identifier: consumers must strip it rather than emit it into SQL.
DEFAULT_SCHEMA_PLACEHOLDER = "default_schema"

# A SQL identifier: quoted ("x", [x], `x`) or bare, optionally schema-qualified.
# The quoted alternatives come from dblift.core.sql_parser.dialects.identifier_tokens,
# the shared (escape-aware) definition also used by ``SqlServerConfig.object_patterns``.
_IDENTIFIER = rf"(?:{DOUBLE_QUOTED_IDENTIFIER}|{BRACKET_IDENTIFIER}|{BACKTICK_IDENTIFIER}|[\w$#]+)"
_QUALIFIED_NAME = rf"{_IDENTIFIER}(?:\s*\.\s*{_IDENTIFIER})*"


def is_select_into(statement: str) -> bool:
    """True for a top-level ``SELECT ... INTO <target>``, optionally behind a CTE list.

    It writes its result instead of returning rows: PostgreSQL and SQL Server
    create a table, MySQL/MariaDB fill variables or a file. Only an ``INTO``
    outside quotes, comments, dollar quotes and parentheses counts, so a CTE
    body or subquery never matches. A procedural ``SELECT ... INTO var`` sits
    inside a ``DO`` or ``CREATE FUNCTION`` body and never starts the statement.
    """
    text = strip_leading_sql_comments(statement).lstrip()
    if not re.match(r"(?:SELECT|WITH)\b", text, flags=re.IGNORECASE):
        return False
    into = _find_top_level_keyword(text, "INTO", DEFAULT_QUOTE_PAIRS)
    if into < 0:
        return False
    # ``WITH ... INSERT INTO`` / ``MERGE INTO`` is the outer DML's own INTO.
    return all(
        not 0 <= _find_top_level_keyword(text, verb, DEFAULT_QUOTE_PAIRS) < into
        for verb in ("INSERT", "MERGE")
    )


class StatementReader:
    """Splits SQL and reads each statement's kind and objects from the plugin's statement facts."""

    def __init__(
        self,
        dialect: str,
        logger: Optional[Log] = None,
        statement_splitter: Optional[StatementSplitter] = None,
        analysis_mode: Literal["full", "execution"] = "full",
    ):
        """Bind *dialect*; the splitter is built from its lexical spec unless one is given."""
        self.dialect = dialect.lower()
        self.analysis_mode = analysis_mode
        self.logger = logger or logging.getLogger(__name__)
        self.statement_splitter = statement_splitter or StatementSplitter(
            self.dialect, logger=self.logger
        )

    def prepare_object_analysis(self) -> None:
        """Fail before any SQL is applied when object analysis needs SQLGlot and it is missing."""
        from dblift.core.migration.executor.migration_executor import require_analysis_support

        require_analysis_support(self.analysis_mode)

    def get_statement_type(self, sql: str) -> str:
        """Get the high-level type of SQL statement (DDL, DML, QUERY, UNKNOWN).

        Reads the plugin's statement facts where they apply, else the statement's text.
        """
        sql = sql.strip()

        if not sql:
            return "UNKNOWN"

        execution_sql = sql.lstrip("\ufeff").lstrip() if self.analysis_mode == "execution" else sql
        if self.analysis_mode == "execution":
            try:
                execution_head = strip_leading_sql_comments(execution_sql, strict=True).lstrip()
            except ValueError as exc:
                raise ValueError(f"{exc}; use analysis_mode='full'") from exc
        else:
            execution_head = ""
        if self.analysis_mode == "execution" and re.match(
            r"WITH\b", execution_head, flags=re.IGNORECASE
        ):
            outer = scan_cte_outer_statement_type(
                execution_sql,
                quote_pairs=ProviderRegistry.get_quirks(self.dialect).sql_scan_quote_pairs,
                strict=True,
            )
            if outer is None:
                raise ValueError(
                    "Cannot classify WITH statement in execution mode; use analysis_mode='full'"
                )
            return "DML" if outer == "QUERY" and is_select_into(execution_sql) else outer

        # Starts like a query but returns no rows; checked ahead of the
        # dialect parsers, which classify by the leading keyword.
        if is_select_into(sql):
            return "DML"

        if (
            self.analysis_mode == "full"
            and self.dialect == "duckdb"  # lint: allow-dialect-string: DuckDB facts classification
        ):
            quirks = ProviderRegistry.get_quirks(self.dialect)
            if quirks.supports_statement_facts:
                return quirks.statement_facts(sql).kind

        # Words the dialect's own rules classify and the generic ones do not.
        first = strip_leading_sql_comments(sql).lstrip().split(None, 1)
        if first:
            word = re.match(r"[A-Za-z_]+", first[0])
            for statement_type, words in ProviderRegistry.get_quirks(
                self.dialect
            ).leading_word_statement_types:
                if word and word.group().upper() in words:
                    return statement_type

        # Fallback to enhanced string-based classification
        return self._get_statement_type_string(sql)

    def _get_statement_type_string(self, sql: str) -> str:
        """Enhanced string-based statement type identification with EXEC support."""
        # Remove leading/trailing whitespace
        sql_clean = sql.strip()
        # UTF-8 BOM breaks startswith("CREATE") / DDL detection if left in place
        if sql_clean.startswith("\ufeff"):
            sql_clean = sql_clean.lstrip("\ufeff").lstrip()

        # Keep the pre-comment-strip text for sqlglot (below); the comment
        # removal here is a crude regex meant only for keyword detection.
        original_sql = sql_clean

        # Remove SQL comments to get the actual first keyword
        # Remove block comments /* ... */
        sql_clean = re.sub(r"/\*.*?\*/", "", sql_clean, flags=re.DOTALL)
        # Remove line comments -- ...
        sql_clean = re.sub(r"--.*?$", "", sql_clean, flags=re.MULTILINE)

        # Get the cleaned and normalized statement
        sql_upper = sql_clean.upper().strip()

        if not sql_upper:
            return "UNKNOWN"

        # DDL patterns - include GRANT/REVOKE as they are DDL statements
        ddl_keywords = ["CREATE", "ALTER", "DROP", "TRUNCATE", "COMMENT", "GRANT", "REVOKE"]
        if any(sql_upper.startswith(ddl) for ddl in ddl_keywords):
            return "DDL"

        # Special handling for RENAME - it's DDL but might have different syntax
        if sql_upper.startswith("RENAME"):
            return "DDL"

        # DML patterns (including EXEC/EXECUTE)
        dml_keywords = ["INSERT", "UPDATE", "DELETE", "MERGE", "UPSERT"]
        if any(sql_upper.startswith(dml) for dml in dml_keywords):
            return "DML"

        # Handle EXEC/EXECUTE patterns more carefully
        if re.match(r"^EXEC(?:\s|\t|\n|\r)", sql_upper) or sql_upper.startswith("EXECUTE "):
            return "DML"

        # QUERY patterns
        if sql_upper.startswith("WITH"):
            # A data-modifying CTE (RETURNING) can feed an outer INSERT/UPDATE/
            # DELETE, which doesn't return rows even though the statement
            # starts with WITH.
            try:
                outer_type = cte_outer_statement_type(
                    original_sql, sqlglot_dialect=get_sqlglot_dialect(self.dialect)
                )
            except ModuleNotFoundError as exc:
                if exc.name != "sqlglot":
                    raise
                raise ModuleNotFoundError(
                    "classifying a WITH statement needs SQLGlot: install it with "
                    "`pip install dblift[analysis]`, or use analysis_mode='execution'",
                    name="sqlglot",
                ) from exc
            return "DML" if outer_type == "DML" else "QUERY"

        query_keywords = ["SELECT", "SHOW", "DESCRIBE", "DESC", "EXPLAIN"]
        if any(sql_upper.startswith(query) for query in query_keywords):
            return "QUERY"

        return "UNKNOWN"

    def _reads_objects(self, quirks: Any) -> bool:
        """Whether this analyzer reads objects: the plugin has a facts reader and the mode allows it.

        DuckDB's execution mode disables object extraction, which keeps it free of the SQL parser.
        """
        sqlglot_free = self.dialect == "duckdb"  # lint: allow-dialect-string: sqlglot-free mode
        if self.analysis_mode == "execution" and sqlglot_free:
            return False
        return bool(quirks.supports_statement_facts)

    @staticmethod
    def _fact_objects(quirks: Any, facts: Any) -> List[Dict[str, str]]:
        objects = [
            {
                "object_type": obj.type.value,
                "object_name": f"{obj.schema or DEFAULT_SCHEMA_PLACEHOLDER}.{obj.name}",
            }
            for obj in facts.affected_objects
        ]
        if quirks.is_sqlserver_family and facts.indexed_table:
            for obj in objects:
                if obj["object_type"] == "INDEX":
                    obj["on_object"] = facts.indexed_table
        return objects

    def extract_objects(self, sql: str) -> List[Dict[str, str]]:
        """Extract the objects a SQL statement acts on, as the plugin's statement facts read them.

        A statement the facts cannot read names no object, and neither does a dialect without a
        facts reader or DuckDB's ``analysis_mode="execution"``: no object is ever guessed from text.

        Args:
            sql: SQL statement to analyze

        Returns:
            List of dictionaries with object information
        """
        quirks = ProviderRegistry.get_quirks(self.dialect)
        if not self._reads_objects(quirks):
            return []
        return self._fact_objects(quirks, quirks.statement_facts(sql))

    def analyze_statement(self, sql: str) -> Dict[str, Any]:
        """Analyze a SQL statement for type and affected objects.

        Args:
            sql: SQL statement to analyze

        Returns:
            Dictionary containing analysis results; ``parsed_with`` is ``"facts"``, or ``"none"``
            when no objects are read (see :meth:`extract_objects`) and the type is classified from
            the statement text.
        """
        quirks = ProviderRegistry.get_quirks(self.dialect)
        if not self._reads_objects(quirks):
            return {
                "type": self.get_statement_type(sql),
                "objects": [],
                "is_valid": True,
                "errors": [],
                "parsed_with": "none",
            }
        facts = quirks.statement_facts(sql)
        return {
            "type": facts.kind,
            "objects": self._fact_objects(quirks, facts),
            "is_valid": facts.error is None,
            "errors": [facts.error] if facts.error else [],
            "parsed_with": "facts",
        }

    def split_statements(self, sql: str) -> List[str]:
        """Split SQL into individual statements.

        Args:
            sql: SQL script containing multiple statements

        Returns:
            List of individual SQL statements
        """
        # Directive lines (``PROMPT``, ``SET``, ``DEFINE``, ``WHENEVER`` ...) and
        # SQL*Plus variables are the dialect splitter's, not a pre-pass.
        statements = self.statement_splitter.split_statements(sql)

        # Log each statement for debugging
        for i, stmt in enumerate(statements):
            self.logger.debug(
                f"Execution Statement {i+1}: '{stmt[:50]}{'...' if len(stmt) > 50 else ''}'"
            )

        return list(statements)

    def split_statements_for_analysis(self, sql: str) -> List[str]:
        """The statements of ``sql`` for callers that read a script statement by statement.

        ``split_statements`` returns what the server receives, and a T-SQL batch holds several
        statements: a dialect that divides its batches does it here, after the same refusals.
        Every other dialect: the execution split.
        """
        engine = self.statement_splitter._engine
        if engine is not None:
            return engine.split_for_analysis(sql)
        return self.split_statements(sql)
