"""PostgreSQL :class:`DialectQuirks` — Epic 26."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Type

from db.base_quirks import BaseQuirks
from db.error import ErrorCategory

# Each entry: (compiled regex, ErrorCategory). Sourced by
# ``DatabaseErrorClassifier`` via ``error_patterns()`` (ADR-26 A2).
_ERROR_PATTERNS: List[Tuple[re.Pattern[str], ErrorCategory]] = [
    # SQLSTATE class-based matching
    (re.compile(r"SQLSTATE\s*08\w{3}", re.IGNORECASE), ErrorCategory.NETWORK),
    (re.compile(r"SQLSTATE\s*08\d{3}", re.IGNORECASE), ErrorCategory.NETWORK),
    (re.compile(r"SQLSTATE\s*57P01", re.IGNORECASE), ErrorCategory.NETWORK),  # admin_shutdown
    (re.compile(r"SQLSTATE\s*40\w{3}", re.IGNORECASE), ErrorCategory.LOCKING),
    (re.compile(r"SQLSTATE\s*23\w{3}", re.IGNORECASE), ErrorCategory.CONSTRAINT),
    (re.compile(r"SQLSTATE\s*42\w{3}", re.IGNORECASE), ErrorCategory.SQL_SYNTAX),
    (re.compile(r"SQLSTATE\s*28\w{3}", re.IGNORECASE), ErrorCategory.AUTHENTICATION),
    (re.compile(r"SQLSTATE\s*3D\w{3}", re.IGNORECASE), ErrorCategory.SCHEMA),
    (re.compile(r"SQLSTATE\s*3F\w{3}", re.IGNORECASE), ErrorCategory.SCHEMA),
    (re.compile(r"SQLSTATE\s*53\w{3}", re.IGNORECASE), ErrorCategory.RESOURCE),
    (re.compile(r"SQLSTATE\s*57\w{3}", re.IGNORECASE), ErrorCategory.INTERNAL),
]

_DROP_TRIGGER_ON_RE = re.compile(
    r"^\s*DROP\s+TRIGGER\s+(?:IF\s+EXISTS\s+)?"
    r'(?:(?:"[^"]+"|[a-zA-Z_][a-zA-Z0-9_$]*)\.)?'
    r'(?:"[^"]+"|[a-zA-Z_][a-zA-Z0-9_$]*)'
    r"\s+ON\s+",
    re.IGNORECASE,
)

if TYPE_CHECKING:
    from core.sql_generator.alter.base_alter_generator import BaseAlterGenerator
    from core.sql_generator.base_generator import BaseSqlGenerator


class PostgresqlQuirks(BaseQuirks):
    """PostgreSQL-specific :class:`DialectQuirks` for the PostgreSQL dialect.

    Covers PostgreSQL's deviations from ANSI SQL: ``"public"`` default
    schema, transactional DDL, ``DROP TABLE`` defaults to ``CASCADE``,
    dollar-quoted function bodies, ``CREATE OR REPLACE`` for procedures
    / functions, ``CREATE INDEX ... CONCURRENTLY``, ``USING <method>``
    indexes (GIN / GIST / BRIN / HASH / SPGIST that reject ASC/DESC),
    sequence-backed defaults rendered as ``nextval('seq_name')``,
    ``UNLOGGED`` / ``security_definer`` materialised views, partial
    introspection of computed columns, and ``DROP TRIGGER ... ON
    table`` (which sqlglot rejects, so it's tagged as opaque-valid DDL).
    """

    # Capability matrix (was ``_CAPABILITIES["postgresql"]`` in
    # core/sql_model/dialect.py). Owned by the plugin now.
    supports_transactions = True
    supports_transactional_ddl = True
    schema_required = True
    uppercase_identifiers = False
    clean_strategy = "introspector"
    sqlglot_dialect = "postgres"
    # PostgreSQL's permissive grammar is the last-resort sqlglot read dialect
    # for dialects that declare none of their own (DB2, CosmosDB). See
    # ``core.migration.scripting.undo_script_generator._helpers``.
    is_default_sqlglot_read_fallback = True
    # PostgreSQL is the ANSI/generic reference dialect dblift renders with when
    # a model has no dialect of its own. The SqlGeneratorFactory resolves a
    # falsy dialect to this plugin (ADR-26 E, story 26-5).
    is_ansi_reference_dialect = True
    pygments_lexer = "postgresql"
    default_schema_name = "public"
    drop_supports_if_exists = True
    drop_table_default_cascade = True
    supports_concurrent_index = True
    # Procedure / function DDL (story 26-5).
    proc_supports_create_or_replace = True
    proc_supports_language_clause = True
    proc_body_wrap_style = "dollar_quotes"
    # Index DDL (story 26-5).
    index_qualifies_with_schema = False
    index_supports_using_clause = True
    index_no_sort_types = frozenset({"GIN", "GIST", "BRIN", "HASH", "SPGIST"})
    index_with_options_style = "lowercase"
    # Sequence DDL (story 26-5).
    seq_supports_temp = True
    # View DDL (story 26-5).
    view_supports_security_with_clause = True
    # View comparison (story 26-6 Wave A).
    view_supports_unlogged_and_security = True
    serial_types_alias_integer = True
    # Table DDL (story 26-5).
    table_supports_inline_collate = True
    table_supports_deferrable_constraints = True
    table_supports_inherits = True
    # Wave A hooks (story 26-6).
    supports_constraint_triggers = True
    seq_uses_nextval_syntax = True
    computed_column_introspection_incomplete = True
    supports_virtual_computed_columns = False
    table_prefers_inline_single_pk = True
    index_comment_template = "COMMENT ON INDEX {schema_prefix}{idx_name} IS '{escaped_comment}';"
    # Wave B hooks.
    native_driver_display = "psycopg"
    connection_identifier_attrs = ("url", "host", "database")
    missing_connection_identifier_hint = (
        "PostgreSQL connection requires url or host/database fields"
    )
    native_url_schema_params = ("currentSchema", "search_path")
    # PG TIMESTAMP / TIME accept only fractional-seconds precision.
    time_type_supports_only_fractional_precision = True

    # Default canonical name; ProviderRegistry.get_quirks() passes the
    # caller's db_type so that aliases (e.g. "postgres") preserve the
    # invariant ``provider.config.database.type == provider.quirks.dialect_name``.
    def __init__(self, dialect_name: str = "postgresql") -> None:
        """Initialize PostgreSQL quirks with the dialect name."""
        super().__init__(dialect_name=dialect_name)

    def error_patterns(self) -> "List[Tuple[re.Pattern[str], ErrorCategory]]":
        """PostgreSQL SQLSTATE-class error-classification patterns (ADR-26 A2)."""
        return _ERROR_PATTERNS

    def has_connection_identifier(self, database_config: Any) -> bool:
        """PostgreSQL accepts a URL or a complete host/database pair."""

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

    def ddl_generator_class(self) -> Optional[Type["BaseSqlGenerator"]]:
        """DDL generator relocated to the paid package; registered by register_pro_generators()."""
        return None

    def alter_generator_class(self) -> Optional[Type["BaseAlterGenerator"]]:
        """ALTER generator relocated to the paid package; registered by register_pro_generators()."""
        return None

    def vendor_queries_class(self) -> "Optional[Type[Any]]":
        """PostgreSQL rich metadata queries are registered by PRO."""
        return None

    def introspector_class(self) -> "Optional[Type[Any]]":
        """PostgreSQL rich introspection is registered by PRO."""
        return None

    def parser_class(self, parser_type: str) -> Optional[type]:
        """PostgreSQL parser dispatch: hybrid → :class:`HybridParser`, sqlglot →
        :class:`SqlGlotParser` (``postgres`` dialect), regex → :class:`PostgreSqlRegexParser`."""
        if parser_type == "hybrid":
            from core.sql_parser.hybrid_parser import HybridParser

            return HybridParser
        if parser_type == "sqlglot":
            from core.sql_parser.sqlglot_parser import SqlGlotParser

            return SqlGlotParser
        if parser_type == "regex":
            from db.plugins.postgresql.parser.postgresql_regex_parser import (
                PostgreSqlRegexParser,
            )

            return PostgreSqlRegexParser
        return None

    non_transactional_sql_patterns = (
        (
            r"^CREATE\s+(UNIQUE\s+)?INDEX\s+CONCURRENTLY\b",
            "PostgreSQL CREATE INDEX CONCURRENTLY cannot run inside a transaction block",
        ),
        (
            r"^(VACUUM|REINDEX DATABASE|REINDEX SYSTEM)\b",
            "PostgreSQL maintenance command cannot run inside a transaction block",
        ),
    )

    def enrich_view_from_row(self, view: Any, row: Dict[str, Any], view_status: Any = None) -> None:
        """PostgreSQL 15+ views can declare ``security_definer`` /
        ``security_invoker``; the vendor query projects both as
        boolean-coerced columns."""
        from core.utils.row_access import get_row_value

        security_definer = get_row_value(row, "security_definer")
        security_invoker = get_row_value(row, "security_invoker")
        if security_definer is not None:
            view.security_definer = bool(security_definer)
        if security_invoker is not None:
            view.security_invoker = bool(security_invoker)

    def enrich_materialized_view_from_row(self, mview: Any, row: Dict[str, Any]) -> None:
        """PostgreSQL materialized views can be ``UNLOGGED``; the catalog
        projects ``relpersistence`` as ``is_unlogged`` (``"YES"`` / ``"NO"``)."""
        from core.utils.row_access import get_row_value

        is_unlogged = get_row_value(row, "is_unlogged")
        if is_unlogged == "YES":
            mview.unlogged = True

    def normalize_index_predicate(self, predicate: Optional[str]) -> Optional[str]:
        """Strip redundant ``::TEXT`` and ``CAST(<col> AS TEXT)`` decorations
        the catalog re-introduces, so partial-index WHERE clauses round-trip
        against the source DDL."""
        from core.utils.metadata_helpers import (
            normalize_postgresql_index_predicate,
        )

        return normalize_postgresql_index_predicate(predicate)

    def apply_index_vendor_properties(
        self, idx_data: Dict[str, Any], index_kwargs: Dict[str, Any]
    ) -> None:
        """PostgreSQL: forward ``CONCURRENTLY`` build flag and ``tablespace`` choice."""
        if idx_data.get("concurrently"):
            index_kwargs["concurrently"] = True
        if idx_data.get("tablespace"):
            index_kwargs["tablespace"] = idx_data["tablespace"]

    def fetch_unique_constraints(
        self, extractor: Any, schema: str, table: str
    ) -> "Optional[list[Any]]":
        """PostgreSQL UNIQUE constraints come from ``pg_constraint``
        (``contype='u'``). Generic index catalog rows would conflate
        standalone partial unique indexes (``CREATE UNIQUE INDEX ...
        WHERE ...``) with real named UNIQUE constraints — see
        BUG-01 / BUG-03 — collapsing the WHERE predicate on round-trip.

        Falls back to the generic vendor path if the catalog query fails (rare; preserves
        the existing error semantics)."""
        from core.utils.metadata_helpers import (
            _build_unique_constraints_from_dict,
        )

        try:
            unique_indexes = extractor._get_unique_constraints_postgresql(schema, table)
        except Exception as e:
            extractor.log.warning(f"Error getting unique constraints for {schema}.{table}: {e}")
            return []
        return _build_unique_constraints_from_dict(extractor, unique_indexes)

    def extract_partition_scheme_from_row(
        self, extractor: Any, row: Dict[str, Any], table: Any
    ) -> None:
        """PostgreSQL: parse ``partition_definition`` (``RANGE (col)`` /
        ``LIST (col)`` / ``HASH (col)``) into ``partition_method`` +
        ``partition_columns``."""
        import re

        from core.utils.row_access import get_row_value

        part_def = get_row_value(row, "partition_definition")
        if not part_def:
            return
        match = re.match(r"(\w+)\s*\(([^)]+)\)", part_def)
        if match:
            table.partition_method = match.group(1).upper()
            cols_expr = match.group(2).strip()
            table.partition_columns = [c.strip() for c in cols_expr.split(",")]

    def filter_user_defined_types(
        self,
        extractor: Any,
        schema: str,
        user_defined_types: "list[Any]",
        get_tables_fn: Any,
    ) -> "list[Any]":
        """Drop the auto-created composite types that PostgreSQL emits
        for every regular table (``pg_type`` rows whose ``typcategory='C'``
        and whose ``typname`` matches a table name in the same schema).

        Without this filter, every table would surface a duplicate UDT
        in the introspection output. The filter is a no-op when
        ``get_tables_fn`` isn't provided (no schema context to compare
        against)."""
        if not get_tables_fn:
            return user_defined_types
        all_tables = get_tables_fn(schema, include_views=True)
        relation_names = {t.name.lower() for t in all_tables}
        relation_names.update(self._postgresql_relation_type_names(extractor, schema))
        filtered = []
        for udt in user_defined_types:
            if udt.type_category.upper() == "C" and udt.name.lower() in relation_names:
                extractor.log.debug(f"Filtering out relation-generated composite type: {udt.name}")
                continue
            filtered.append(udt)
        return filtered

    def _postgresql_relation_type_names(self, extractor: Any, schema: str) -> "set[str]":
        """Return table/view/materialized-view row-type names for PostgreSQL."""
        from core.utils.row_access import get_row_value

        query_executor = getattr(getattr(extractor, "provider", None), "query_executor", None)
        connection = getattr(extractor, "connection", None)
        if not query_executor or not connection:
            return set()

        sql = """
            SELECT c.relname
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON c.relnamespace = n.oid
            WHERE n.nspname = ?
              AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
        """
        try:
            rows = query_executor.execute_query(connection, sql, [schema])
        except Exception as exc:
            extractor.log.debug(f"Could not load PostgreSQL relation row types: {exc}")
            return set()
        return {
            str(get_row_value(row, "relname")).lower()
            for row in rows
            if get_row_value(row, "relname")
        }

    def enrich_table_extra(self, extractor: Any, schema: str, table_name: str, table: Any) -> None:
        """PostgreSQL row security + table inheritance + RLS policies.

        Three vendor queries (``pg_class.relrowsecurity`` /
        ``relforcerowsecurity``, ``pg_inherits``, ``pg_policies``)
        run on demand; each is gated by the corresponding
        ``vendor_queries.get_*_query`` returning a non-``None`` SQL
        string so older PostgreSQL versions (or trimmed query sets)
        simply skip the unsupported call.
        """
        from core.utils.row_access import get_row_value, parse_json_array

        vendor_queries = extractor.vendor_queries
        if not vendor_queries:
            return

        try:
            query, params = vendor_queries.get_table_row_security_query(schema, table_name)
            if query:
                results = extractor.provider.query_executor.execute_query(
                    extractor.connection, query, params
                )
                if results:
                    row = results[0]
                    # Only persist when True — the absence of the key is the
                    # canonical "off" state (matches the default-deletion the
                    # former property setter applied, keeping snapshots stable).
                    if get_row_value(row, "row_security") == "YES":
                        table.set_dialect_option("postgresql", "row_security", True)
                    if get_row_value(row, "force_row_security") == "YES":
                        table.set_dialect_option("postgresql", "force_row_security", True)
        except Exception as e:
            extractor.log.debug(f"Could not get row security flags for {schema}.{table_name}: {e}")
            extractor.track_warning(
                f"Could not get row security flags: {e}",
                object_type="table",
                object_name=table_name,
                property_name="row_security",
                exception=e,
            )

        try:
            query, params = vendor_queries.get_table_inheritance_query(schema, table_name)
            if query:
                results = extractor.provider.query_executor.execute_query(
                    extractor.connection, query, params
                )
                if results:
                    inherits = []
                    for row in results:
                        parent_schema = get_row_value(row, "parent_schema")
                        parent_table = get_row_value(row, "parent_table")
                        if parent_schema and parent_table:
                            if parent_schema == schema:
                                inherits.append(parent_table)
                            else:
                                inherits.append(f"{parent_schema}.{parent_table}")
                    if inherits:
                        table.set_dialect_option("postgresql", "inherits", inherits)
        except Exception as e:
            extractor.log.debug(f"Could not get table inheritance for {schema}.{table_name}: {e}")
            extractor.track_warning(
                f"Could not get table inheritance: {e}",
                object_type="table",
                object_name=table_name,
                property_name="inherits",
                exception=e,
            )

        try:
            query, params = vendor_queries.get_policies_query(schema, table_name)
            if query:
                results = extractor.provider.query_executor.execute_query(
                    extractor.connection, query, params
                )
                policies: list[Dict[str, Any]] = []
                for row in results:
                    policies.append(
                        {
                            "name": get_row_value(row, "policy_name"),
                            "command": get_row_value(row, "policy_command"),
                            "permissive": get_row_value(row, "is_permissive") == "YES",
                            "roles": parse_json_array(get_row_value(row, "roles")),
                            "qual": get_row_value(row, "policy_qual"),
                            "with_check": get_row_value(row, "policy_with_check"),
                        }
                    )
                if policies:
                    table.set_dialect_option("postgresql", "policies", policies)
        except Exception as e:
            extractor.log.debug(
                f"Could not get row security policies for {schema}.{table_name}: {e}"
            )
            extractor.track_warning(
                f"Could not get row security policies: {e}",
                object_type="table",
                object_name=table_name,
                property_name="policies",
                exception=e,
            )

    def supplement_table_list(
        self, extractor: Any, schema: str, existing_tables: "list[Any]"
    ) -> "list[Any]":
        """Append declarative-partitioned tables (``relkind = 'p'``).

        The regular table query intentionally keeps table categories focused.
        This vendor query adds partitioned parents; columns and constraints are populated through
        the extractor's sub-extractors.
        """
        from core.sql_model.table import Table
        from core.utils.row_access import get_row_value

        if not extractor.vendor_queries:
            return existing_tables

        try:
            query, params = extractor.vendor_queries.get_partitioned_tables_query(schema)
            results = extractor.provider.query_executor.execute_query(
                extractor.connection, query, params
            )
            existing_names = {t.name.lower() for t in existing_tables}
            for row in results:
                pt_name = get_row_value(row, "table_name")
                if not pt_name or pt_name.lower() in existing_names:
                    continue
                remarks = get_row_value(row, "remarks")
                pt = Table(
                    name=pt_name,
                    schema=schema,
                    dialect=extractor.dialect,
                    comment=remarks if remarks else None,
                    temporary=False,
                )
                if extractor.column_extractor:
                    pt.columns = extractor.column_extractor.get_columns(schema, pt_name)
                if extractor.constraint_extractor:
                    pt.constraints = extractor.constraint_extractor.get_constraints(schema, pt_name)
                existing_tables.append(pt)
                extractor.log.info(f"Added partitioned table (relkind='p'): {schema}.{pt_name}")
        except Exception as e:
            extractor.log.warning(f"Could not get partitioned tables for {schema}: {e}")

        return existing_tables

    def is_temporary_sequence(self, row: "Dict[str, Any]") -> bool:
        """PostgreSQL sequences may be ``CREATE TEMPORARY SEQUENCE`` —
        the vendor query projects ``relpersistence`` as ``is_temporary``
        with values ``"YES"`` / ``"NO"``."""
        from core.utils.row_access import get_row_value

        return bool(get_row_value(row, "is_temporary") == "YES")

    def fk_reference_query(
        self, schema: str, table: str, col: str
    ) -> "Tuple[Optional[str], list[Any]]":
        """Return the PostgreSQL ``information_schema`` query for FKs targeting ``col``."""
        sql = """
            SELECT
                tc.constraint_name,
                tc.table_schema || '.' || tc.table_name as table_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
            JOIN information_schema.constraint_column_usage ccu
                ON ccu.constraint_name = tc.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY'
                AND ccu.table_schema = $1
                AND ccu.table_name = $2
                AND ccu.column_name = $3
        """
        return (sql, self.fk_reference_bind_params(schema, table, col))

    def index_reference_query(
        self, schema: str, table: str, col: str
    ) -> "Tuple[Optional[str], list[Any]]":
        """PostgreSQL ``pg_index`` / ``pg_class`` query listing indexes covering ``col``."""
        sql = """
            SELECT i.relname as index_name
            FROM pg_index ix
            JOIN pg_class i ON i.oid = ix.indexrelid
            JOIN pg_class t ON t.oid = ix.indrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey)
            WHERE n.nspname = $1
                AND t.relname = $2
                AND a.attname = $3
        """
        return (sql, [schema, table, col])

    def is_sqlglot_opaque_valid_ddl(self, sql_content: str) -> bool:
        """PG ``DROP TRIGGER name ON table`` — valid DDL that sqlglot rejects."""
        return _DROP_TRIGGER_ON_RE.search(sql_content) is not None

    # Story 26-3: PostgreSQL DROP EXTENSION uses extension namespace.
    def render_drop_for_object(
        self,
        obj_type: str,
        obj_name: str,
        schema_prefix: str,
        table_name: Optional[str],
    ) -> Optional[str]:
        """``DROP EXTENSION IF EXISTS`` — extensions are unschema-qualified in PostgreSQL.

        Other object types defer to the generic ``DROP ... IF EXISTS`` fallback.
        """
        if obj_type == "EXTENSION":
            return f"DROP EXTENSION IF EXISTS {obj_name}"
        return None

    # Story 27-1: type normalization — strip precision from fixed-width float
    # types and reorder TIMESTAMP {WITH|WITHOUT} TIME ZONE(n) → TIMESTAMP(n)
    # {WITH|WITHOUT} TIME ZONE so downstream comparators see a canonical form.
    def normalize_column_data_type(self, col: object, data_type: str) -> str:
        """Strip precision from fixed-width floats; canonicalise ``TIMESTAMP(n) {WITH|WITHOUT} TZ``.

        ``FLOAT4(...)`` / ``FLOAT8(...)`` / ``REAL(...)`` / ``DOUBLE PRECISION(...)`` lose
        the precision suffix (PostgreSQL ignores it), and ``TIMESTAMP {WITH|WITHOUT} TIME
        ZONE(n)`` is reordered to ``TIMESTAMP(n) {WITH|WITHOUT} TIME ZONE`` (canonical form).
        """
        import re

        dt = data_type.upper()
        if dt.startswith("FLOAT4("):
            return "FLOAT4"
        if dt.startswith("FLOAT8("):
            return "FLOAT8"
        if dt.startswith("REAL("):
            return "REAL"
        if dt.startswith("DOUBLE PRECISION("):
            return "DOUBLE PRECISION"
        m = re.search(r"TIMESTAMP WITHOUT TIME ZONE\((\d+)\)", dt)
        if m:
            return f"TIMESTAMP({m.group(1)}) WITHOUT TIME ZONE"
        m = re.search(r"TIMESTAMP WITH TIME ZONE\((\d+)\)", dt)
        if m:
            return f"TIMESTAMP({m.group(1)}) WITH TIME ZONE"
        return data_type

    def enhance_columns(
        self, extractor: Any, schema: str, table: str, columns: "list[Any]"
    ) -> None:
        """Keep PostgreSQL sequence-backed defaults explicit in introspected columns."""
        for col in columns:
            default_value = str(getattr(col, "default_value", "") or "").lower()
            if "nextval(" not in default_value:
                continue
            data_type = str(getattr(col, "data_type", "") or "").lower()
            base_type = self._PG_SERIAL_BASE_TYPES.get(data_type)
            if base_type:
                col.data_type = base_type
            col.is_identity = False
            col.identity_generation = None
            col.identity_seed = None
            col.identity_increment = None

    def unwrap_default_value(self, default_str: str, column: object) -> str:
        """Normalize PostgreSQL sequence defaults to native ``nextval('seq'::regclass)``."""
        match = re.match(
            r"^\s*nextval\s*\(\s*cast\s*\(\s*'([^']+)'\s+as\s+regclass\s*\)\s*\)\s*$",
            default_str,
            re.IGNORECASE,
        )
        if match:
            return f"nextval('{match.group(1)}'::regclass)"
        return default_str

    # round_trip extra object types (story 27-6).
    def round_trip_extra_object_types(self) -> "list[str]":
        """PostgreSQL round-trip covers user-defined types, materialized views, and extensions."""
        return ["user_defined_types", "materialized_views", "extensions"]

    # Column ALTER hooks (Epic 27 column_converter refactor).
    def render_column_nullable_change(
        self, col_diff: object, formatted_table: str, formatted_column: str, dialect: str
    ) -> "Optional[object]":
        """``ALTER TABLE … ALTER COLUMN <c> SET|DROP NOT NULL`` — PostgreSQL nullable toggle.

        SET NOT NULL emits a pre-check counting NULL rows so a violating migration
        fails cleanly before the ALTER runs.
        """
        from core.sql_generator.sql_statement import SqlStatement

        nullable_diff = getattr(col_diff, "nullable_diff", None)
        if nullable_diff is None:
            return None
        expected_nullable, _ = nullable_diff
        if not expected_nullable:
            sql = f"ALTER TABLE {formatted_table} ALTER COLUMN {formatted_column} SET NOT NULL;"
            return SqlStatement(
                sql=sql,
                statement_type="ALTER",
                object_type="COLUMN",
                object_name=f"{formatted_table}.{formatted_column}",
                dialect=dialect,
                pre_check=f"SELECT COUNT(*) FROM {formatted_table} WHERE {formatted_column} IS NULL;",
                error_if_check_fails=True,
                error_message="Cannot set NOT NULL: column contains NULL values",
            )
        return SqlStatement(
            sql=f"ALTER TABLE {formatted_table} ALTER COLUMN {formatted_column} DROP NOT NULL;",
            statement_type="ALTER",
            object_type="COLUMN",
            object_name=f"{formatted_table}.{formatted_column}",
            dialect=dialect,
        )

    def render_column_default_change(
        self, col_diff: object, formatted_table: str, formatted_column: str, dialect: str
    ) -> "Optional[object]":
        """``ALTER TABLE … ALTER COLUMN <c> SET|DROP DEFAULT`` — PostgreSQL DEFAULT change."""
        from core.sql_generator.sql_statement import SqlStatement

        default_diff = getattr(col_diff, "default_diff", None)
        if default_diff is None:
            return None
        expected_default, _ = default_diff
        if expected_default:
            sql = f"ALTER TABLE {formatted_table} ALTER COLUMN {formatted_column} SET DEFAULT {expected_default};"
        else:
            sql = f"ALTER TABLE {formatted_table} ALTER COLUMN {formatted_column} DROP DEFAULT;"
        return SqlStatement(
            sql=sql,
            statement_type="ALTER",
            object_type="COLUMN",
            object_name=f"{formatted_table}.{formatted_column}",
            dialect=dialect,
        )

    def render_column_type_change(
        self, col_diff: object, formatted_table: str, formatted_column: str, dialect: str
    ) -> "Optional[object]":
        """``ALTER TABLE … ALTER COLUMN <c> TYPE <type>`` — PostgreSQL column-type change form."""
        from core.sql_generator.sql_statement import SqlStatement

        data_type_diff = getattr(col_diff, "data_type_diff", None)
        if data_type_diff is None:
            return None
        expected_type, _ = data_type_diff
        return SqlStatement(
            sql=f"ALTER TABLE {formatted_table} ALTER COLUMN {formatted_column} TYPE {expected_type};",
            statement_type="ALTER",
            object_type="COLUMN",
            object_name=f"{formatted_table}.{formatted_column}",
            dialect=dialect,
        )

    def render_column_collation_change(
        self, col_diff: object, formatted_table: str, formatted_column: str, dialect: str
    ) -> "Optional[object]":
        """``ALTER TABLE … ALTER COLUMN <c> SET COLLATION <coll>`` — PG collation change."""
        from core.sql_generator.sql_statement import SqlStatement

        collation_diff = getattr(col_diff, "collation_diff", None)
        if collation_diff is None:
            return None
        expected_collation, _ = collation_diff
        return SqlStatement(
            sql=f"ALTER TABLE {formatted_table} ALTER COLUMN {formatted_column} SET COLLATION {expected_collation};",
            statement_type="ALTER",
            object_type="COLUMN",
            object_name=f"{formatted_table}.{formatted_column}",
            dialect=dialect,
        )

    # Story 27-2: identity clause — PostgreSQL serial types encode the
    # auto-increment in the type name; GENERATED … AS IDENTITY for plain
    # integer types.
    _PG_SERIAL_TYPES = frozenset(
        {"serial", "serial4", "bigserial", "serial8", "smallserial", "serial2"}
    )
    _PG_SERIAL_BASE_TYPES = {
        "serial": "INTEGER",
        "serial4": "INTEGER",
        "bigserial": "BIGINT",
        "serial8": "BIGINT",
        "smallserial": "SMALLINT",
        "serial2": "SMALLINT",
    }

    def render_identity_clause(self, col: object) -> "Optional[str]":
        """PostgreSQL identity: ``None`` for ``SERIAL*`` types (auto-increment is in the type name),
        otherwise ``GENERATED [ALWAYS|BY DEFAULT] AS IDENTITY`` per ``identity_generation``."""
        data_type = (getattr(col, "data_type", "") or "").lower()
        if data_type in self._PG_SERIAL_TYPES:
            return None
        generation = (getattr(col, "identity_generation", None) or "").upper()
        if generation == "ALWAYS":
            return "GENERATED ALWAYS AS IDENTITY"
        return "GENERATED BY DEFAULT AS IDENTITY"

    def type_equivalents(self) -> "dict[str, str]":
        """PostgreSQL alias → canonical type map.

        Notably the ``SERIAL`` family (``SERIAL`` / ``SERIAL2/4/8`` / ``BIGSERIAL`` /
        ``SMALLSERIAL``) aliases to its underlying integer width; ``INT2/4/8`` to
        ``SMALLINT`` / ``INTEGER`` / ``BIGINT``; ``DECIMAL`` → ``NUMERIC``; ``FLOAT4/8``
        → ``REAL`` / ``DOUBLE PRECISION``; ``TIMESTAMPTZ`` / ``TIMETZ`` add ``WITH TIME ZONE``.
        """
        return {
            "INT": "INTEGER",
            "INT2": "SMALLINT",
            "INT4": "INTEGER",
            "INT8": "BIGINT",
            "SERIAL": "INTEGER",
            "SERIAL2": "SMALLINT",
            "SERIAL4": "INTEGER",
            "SERIAL8": "BIGINT",
            "BIGSERIAL": "BIGINT",
            "SMALLSERIAL": "SMALLINT",
            "CHARACTER VARYING": "VARCHAR",
            "CHARACTER": "CHAR",
            "DECIMAL": "NUMERIC",
            "FLOAT4": "REAL",
            "FLOAT8": "DOUBLE PRECISION",
            "DOUBLE": "DOUBLE PRECISION",
            "BOOL": "BOOLEAN",
            "TIMESTAMPTZ": "TIMESTAMP WITH TIME ZONE",
            "TIMETZ": "TIME WITH TIME ZONE",
        }

    version_specific_type_mappings = {("postgresql", "9.4+"): {"JSONB": "JSON"}}

    def type_preferences(self) -> "dict[str, str]":
        """PostgreSQL keeps ANSI names — ``INTEGER`` / ``VARCHAR`` / ``TIMESTAMP`` unchanged."""
        return {"INTEGER": "INTEGER", "VARCHAR": "VARCHAR", "TIMESTAMP": "TIMESTAMP"}

    def render_computed_column(
        self, col: Any, formatted_col_name: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """PostgreSQL: ``GENERATED ALWAYS AS (expr) [STORED]``."""
        if not getattr(col, "is_computed", False) or not getattr(col, "computed_expression", None):
            return None, None
        if getattr(col, "computed_stored", False):
            return f"GENERATED ALWAYS AS ({col.computed_expression}) STORED", None
        return f"GENERATED ALWAYS AS ({col.computed_expression})", None


__all__ = ["PostgresqlQuirks"]
