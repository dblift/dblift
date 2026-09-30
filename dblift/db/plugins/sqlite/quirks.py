"""SQLite :class:`DialectQuirks`."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional, Type

from dblift.db.base_quirks import BaseQuirks

if TYPE_CHECKING:
    from dblift.db.generator_protocol import AlterGeneratorProtocol, SqlGeneratorProtocol


class SqliteQuirks(BaseQuirks):
    """SQLite-specific :class:`DialectQuirks` for the file-based SQLite dialect.

    Covers SQLite's deviations from ANSI SQL: file-based connections
    (no schema concept; ``schema_required=False``), no traditional
    user/password credentials, ``"main"`` as the default schema name,
    integer 0/1 literals for booleans, no CASCADE on ``DROP TABLE``,
    and the regex-only parser path (sqlglot's SQLite dialect is not
    used for round-trip parsing).
    """

    # Capability matrix (was ``_CAPABILITIES["sqlite"]``).
    supports_transactions = True
    supports_transactional_ddl = True
    schema_required = False  # file-based, no schema concept
    uppercase_identifiers = False
    clean_strategy = "native"
    sqlglot_dialect = "sqlite"
    default_schema_name = "main"
    boolean_false_literal = "0"
    # ``ON CONFLICT (col) DO UPDATE SET`` — the "UPSERT" clause, SQLite 3.24+ (2018).
    upsert_style = "on_conflict"
    drop_supports_if_exists = True  # supported since SQLite 3.3.0 (2006)
    # https://sqlite.org/lang_createview.html
    # SQLite has no CASCADE on DROP TABLE; use plain `DROP TABLE IF EXISTS`.
    table_drop_style = "if_exists"
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
    )

    def __init__(self, dialect_name: str = "sqlite") -> None:
        """Initialize SQLite quirks with the dialect name."""
        super().__init__(dialect_name=dialect_name)

    def ddl_generator_class(self) -> Optional[Type["SqlGeneratorProtocol"]]:
        """DDL generator is supplied by an installed extension package."""
        return None

    def alter_generator_class(self) -> Optional[Type["AlterGeneratorProtocol"]]:
        """ALTER generator is supplied by an installed extension package."""
        return None

    def render_column_type_change(
        self, col_diff: object, formatted_table: str, formatted_column: str, dialect: str
    ) -> "Optional[object]":
        """Expose type changes that require rebuilding the table as SQL comments."""
        from dblift.core.state.sql_statement import SqlStatement

        data_type_diff = getattr(col_diff, "data_type_diff", None)
        if data_type_diff is None:
            return None
        expected_type, actual_type = data_type_diff
        # SQLite has no ALTER COLUMN type syntax; use the documented 12-step rebuild.
        # https://sqlite.org/lang_altertable.html#making_other_kinds_of_table_schema_changes
        return SqlStatement(
            sql=(
                f"-- Column type change for {formatted_table}.{formatted_column} "
                f"from {actual_type} to {expected_type} requires rebuilding the table."
            ),
            statement_type="COMMENT",
            object_type="COLUMN",
            object_name=f"{formatted_table}.{formatted_column}",
            dialect=dialect,
        )

    def parser_class(self, parser_type: str) -> Optional[type]:
        """SQLite uses :class:`SQLiteRegexParser` for ``"hybrid"`` and ``"regex"``.

        ``"sqlglot"`` returns ``None`` — sqlglot's SQLite dialect is not used
        for round-trip parsing (regex handles SQLite's small DDL surface).
        """
        # SQLite uses regex-only parser for all three modes (hybrid
        # routing previously dispatched here too).
        from dblift.db.plugins.sqlite.parser.sqlite_regex_parser import SQLiteRegexParser

        if parser_type in ("hybrid", "regex"):
            return SQLiteRegexParser
        return None

    def introspector_class(self) -> Optional[Type[Any]]:
        """SQLite rich introspection is supplied by an installed extension package."""
        return None

    def vendor_queries_class(self) -> "Optional[Type[Any]]":
        """SQLite metadata queries are supplied by an installed extension package."""
        return None

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

    def type_preferences(self) -> "dict[str, str]":
        """SQLite prefers its storage-class affinity names.

        ``VARCHAR`` → ``TEXT`` and ``TIMESTAMP`` → ``DATETIME`` reflect SQLite's
        flexible typing where text and date/time are stored as TEXT.
        """
        return {"INTEGER": "INTEGER", "VARCHAR": "TEXT", "TIMESTAMP": "DATETIME"}


__all__ = ["SqliteQuirks"]
