"""SQL analyzer — parses migration scripts to extract tables, views, indexes, and other objects."""

import logging
import re
from typing import Any, Dict, List, Literal, Optional, Tuple

from dblift.core.exceptions import ParserNotAvailableError
from dblift.core.logger import Log
from dblift.core.migration.sql.statement_splitter import StatementSplitter
from dblift.core.sql_model.dialect import get_sqlglot_dialect
from dblift.core.sql_parser._deprecation import internal_parser_construction, warn_direct_parser

# Import parser system components
from dblift.core.sql_parser.dialects.identifier_tokens import (
    BACKTICK_IDENTIFIER,
    BRACKET_IDENTIFIER,
    DOUBLE_QUOTED_IDENTIFIER,
)
from dblift.core.sql_parser.parser_factory import SqlParserFactory
from dblift.core.sql_parser.parser_interface import SqlParserInterface
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
# The undo script generator imports these two patterns to recognise object references.
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


class SqlAnalyzer:
    """Analyzes SQL statements for type and affected objects."""

    def __init__(
        self,
        dialect: str,
        logger: Optional[Log] = None,
        parser_factory: Any = None,
        statement_splitter: Optional[StatementSplitter] = None,
        analysis_mode: Literal["full", "execution"] = "full",
    ):
        """Initialize SQL analyzer.

        Args:
            dialect: SQL dialect to use (required — callers resolve it from
                config/provider or the plugin registry; ADR-26 E5)
            logger: Optional logger to use
            parser_factory: Optional parser factory to use
        """
        warn_direct_parser("SqlAnalyzer")
        self.dialect = dialect.lower()
        self.analysis_mode = analysis_mode
        self.logger = logger or logging.getLogger(__name__)

        # Statement execution only needs regex/tokenizer splitting. Rich parser
        # construction remains reserved for schema/object analysis paths.
        self._db_specific_parser = None
        try:
            with internal_parser_construction():
                classification_factory = SqlParserFactory(self.dialect, parser_type="regex")
            self._db_specific_parser = classification_factory.get_parser()

            self.logger.debug(
                f"Initialized parser: {type(self._db_specific_parser).__name__} for dialect: {self.dialect}"
            )
        except Exception as e:
            # Use a basic logger if the class logger isn't available yet
            import logging as log_module

            basic_logger = log_module.getLogger(__name__)
            basic_logger.debug(
                f"Failed to initialize database-specific parser for {self.dialect}: {e}"
            )
            self._db_specific_parser = None

        self.statement_splitter = statement_splitter or StatementSplitter(
            self.dialect, logger=self.logger
        )

        # Rich parser construction is needed only by explicit analysis consumers.
        self._parser_factory: Any = parser_factory

    @property
    def parser_factory(self) -> Any:
        """Return the rich parser factory, constructing it on first access."""
        if self._parser_factory is None:
            with internal_parser_construction():
                self._parser_factory = SqlParserFactory(self.dialect)
        return self._parser_factory

    @parser_factory.setter
    def parser_factory(self, value: Any) -> None:
        """Keep explicit parser factory replacements available to consumers."""
        self._parser_factory = value

    def prepare_object_analysis(self) -> None:
        """Load the parser selected for object extraction before SQL is applied."""
        get_parser = getattr(self.parser_factory, "get_parser", None)
        if get_parser is None:
            return  # An injected factory without a preparation hook is opaque.
        try:
            get_parser()
        except ParserNotAvailableError as exc:
            if isinstance(exc.__cause__, ModuleNotFoundError):
                raise exc.__cause__ from None
            raise

    def get_statement_type(self, sql: str) -> str:
        """Get the high-level type of SQL statement (DDL, DML, QUERY, UNKNOWN).

        Uses database-specific regex parser, falling back to string analysis.
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

        # Try database-specific parser classification first
        if self.dialect and hasattr(self, "_db_specific_parser") and self._db_specific_parser:
            try:
                # Use database-specific parser's improved classification
                pass

                # Check if the parser has the method before calling it
                if hasattr(self._db_specific_parser, "_identify_statement_type"):
                    stmt_type = self._db_specific_parser._identify_statement_type(sql)

                    # Convert SqlStatementType enum to string (not MigrationType).
                    if hasattr(stmt_type, "value"):
                        result = str(stmt_type.value)
                    else:
                        result = str(stmt_type)  # lint: allow-enum-str  SqlStatementType fallback

                    # If we got a definitive result (not UNKNOWN), use it
                    if result != "UNKNOWN":
                        return result

            except Exception as e:
                logger.debug(f"Database-specific parser classification failed: {e}")

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
            outer_type = cte_outer_statement_type(
                original_sql, sqlglot_dialect=get_sqlglot_dialect(self.dialect)
            )
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

    def validate_sql(self, sql: str) -> Tuple[bool, Optional[str]]:
        """Validate SQL syntax and return (is_valid, error_message)."""
        # Try to use database-specific parser first if available
        if self._db_specific_parser and hasattr(self._db_specific_parser, "validate_sql"):
            try:
                self.logger.debug(f"Using {self.dialect}-specific parser for SQL validation")
                result = self._db_specific_parser.validate_sql(sql)

                # Handle different return formats from database-specific parsers
                if isinstance(result, tuple) and len(result) == 2:
                    is_valid, error_message = result
                elif isinstance(result, dict):
                    # Parsers answer {"valid": bool, "errors": [str, ...]}; the legacy
                    # {"is_valid", "error_message"} spelling is still read.
                    # An answer carrying no verdict is not a pass.
                    verdict = next(
                        (result[k] for k in ("valid", "is_valid", "success") if k in result),
                        None,
                    )
                    is_valid = bool(verdict)
                    errors = result.get("errors")
                    raw_error_message = errors[0] if errors else result.get("error_message", None)
                    if verdict is None:
                        raw_error_message = raw_error_message or "the parser returned no verdict"
                    error_message = (
                        str(raw_error_message) if raw_error_message is not None else None
                    )
                else:
                    # If parser returns something else, assume it's a boolean
                    is_valid = bool(result)
                    error_message = None

                self.logger.debug(
                    f"Validated SQL using {self.dialect}-specific parser: valid={is_valid}"
                )

                # Log validation details for debugging
                if hasattr(self.logger, "is_debug_enabled") and self.logger.is_debug_enabled():
                    truncated_sql = sql[:100] + ("..." if len(sql) > 100 else "")
                    if is_valid:
                        self.logger.debug(f"Valid SQL ({self.dialect}): {truncated_sql}")
                    else:
                        self.logger.debug(f"Invalid SQL ({self.dialect}): {truncated_sql}")
                        self.logger.debug(f"Error: {error_message}")

                return is_valid, error_message
            except Exception as e:
                self.logger.warning(
                    f"{self.dialect}-specific parser validation failed: {e}, assuming SQL is valid"
                )

        # Without database-specific parser validation, we use basic structural checks
        # This provides minimal validation but avoids complex ANTLR-based parsing
        self.logger.info("Using basic structural SQL validation")

        # Basic checks for common syntax errors
        sql_clean = sql.strip()
        if not sql_clean:
            return False, "Empty SQL statement"

        # Check for obvious syntax errors
        if sql_clean.count("(") != sql_clean.count(")"):
            return False, "Unmatched parentheses"

        if sql_clean.count("'") % 2 != 0:
            return False, "Unmatched single quotes"

        # If basic checks pass, assume SQL is valid
        return True, None

    def split_statements(self, sql: str, strict_tokenizer: Optional[bool] = None) -> List[str]:
        """Split SQL into individual statements.

        Args:
            sql: SQL script containing multiple statements
            strict_tokenizer: If True, dialect tokenizers fail on unknown
                characters instead of falling back to permissive splitting.

        Returns:
            List of individual SQL statements
        """
        # Directive lines (``PROMPT``, ``SET``, ``DEFINE``, ``WHENEVER`` ...) and
        # SQL*Plus variables are the dialect splitter's, not a pre-pass.
        if strict_tokenizer is not None:
            warn_direct_parser("strict_tokenizer")
        with internal_parser_construction():
            statements = self.statement_splitter.split_statements(
                sql,
                strict_tokenizer=bool(strict_tokenizer),
            )

        # Log each statement for debugging
        for i, stmt in enumerate(statements):
            self.logger.debug(
                f"Execution Statement {i+1}: '{stmt[:50]}{'...' if len(stmt) > 50 else ''}'"
            )

        return list(statements)

    def split_statements_for_analysis(
        self, sql: str, strict_tokenizer: Optional[bool] = None
    ) -> List[str]:
        """The statements of ``sql`` for callers that read a script statement by statement.

        ``split_statements`` returns what the server receives, and a T-SQL batch holds several
        statements: a dialect that divides its batches does it here, after the same refusals.
        Every other dialect: the execution split.
        """
        if strict_tokenizer is not None:
            warn_direct_parser("strict_tokenizer")
        engine = self.statement_splitter._engine
        if engine is not None and engine.spec.sqlite_shell:
            return engine.split_for_analysis(sql)
        parser = self._db_specific_parser
        if (
            parser is not None
            and type(parser).split_for_analysis is not SqlParserInterface.split_for_analysis
        ):
            return list(parser.split_for_analysis(sql, strict_tokenizer=bool(strict_tokenizer)))
        with internal_parser_construction():
            return self.split_statements(sql, strict_tokenizer=bool(strict_tokenizer))
