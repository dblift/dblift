"""SQLite :class:`DialectQuirks`."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from dblift.core.sql_parser.statement_facts import SqlglotStatementFactsReader
from dblift.db.base_quirks import BaseQuirks
from dblift.db.dml_analysis import DmlMutation

if TYPE_CHECKING:
    from dblift.core.sql_parser.lexical_spec import LexicalSpec


class SqliteQuirks(BaseQuirks):
    """SQLite-specific :class:`DialectQuirks` for the file-based SQLite dialect.

    Covers SQLite's deviations from ANSI SQL: file-based connections
    (no schema concept; ``schema_required=False``), no traditional
    user/password credentials, ``"main"`` as the default schema name,
    integer 0/1 literals for booleans, no CASCADE on ``DROP TABLE``,
    and statement facts read from sqlglot's SQLite AST.
    """

    # Capability matrix (was ``_CAPABILITIES["sqlite"]``).
    supports_transactions = True
    supports_transactional_ddl = True
    schema_required = False  # file-based, no schema concept
    uppercase_identifiers = False
    clean_strategy = "native"
    sqlglot_dialect = "sqlite"
    statement_facts_class = SqlglotStatementFactsReader
    undo_reverses_statement_facts = True
    default_schema_name = "main"
    boolean_false_literal = "0"
    drop_supports_if_exists = True  # supported since SQLite 3.3.0 (2006)
    # Wave B hooks.
    native_driver_display = "sqlite3"
    requires_credentials = False
    url_optional_when_file_path_given = True
    connection_identifier_attrs = ("url", "path", "database")
    # In-memory DB: never touches disk, safe as a validate-sql offline placeholder.
    lint_placeholder_url = "sqlite:///:memory:"

    # SQLite's own reference: "This pragma is a no-op within a transaction;
    # foreign key constraint enforcement may only be enabled or disabled when
    # there is no pending BEGIN" (pragma.html#pragma_foreign_keys). A migration
    # that sets this pragma inside a transactional migrate run otherwise
    # executes silently without taking effect.
    non_transactional_sql_patterns = (
        (
            r"^PRAGMA\s+FOREIGN_KEYS\s*=?\s*\(?\s*(ON|OFF|TRUE|FALSE|0|1)\s*\)?;?$",
            "SQLite PRAGMA foreign_keys is a no-op inside a transaction block",
        ),
        # "VACUUM ... cannot be run inside a transaction" (lang_vacuum.html).
        (r"^VACUUM\b", "SQLite VACUUM cannot run inside a transaction"),
    )

    # dblift's migrate holds the connection's one transaction: a script's own BEGIN fails against
    # it and its COMMIT/END/ROLLBACK ends it early. The SAVEPOINT family has no entry: it nests.
    transaction_control_sql_patterns = (
        (r"^BEGIN(\s+(DEFERRED|IMMEDIATE))?(\s+TRANSACTION)?\s*;?$", "begin"),
        (r"^BEGIN\b", "begin_other"),
        (r"^(COMMIT|END)(\s+TRANSACTION)?\s*;?$", "end"),
        (r"^ROLLBACK(\s+TRANSACTION)?\s*;?$", "abort"),
    )

    def blank_comments(self, sql: str) -> str:
        """The statement with its comments blanked by the SQLite scanner."""
        from dblift.core.sql_parser.lexical_engine import LexicalEngine

        return LexicalEngine(self.lexical_spec()).blank_comments(sql)

    def lexical_spec(self) -> "LexicalSpec":
        """The SQLite script rules used by execution, analysis and masking."""
        from dblift.db.plugins.sqlite.parser.lexical_spec import SQLITE_SPEC

        return SQLITE_SPEC

    def __init__(self, dialect_name: str = "sqlite") -> None:
        """Initialize SQLite quirks with the dialect name."""
        super().__init__(dialect_name=dialect_name)

    def parser_class(self, parser_type: str) -> Optional[type]:
        """Use statement facts for the supported SQLite parser projections."""
        from dblift.db.plugins.sqlite.parser.sqlite_facts_parser import SQLiteFactsParser

        return SQLiteFactsParser if parser_type in ("hybrid", "regex") else None

    def analyze_dml(self, statement: str) -> DmlMutation:
        """Project DML safety details from the SQLite statement facts."""
        facts = self.statement_facts(statement)
        return DmlMutation(
            facts.target or "",
            set(facts.events) if facts.events else None,
            list(facts.affected_columns),
        )

    def is_full_table_dml(self, statement: str) -> bool:
        """Treat an opaque mutation as potentially affecting every row."""
        facts = self.statement_facts(statement)
        return facts.operation in ("UPDATE", "DELETE") and (not facts.predicate)

    def type_equivalents(self) -> "dict[str, str]":
        """SQLite alias → canonical type map.

        ``INT`` → ``INTEGER``, ``CHARACTER VARYING`` → ``VARCHAR``, and
        ``DOUBLE``/``DOUBLE PRECISION`` → ``REAL`` (SQLite's only float type).
        """
        return {
            "INT": "INTEGER",
            "CHARACTER VARYING": "VARCHAR",
            "DOUBLE PRECISION": "REAL",
            "DOUBLE": "REAL",
        }


__all__ = ["SqliteQuirks"]
