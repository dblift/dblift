"""DuckDB dialect configuration for regex-based parsing.

DuckDB SQL is PostgreSQL-like but with a small, non-procedural surface:
- No stored procedures / no PL blocks (user code lives outside the DB)
- Real schemas and sequences
- Double-quoted identifiers (no square brackets)
"""

import re
from typing import Dict, List, Pattern, Set

from core.sql_parser.dialects.base_config import DialectConfig

_IDENT = r'(?:"[^"]*"|[a-zA-Z_][a-zA-Z0-9_]*)'
_QUALIFIED = rf"(?:{_IDENT}\.)?{_IDENT}"


class DuckDBParserConfig(DialectConfig):
    """DuckDB dialect configuration for the regex parser framework."""

    def __init__(self) -> None:
        """Initialize DuckDB dialect configuration."""
        super().__init__()  # type: ignore[no-untyped-call]

        self.identifier_quote_char = '"'
        self.string_quote_char = "'"
        self.supports_bracket_identifiers = False
        self.statement_separator = ";"
        self.line_comment_prefix = "--"
        self.block_comment_start = "/*"
        self.block_comment_end = "*/"

        self.supports_dollar_quoting = False
        self.supports_copy_statements = True  # DuckDB COPY
        self.supports_plpgsql_blocks = False
        self.supports_cte_with_recursive = True
        self.supports_on_conflict = True
        self.supports_returning = True

        self._compile_patterns()

    def _compile_patterns(self) -> None:
        def _create(kind: str) -> Pattern[str]:
            return re.compile(
                rf"\s*CREATE\s+(?:OR\s+REPLACE\s+)?{kind}\s+(?:IF\s+NOT\s+EXISTS\s+)?",
                re.IGNORECASE,
            )

        def _drop(kind: str) -> Pattern[str]:
            return re.compile(rf"\s*DROP\s+{kind}\s+(?:IF\s+EXISTS\s+)?", re.IGNORECASE)

        self._ddl_patterns = {
            "create_table": _create(r"(?:TEMP(?:ORARY)?\s+)?TABLE"),
            "create_view": _create(r"(?:TEMP(?:ORARY)?\s+)?VIEW"),
            "create_index": re.compile(
                r"\s*CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?", re.IGNORECASE
            ),
            "create_sequence": _create(r"(?:TEMP(?:ORARY)?\s+)?SEQUENCE"),
            "create_schema": _create(r"SCHEMA"),
            "create_type": _create(r"TYPE"),
            "create_macro": _create(r"(?:TEMP(?:ORARY)?\s+)?MACRO"),
            "alter_table": re.compile(r"\s*ALTER\s+TABLE\s+", re.IGNORECASE),
            "drop_table": _drop("TABLE"),
            "drop_view": _drop("VIEW"),
            "drop_index": _drop("INDEX"),
            "drop_sequence": _drop("SEQUENCE"),
            "drop_schema": _drop("SCHEMA"),
            "drop_type": _drop("TYPE"),
        }

        self._dml_patterns = {
            "insert": re.compile(
                r"\s*INSERT\s+(?:OR\s+(?:REPLACE|IGNORE)\s+)?INTO\s+", re.IGNORECASE
            ),
            "update": re.compile(r"\s*UPDATE\s+", re.IGNORECASE),
            "delete": re.compile(r"\s*DELETE\s+FROM\s+", re.IGNORECASE),
            "copy": re.compile(r"\s*COPY\s+", re.IGNORECASE),
        }

        self._query_patterns = {
            "select": re.compile(r"\s*SELECT\s+", re.IGNORECASE),
            "with": re.compile(r"\s*WITH\s+(?:RECURSIVE\s+)?", re.IGNORECASE),
            "values": re.compile(r"\s*VALUES\s+", re.IGNORECASE),
            "explain": re.compile(r"\s*EXPLAIN\s+", re.IGNORECASE),
        }

    def get_ddl_keywords(self) -> Set[str]:
        return {"CREATE", "ALTER", "DROP", "ATTACH", "DETACH", "PRAGMA"}

    def get_dml_keywords(self) -> Set[str]:
        return {"INSERT", "UPDATE", "DELETE", "COPY"}

    def get_query_keywords(self) -> Set[str]:
        return {"SELECT", "WITH", "VALUES", "EXPLAIN"}

    def get_transaction_keywords(self) -> Set[str]:
        return {"BEGIN", "COMMIT", "ROLLBACK", "ABORT", "TRANSACTION", "START"}

    def get_identifier_pattern(self) -> re.Pattern[str]:
        return re.compile(_IDENT, re.IGNORECASE)

    def get_qualified_identifier_pattern(self) -> re.Pattern[str]:
        return re.compile(_QUALIFIED, re.IGNORECASE)

    def get_string_literal_pattern(self) -> re.Pattern[str]:
        return re.compile(r"'(?:[^']|'')*'", re.IGNORECASE)

    def get_comment_pattern(self) -> re.Pattern[str]:
        return re.compile(r"(?:--[^\r\n]*|/\*.*?\*/)", re.DOTALL)

    def get_statement_separator_pattern(self) -> re.Pattern[str]:
        return re.compile(r";")

    def _matches_any(self, patterns: Dict[str, Pattern[str]], statement: str) -> bool:
        statement = statement.strip()
        return bool(statement) and any(p.match(statement) for p in patterns.values())

    def is_ddl_statement(self, statement: str) -> bool:
        return self._matches_any(self._ddl_patterns, statement)

    def is_dml_statement(self, statement: str) -> bool:
        return self._matches_any(self._dml_patterns, statement)

    def is_query_statement(self, statement: str) -> bool:
        return self._matches_any(self._query_patterns, statement)

    def get_batch_separator(self) -> str:
        return ";"

    def supports_block_comments(self) -> bool:
        return True

    def supports_line_comments(self) -> bool:
        return True

    def get_block_keywords_for_splitting(self) -> Set[str]:
        # DuckDB DDL is non-procedural; only transaction control uses BEGIN/END.
        return set()

    def normalize_identifier(self, identifier: str, is_quoted: bool = False) -> str:
        if not identifier:
            return identifier
        if identifier.startswith('"') and identifier.endswith('"'):
            return identifier[1:-1]
        return identifier

    @property
    def name(self) -> str:
        return "duckdb"  # lint: allow-dialect-string: dialect dispatch

    @property
    def batch_separators(self) -> List[Pattern[str]]:
        return [re.compile(r";")]

    @property
    def quoted_identifiers(self) -> List[Pattern[str]]:
        return [re.compile(r'"[^"]*"')]

    @property
    def comment_patterns(self) -> List[Pattern[str]]:
        return [re.compile(r"--[^\r\n]*"), re.compile(r"/\*.*?\*/", re.DOTALL)]

    @property
    def block_keywords(self) -> List[str]:
        return ["CREATE", "ALTER", "DROP"]

    @property
    def ddl_patterns(self) -> Dict[str, Pattern[str]]:
        return self._ddl_patterns

    @property
    def dml_patterns(self) -> Dict[str, Pattern[str]]:
        return self._dml_patterns

    @property
    def query_patterns(self) -> Dict[str, Pattern[str]]:
        return self._query_patterns

    @property
    def object_patterns(self) -> Dict[str, Pattern[str]]:
        def _obj(kind: str) -> Pattern[str]:
            return re.compile(
                rf"CREATE\s+(?:OR\s+REPLACE\s+)?{kind}\s+(?:IF\s+NOT\s+EXISTS\s+)?"
                rf"(?:({_IDENT})\.)?({_IDENT})",
                re.IGNORECASE,
            )

        return {
            "create_table": _obj(r"(?:TEMP(?:ORARY)?\s+)?TABLE"),
            "create_view": _obj(r"(?:TEMP(?:ORARY)?\s+)?VIEW"),
            "create_index": re.compile(
                rf"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?"
                rf"(?:({_IDENT})\.)?({_IDENT})",
                re.IGNORECASE,
            ),
            "create_sequence": _obj(r"(?:TEMP(?:ORARY)?\s+)?SEQUENCE"),
            "alter_table": re.compile(
                rf"ALTER\s+TABLE\s+(?:({_IDENT})\.)?({_IDENT})", re.IGNORECASE
            ),
            "drop_table": re.compile(
                rf"DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:({_IDENT})\.)?({_IDENT})", re.IGNORECASE
            ),
        }
