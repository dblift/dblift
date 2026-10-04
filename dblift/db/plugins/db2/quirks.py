"""DB2 :class:`DialectQuirks`."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Type

from dblift.db.base_quirks import BaseQuirks
from dblift.db.error import ErrorCategory

if TYPE_CHECKING:
    from dblift.db.generator_protocol import AlterGeneratorProtocol, SqlGeneratorProtocol


# Each entry: (compiled regex, ErrorCategory). Sourced by
# ``DatabaseErrorClassifier`` via ``error_patterns()`` (ADR-26 A2).
_ERROR_PATTERNS: List[Tuple[re.Pattern[str], ErrorCategory]] = [
    # Connection errors (consolidated from the DB2 query executor)
    (re.compile(r"errorcode=-4499", re.IGNORECASE), ErrorCategory.NETWORK),
    (re.compile(r"sqlstate=08001", re.IGNORECASE), ErrorCategory.NETWORK),
    (re.compile(r"sqlstate=08\w{3}", re.IGNORECASE), ErrorCategory.NETWORK),
    (
        re.compile(r"disconnectnontransientconnectionexception", re.IGNORECASE),
        ErrorCategory.NETWORK,
    ),
    (re.compile(r"disconnectexception", re.IGNORECASE), ErrorCategory.NETWORK),
    (re.compile(r"communication\s+error", re.IGNORECASE), ErrorCategory.NETWORK),
    # Locking
    (re.compile(r"sql0911n", re.IGNORECASE), ErrorCategory.LOCKING),
    (re.compile(r"sqlstate=40001", re.IGNORECASE), ErrorCategory.LOCKING),
    # Authentication
    (re.compile(r"sqlstate=28000", re.IGNORECASE), ErrorCategory.AUTHENTICATION),
    # SQL Syntax
    (re.compile(r"sqlstate=42\w{3}", re.IGNORECASE), ErrorCategory.SQL_SYNTAX),
    # Constraint
    (re.compile(r"sqlstate=23\w{3}", re.IGNORECASE), ErrorCategory.CONSTRAINT),
    # Resource
    (re.compile(r"sqlstate=57\w{3}", re.IGNORECASE), ErrorCategory.RESOURCE),
]


class Db2Quirks(BaseQuirks):
    """DB2-specific :class:`DialectQuirks` for the IBM Db2 dialect.

    Covers Db2's deviations from ANSI SQL: uppercase-folded unquoted
    identifiers, ``FETCH FIRST n ROWS ONLY`` (no ``LIMIT``), ``ALIAS``
    instead of ``SYNONYM``, CHECK / self-FK constraints emitted via
    ``ALTER TABLE`` (Db2 rejects them inline), no ``DROP INDEX IF EXISTS``,
    ``COMPRESS YES/NO`` storage clause, and migration-engine semantics
    where ``clean_schema`` auto-commits and DDL needs an explicit commit.
    """

    # Capability matrix (was ``_CAPABILITIES["db2"]``).
    supports_transactions = True
    supports_transactional_ddl = True
    schema_required = True
    uppercase_identifiers = True
    clean_strategy = "introspector"
    # import-flyway reads Flyway's quoted lowercase source table directly, as on
    # Oracle; get_applied_migrations would uppercase the name and miss it.
    flyway_source_table_case_sensitive = True

    def is_schema_history_race_error(self, error_message: str) -> bool:
        """DB2 has no ``CREATE TABLE IF NOT EXISTS``; a concurrent migration
        bootstrap loses with SQL0601N ("the name of the object to be
        created is identical to the existing name"), SQLSTATE 42710 — text
        the base English markers don't contain."""
        if "42710" in (error_message or ""):
            return True
        return super().is_schema_history_race_error(error_message)

    connection_probe_sql = "SELECT 1 FROM SYSIBM.SYSDUMMY1"
    unquoted_identifier_case = "uppercase"
    connection_identifier_attrs = ("url", "host", "database")
    missing_connection_identifier_hint = "DB2 connection requires url or host/database fields"
    native_url_schema_params = ("currentSchema", "schema")
    proc_param_supports_default = False  # DB2 rejects ``= default``
    index_drop_standalone_supports_if_exists = False  # DB2 has no DROP INDEX IF EXISTS
    # Wave B hooks.
    native_driver_display = "ibm_db_sa"
    # validate-sql offline placeholder.
    lint_placeholder_url = "db2://localhost:50000/DBLIFT_VALIDATE_SQL"
    # DB2 TIMESTAMP / TIME accept only fractional-seconds precision,
    # not the generic ``(width, scale)`` pair.
    time_type_supports_only_fractional_precision = True
    # DB2 identity metadata needs a catalog fallback in addition to the
    # projected column flag; ColumnExtractor consults a preloaded identity
    # column set when this is True.
    identity_uses_catalog_fallback = True

    def correct_computed_column_flag(
        self, is_generated: bool, column_def: "Optional[str]", is_identity: bool
    ) -> bool:
        """DB2 catalog rows can mark IDENTITY columns as generated/computed — that's
        wrong, IDENTITY is a separate concept. Suppress the false flag
        when ``is_identity`` is true; trust the catalog flag otherwise so
        the SYSCAT enrichment can still flip real GENERATED-AS columns
        on later."""
        if is_generated and is_identity:
            return False
        return is_generated

    def has_connection_identifier(self, database_config: Any) -> bool:
        """DB2 accepts a URL or a complete host/database pair."""

        def _value(attr: str) -> str:
            raw = (
                database_config.get(attr)
                if isinstance(database_config, dict)
                else getattr(database_config, attr, None)
            )
            return str(raw or "").strip()

        if _value("url"):
            return True
        return bool(_value("host") and _value("database"))

    def __init__(self, dialect_name: str = "db2") -> None:
        """Initialize Db2 quirks with the dialect name."""
        super().__init__(dialect_name=dialect_name)

    def error_patterns(self) -> "List[Tuple[re.Pattern[str], ErrorCategory]]":
        """DB2 SQLSTATE / errorcode error-classification patterns (ADR-26 A2)."""
        return _ERROR_PATTERNS

    def ddl_generator_class(self) -> Optional[Type["SqlGeneratorProtocol"]]:
        """DDL generator is supplied by an installed extension package."""
        return None

    def alter_generator_class(self) -> Optional[Type["AlterGeneratorProtocol"]]:
        """ALTER generator is supplied by an installed extension package."""
        return None

    def parser_class(self, parser_type: str) -> Optional[type]:
        """Return the Db2 parser class for ``parser_type``, or ``None``.

        ``"hybrid"`` → ``HybridParser`` (which falls back to regex since
        sqlglot has no Db2 dialect), ``"regex"`` → ``DB2RegexParser``,
        ``"sqlglot"`` → ``None`` (no Db2 sqlglot dialect — factory raises
        ``UnsupportedDialectError``, matching the legacy ``SQLGLOT_PARSER_MAP``).
        """
        if parser_type == "hybrid":
            from dblift.core.sql_parser.hybrid_parser import HybridParser

            return HybridParser
        if parser_type == "regex":
            from dblift.db.plugins.db2.parser.db2_regex_parser import DB2RegexParser

            return DB2RegexParser
        return None

    def normalize_view_name(self, name: str) -> str:
        """DB2 returns view names uppercase from SYSCAT.VIEWS but
        downstream catalog lookups use lowercase keys."""
        return name.lower()

    def apply_vendor_table_properties(self, table: Any, row: Dict[str, Any]) -> None:
        """Apply DB2 tablespace + compression + storage params."""
        from dblift.core.utils.row_access import get_row_value

        tablespace = get_row_value(row, "tablespace_name")
        if tablespace:
            table.tablespace = tablespace
        is_compressed = get_row_value(row, "is_compressed")
        if is_compressed == "YES":
            table.compress = True
            compress_type = get_row_value(row, "compress_type")
            if compress_type and compress_type != "N":
                table.compress_type = compress_type
        elif is_compressed == "NO":
            table.compress = False
        # DB2 storage parameters share the Oracle ``dialect_options`` namespace
        # (both render PCTFREE/PCTUSED/INITIAL/NEXT). Resolve that canonical
        # namespace from the registry via the storage-params capability so this
        # plugin names no foreign dialect (ADR-26 E).
        from dblift.db.provider_registry import ProviderRegistry

        storage_ns = ProviderRegistry.canonical_dialect_name_for_capability(
            "table_supports_storage_params"
        )
        for attr, col in (
            ("pctfree", "pctfree_value"),
            ("pctused", "pctused_value"),
            ("initial", "initial_value"),
            ("next", "next_extent_size"),
        ):
            val = get_row_value(row, col)
            if val is not None and storage_ns:
                try:
                    table.set_dialect_option(storage_ns, attr, int(val))
                except (ValueError, TypeError):
                    pass

    def fetch_unique_constraints(
        self, extractor: Any, schema: str, table: str
    ) -> "Optional[list[Any]]":
        """DB2 UNIQUE constraints come from ``SYSCAT.TABCONST`` (``TYPE='U'``)
        — more reliable than indexes for multi-column constraints.
        Names are not sanitized: TABCONST already represents
        user-meaningful constraints."""
        if not getattr(extractor, "vendor_queries", None):
            return None
        result: "list[Any]" = extractor._get_unique_constraints_via_vendor_queries(schema, table)
        return result

    def sanitize_constraint_name(self, name: "Optional[str]") -> "Optional[str]":
        """DB2 drops constraint names matching ``SQL\\d+`` (system-generated
        in SYSCAT for unnamed constraints, e.g. ``SQL251208171332370``)."""
        import re

        if not name:
            return name
        normalized = name.strip().upper()
        if re.match(r"^SQL\d+$", normalized):
            return None
        return name

    def extract_partition_scheme_from_row(
        self, extractor: Any, row: Dict[str, Any], table: Any
    ) -> None:
        """DB2: ``partition_definition`` (from ``SYSCAT.DATAPARTITIONS``).
        DB2 only supports range partitioning."""
        import re

        from dblift.core.utils.row_access import get_row_value

        part_def = get_row_value(row, "partition_definition")
        if not part_def:
            return
        table.partition_method = "RANGE"
        cols = re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\b", part_def)
        if cols:
            table.partition_columns = cols

    def extract_computed_column_expression(self, text: "Optional[str]") -> "Optional[str]":
        """DB2 SYSCAT.COLUMNS.TEXT wraps computed expressions in
        ``GENERATED ALWAYS AS (...)`` (sometimes with extra ``AS`` /
        outer parens). Pull out the inner expression so it can be
        compared against the source DDL."""
        import re

        if not text:
            return text
        expr = text
        match = re.search(
            r"GENERATED\s+ALWAYS\s+AS\s*\((.+?)\)",
            expr,
            re.IGNORECASE | re.DOTALL,
        )
        if match:
            expr = match.group(1).strip()
            # Strip leading "AS " that may slip through the regex.
            expr = re.sub(r"^\s*AS\s+", "", expr, flags=re.IGNORECASE).strip()
            # Handle nested "AS (...)" wrappers.
            as_paren_match = re.match(
                r"^\s*AS\s*\((.*)\)\s*$",
                expr,
                re.IGNORECASE | re.DOTALL,
            )
            if as_paren_match:
                expr = as_paren_match.group(1).strip()
            elif expr.startswith("(") and expr.endswith(")"):
                if expr.count("(") == 1 and expr.count(")") == 1:
                    expr = expr[1:-1].strip()
            return expr
        # No GENERATED-AS wrapper — try the trailing "AS <expr>" fallback.
        # Matches the legacy behaviour exactly: take the text after the
        # final ``AS``, strip outer parens and any further leading
        # ``AS ``, and return the (possibly empty) result so the
        # enricher's ``if not computation_expr: continue`` guard skips
        # columns whose ``AS`` wrapper produced no actual expression.
        if "AS" in expr.upper():
            parts = expr.rsplit("AS", 1)
            if len(parts) > 1:
                tail = parts[1].strip()
                if tail.startswith("(") and tail.endswith(")"):
                    tail = tail[1:-1].strip()
                tail = re.sub(r"^\s*AS\s+", "", tail, flags=re.IGNORECASE).strip()
                return tail
        return expr

    def type_equivalents(self) -> "dict[str, str]":
        """Db2 alias → canonical type map.

        Examples: ``INT`` → ``INTEGER``, ``LONG VARCHAR`` → ``VARCHAR``,
        ``DOUBLE PRECISION`` → ``DOUBLE``.
        """
        return {
            "INT": "INTEGER",
            "CHARACTER VARYING": "VARCHAR",
            "CHARACTER": "CHAR",
            "LONG VARCHAR": "VARCHAR",
            "LONG VARGRAPHIC": "DBCLOB",
            "DOUBLE PRECISION": "DOUBLE",
        }


__all__ = ["Db2Quirks"]
