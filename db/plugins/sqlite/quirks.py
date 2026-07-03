"""SQLite :class:`DialectQuirks` — Epic 26."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional, Type

from db.base_quirks import BaseQuirks

if TYPE_CHECKING:
    from core.sql_generator.alter.base_alter_generator import BaseAlterGenerator
    from core.sql_generator.base_generator import BaseSqlGenerator


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
    drop_supports_if_exists = True  # supported since SQLite 3.3.0 (2006)
    # SQLite has no CASCADE on DROP TABLE; use plain `DROP TABLE IF EXISTS`.
    table_drop_style = "if_exists"
    # Wave B hooks.
    native_driver_display = "sqlite3"
    requires_credentials = False
    url_optional_when_file_path_given = True
    connection_identifier_attrs = ("url", "path", "database")

    def __init__(self, dialect_name: str = "sqlite") -> None:
        """Initialize SQLite quirks with the dialect name."""
        super().__init__(dialect_name=dialect_name)

    def ddl_generator_class(self) -> Optional[Type["BaseSqlGenerator"]]:
        """DDL generator relocated to the paid package; registered by register_pro_generators()."""
        return None

    def alter_generator_class(self) -> Optional[Type["BaseAlterGenerator"]]:
        """ALTER generator relocated to the paid package; registered by register_pro_generators()."""
        return None

    def parser_class(self, parser_type: str) -> Optional[type]:
        """SQLite uses :class:`SQLiteRegexParser` for ``"hybrid"`` and ``"regex"``.

        ``"sqlglot"`` returns ``None`` — sqlglot's SQLite dialect is not used
        for round-trip parsing (regex handles SQLite's small DDL surface).
        """
        # SQLite uses regex-only parser for all three modes (hybrid
        # routing previously dispatched here too).
        from db.plugins.sqlite.parser.sqlite_regex_parser import SQLiteRegexParser

        if parser_type in ("hybrid", "regex"):
            return SQLiteRegexParser
        return None

    def introspector_class(self) -> Optional[Type[Any]]:
        """SQLite rich introspection is registered by PRO."""
        return None

    def vendor_queries_class(self) -> "Optional[Type[Any]]":
        """SQLite metadata queries are registered by PRO."""
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
