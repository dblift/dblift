"""DuckDB :class:`DialectQuirks` — provider capability overlay."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from dblift.db.base_quirks import BaseQuirks
from dblift.db.plugins.duckdb.parser.duckdb_facts_parser import DuckDBStatementFactsReader

if TYPE_CHECKING:
    from dblift.core.sql_parser.lexical_spec import LexicalSpec


class DuckDBQuirks(BaseQuirks):
    """DuckDB-specific :class:`DialectQuirks`.

    DuckDB is embedded/file-based like SQLite (native driver, no
    credentials, ``"main"`` default schema) but PostgreSQL-like in SQL
    (real schemas, sequences, native ``BOOLEAN``, ``information_schema``,
    ACID transactional DDL). Capability values reflect that hybrid.
    """

    # Capability matrix (consumed by core.sql_model.dialect via the registry).
    supports_transactions = True
    supports_transactional_ddl = True  # DuckDB DDL is transactional (MVCC/ACID)
    schema_required = False  # defaults to "main"; schemas supported but optional
    uppercase_identifiers = False
    clean_strategy = "native"
    sqlglot_dialect = "duckdb"
    statement_facts_class = DuckDBStatementFactsReader
    default_schema_name = "main"
    boolean_false_literal = "FALSE"  # native BOOLEAN, not 0/1
    drop_supports_if_exists = True
    # Wave B hooks — embedded, file-based, no credentials (mirrors SQLite).
    native_driver_display = "duckdb"
    requires_credentials = False
    url_optional_when_file_path_given = True
    connection_identifier_attrs = ("url", "path", "database")
    # In-memory DB: never touches disk, safe as a validate-sql offline placeholder.
    lint_placeholder_url = "duckdb:///:memory:"

    # The connection always holds dblift's transaction (``duckdb_engine`` opens one on the first
    # statement): a script's own BEGIN fails against it and its COMMIT/END/ROLLBACK/ABORT ends it
    # early. DuckDB has no SAVEPOINT, so there is no savepoint family to leave alone.
    transaction_control_sql_patterns = (
        (r"^(BEGIN(\s+(TRANSACTION|WORK))?|START\s+TRANSACTION)\s*;?$", "begin"),
        (r"^(BEGIN|START\s+TRANSACTION)\b", "begin_other"),
        (r"^(COMMIT|END)(\s+(TRANSACTION|WORK))?\s*;?$", "end"),
        (r"^(ROLLBACK|ABORT)(\s+(TRANSACTION|WORK))?\s*;?$", "abort"),
    )

    non_transactional_sql_patterns = (
        (
            r"^(?:FORCE\s+)?CHECKPOINT\b",
            "DuckDB CHECKPOINT cannot run in a transaction with local changes",
        ),
    )

    def lexical_spec(self) -> "LexicalSpec":
        """The lexical specification the shared engine cuts DuckDB scripts with."""
        from dblift.db.plugins.duckdb.parser.lexical_spec import DUCKDB_SPEC

        return DUCKDB_SPEC

    def blank_comments(self, sql: str) -> str:
        """The statement with its comments blanked by the same scanner as execution."""
        from dblift.core.sql_parser.lexical_engine import LexicalEngine

        return LexicalEngine(self.lexical_spec()).blank_comments(sql)

    def __init__(self, dialect_name: str = "duckdb") -> None:
        """Initialize DuckDB quirks with the dialect name."""
        super().__init__(dialect_name=dialect_name)

    def parser_class(self, parser_type: str) -> Optional[type]:
        """The facts parser bound to DuckDB, whatever ``parser_type`` is asked."""
        from dblift.db.plugins.duckdb.parser.duckdb_facts_parser import DuckDBFactsParser

        return DuckDBFactsParser

    def type_equivalents(self) -> "dict[str, str]":
        """DuckDB alias → canonical type map."""
        return {
            "INT": "INTEGER",
            "INT4": "INTEGER",
            "INT8": "BIGINT",
            "BOOL": "BOOLEAN",
            "CHARACTER VARYING": "VARCHAR",
            "TEXT": "VARCHAR",
            "DECIMAL": "NUMERIC",
            "DOUBLE": "DOUBLE",
        }


__all__ = ["DuckDBQuirks"]
