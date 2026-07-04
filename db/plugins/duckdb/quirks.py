"""DuckDB :class:`DialectQuirks` — provider capability overlay."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional, Type

from db.base_quirks import BaseQuirks

if TYPE_CHECKING:
    from core.sql_generator.alter.base_alter_generator import BaseAlterGenerator
    from core.sql_generator.base_generator import BaseSqlGenerator


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
    default_schema_name = "main"
    boolean_false_literal = "FALSE"  # native BOOLEAN, not 0/1
    drop_supports_if_exists = True
    table_drop_style = "cascade"  # DuckDB supports DROP TABLE ... CASCADE
    # Wave B hooks — embedded, file-based, no credentials (mirrors SQLite).
    native_driver_display = "duckdb"
    requires_credentials = False
    url_optional_when_file_path_given = True
    connection_identifier_attrs = ("url", "path", "database")

    def __init__(self, dialect_name: str = "duckdb") -> None:
        """Initialize DuckDB quirks with the dialect name."""
        super().__init__(dialect_name=dialect_name)

    def parser_class(self, parser_type: str) -> Optional[type]:
        """DuckDB parser dispatch: hybrid → :class:`HybridParser`,
        sqlglot → :class:`SqlGlotParser` (``duckdb`` dialect)."""
        if parser_type == "hybrid":
            from core.sql_parser.hybrid_parser import HybridParser

            return HybridParser
        if parser_type == "sqlglot":
            from core.sql_parser.sqlglot_parser import SqlGlotParser

            return SqlGlotParser
        if parser_type == "regex":
            from db.plugins.duckdb.parser.duckdb_regex_parser import DuckDBRegexParser

            return DuckDBRegexParser
        return None

    # PRO hooks — the paid packages register these (Pro tier).
    def ddl_generator_class(self) -> Optional[Type["BaseSqlGenerator"]]:
        """DDL generator lives in the Pro package; registered by register_pro_generators()."""
        return None

    def alter_generator_class(self) -> Optional[Type["BaseAlterGenerator"]]:
        """ALTER generator lives in the Pro package; registered by register_pro_generators()."""
        return None

    def introspector_class(self) -> Optional[Type[Any]]:
        """DuckDB rich introspection is registered by PRO."""
        return None

    def vendor_queries_class(self) -> "Optional[Type[Any]]":
        """DuckDB metadata queries are registered by PRO."""
        return None

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

    def type_preferences(self) -> "dict[str, str]":
        """DuckDB keeps ANSI names — ``INTEGER`` / ``VARCHAR`` / ``TIMESTAMP`` unchanged."""
        return {"INTEGER": "INTEGER", "VARCHAR": "VARCHAR", "TIMESTAMP": "TIMESTAMP"}


__all__ = ["DuckDBQuirks"]
