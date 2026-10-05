"""PostgreSQL :class:`DialectQuirks`."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from dblift.db.base_quirks import BaseQuirks
from dblift.db.error import ErrorCategory
from dblift.db.feature_gate import FeatureGate

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
    # ``dblift.core.migration.scripting.undo_script_generator._helpers``.
    is_default_sqlglot_read_fallback = True
    # PostgreSQL is the ANSI/generic rendering reference when a model has no
    # dialect of its own, resolved via ProviderRegistry.reference_dialect_name.
    is_ansi_reference_dialect = True
    default_schema_name = "public"
    drop_supports_if_exists = True
    drop_table_default_cascade = True
    # Index DDL.
    index_no_sort_types = frozenset({"GIN", "GIST", "BRIN", "HASH", "SPGIST"})
    table_supports_inherits = True
    supports_virtual_computed_columns = False
    # Wave B hooks.
    native_driver_display = "psycopg"
    connection_identifier_attrs = ("url", "host", "database")
    missing_connection_identifier_hint = (
        "PostgreSQL connection requires url or host/database fields"
    )
    native_url_schema_params = ("currentSchema", "search_path")
    # PG TIMESTAMP / TIME accept only fractional-seconds precision.
    time_type_supports_only_fractional_precision = True
    # validate-sql offline placeholder. Inherited by every PG-wire plugin
    # (CockroachDB, Redshift, Citus, YugabyteDB, Neon, Supabase, AlloyDB,
    # Aurora PostgreSQL, TimescaleDB) — they all keep the postgresql:// scheme.
    lint_placeholder_url = "postgresql://localhost/dblift_validate_sql"

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

    def parser_class(self, parser_type: str) -> Optional[type]:
        """PostgreSQL parser dispatch: hybrid → :class:`HybridParser`, sqlglot →
        :class:`SqlGlotParser` (``postgres`` dialect), regex → :class:`PostgreSqlRegexParser`."""
        if parser_type == "hybrid":
            from dblift.core.sql_parser.hybrid_parser import HybridParser

            return HybridParser
        if parser_type == "sqlglot":
            from dblift.core.sql_parser.sqlglot_parser import SqlGlotParser

            return SqlGlotParser
        if parser_type == "regex":
            from dblift.db.plugins.postgresql.parser.postgresql_regex_parser import (
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
            r"^(VACUUM|REINDEX DATABASE|REINDEX SCHEMA|REINDEX SYSTEM)\b",
            "PostgreSQL maintenance command cannot run inside a transaction block",
        ),
        (
            r"^REINDEX\s+(TABLE|INDEX|SCHEMA|DATABASE|SYSTEM)\s+CONCURRENTLY\b",
            "PostgreSQL REINDEX CONCURRENTLY cannot run inside a transaction block",
        ),
        # Bare CLUSTER only -- "CLUSTER without a table_name reclusters all the
        # previously-clustered tables in the current database", and it is that
        # form the reference restricts: "This form of CLUSTER cannot be executed
        # inside a transaction block." CLUSTER <table> USING <index> is
        # transactional and must not be swept up, which is why this is anchored
        # to end-of-statement rather than to the verb.
        (
            r"^CLUSTER\s*(\([^()]*\)\s*)?(VERBOSE\s*)?;?$",
            "PostgreSQL CLUSTER without a table name cannot run inside a " "transaction block",
        ),
        # Each of these states the restriction on its own reference page, in
        # the same words: "<COMMAND> cannot be executed inside a transaction
        # block." ALTER SYSTEM words it differently -- "since this command acts
        # directly on the file system and cannot be rolled back, it is not
        # allowed inside a transaction block or function" -- and is the same
        # restriction.
        (
            r"^(CREATE|DROP)\s+DATABASE\b",
            "PostgreSQL CREATE/DROP DATABASE cannot run inside a transaction block",
        ),
        (
            r"^(CREATE|DROP)\s+TABLESPACE\b",
            "PostgreSQL CREATE/DROP TABLESPACE cannot run inside a transaction block",
        ),
        (
            r"^ALTER\s+SYSTEM\b",
            "PostgreSQL ALTER SYSTEM acts on the file system and cannot run "
            "inside a transaction block",
        ),
        (
            r"^DROP\s+INDEX\s+CONCURRENTLY\b",
            "PostgreSQL DROP INDEX CONCURRENTLY cannot run inside a transaction block",
        ),
    )

    def enrich_view_from_row(self, view: Any, row: Dict[str, Any], view_status: Any = None) -> None:
        """PostgreSQL 15+ views can declare ``security_definer`` /
        ``security_invoker``; the vendor query projects both as
        boolean-coerced columns."""
        from dblift.core.utils.row_access import get_row_value

        if get_row_value(row, "security_barrier"):
            view.set_dialect_option("postgresql", "security_barrier", True)
        security_definer = get_row_value(row, "security_definer")
        security_invoker = get_row_value(row, "security_invoker")
        if security_definer is not None:
            view.security_definer = bool(security_definer)
        if security_invoker is not None:
            view.security_invoker = bool(security_invoker)

    def enrich_materialized_view_from_row(self, mview: Any, row: Dict[str, Any]) -> None:
        """PostgreSQL materialized views can be ``UNLOGGED``; the catalog
        projects ``relpersistence`` as ``is_unlogged`` (``"YES"`` / ``"NO"``)."""
        from dblift.core.utils.row_access import get_row_value

        is_unlogged = get_row_value(row, "is_unlogged")
        if is_unlogged == "YES":
            mview.unlogged = True

    def normalize_index_predicate(self, predicate: Optional[str]) -> Optional[str]:
        """Strip redundant ``::TEXT`` and ``CAST(<col> AS TEXT)`` decorations
        the catalog re-introduces, so partial-index WHERE clauses round-trip
        against the source DDL."""
        from dblift.core.utils.metadata_helpers import (
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
        WHERE ...``) with real named UNIQUE constraints, collapsing the
        WHERE predicate on round-trip.

        Falls back to the generic vendor path if the catalog query fails (rare; preserves
        the existing error semantics)."""
        from dblift.core.utils.metadata_helpers import (
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

        from dblift.core.utils.row_access import get_row_value

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
        from dblift.core.utils.row_access import get_row_value

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
        from dblift.core.utils.row_access import get_row_value, parse_json_array

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
        from dblift.core.sql_model.table import Table
        from dblift.core.utils.row_access import get_row_value

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
        from dblift.core.utils.row_access import get_row_value

        return bool(get_row_value(row, "is_temporary") == "YES")

    def identity_owned_sequence_names(self, extractor: Any, schema: str) -> "set[str]":
        """Return sequences owned by ``GENERATED … AS IDENTITY`` columns.

        PostgreSQL creates an implicit sequence for each identity column
        and records an internal dependency (``pg_depend.deptype = 'i'``).
        Replaying ``CREATE SEQUENCE`` for those names fails with
        ``relation "…_seq" already exists`` because the identity clause
        already created them. SERIAL ``OWNED BY`` sequences use
        ``deptype = 'a'`` and free-standing sequences have no such row,
        so they are left for export.
        """
        from dblift.core.utils.row_access import get_row_value

        query_executor = getattr(getattr(extractor, "provider", None), "query_executor", None)
        if not query_executor:
            return set()
        connection = getattr(extractor, "connection", None)

        sql = """
            SELECT seq.relname AS identity_sequence_name
            FROM pg_catalog.pg_class seq
            JOIN pg_catalog.pg_namespace nsp ON nsp.oid = seq.relnamespace
            JOIN pg_catalog.pg_depend dep
              ON dep.objid = seq.oid
             AND dep.classid = 'pg_class'::regclass
             AND dep.deptype = 'i'
            JOIN pg_catalog.pg_attribute attr
              ON attr.attrelid = dep.refobjid
             AND attr.attnum = dep.refobjsubid
             AND attr.attidentity <> ''
            WHERE seq.relkind = 'S'
              AND nsp.nspname = ?
        """
        try:
            rows = query_executor.execute_query(connection, sql, [schema])
        except Exception as exc:
            extractor.log.debug(
                f"Could not load PostgreSQL identity-owned sequences for {schema}: {exc}"
            )
            return set()

        names: set[str] = set()
        for row in rows:
            name = get_row_value(row, "identity_sequence_name")
            if name:
                names.add(str(name))
        return names

    def is_sqlglot_opaque_valid_ddl(self, sql_content: str) -> bool:
        """PG ``DROP TRIGGER name ON table`` — sqlglot rejects this valid DDL
        only when the table is schema-qualified (``ON schema.table``).
        Quoting alone — either identifier, or both — does not make sqlglot
        raise; it parses those forms without error."""
        return _DROP_TRIGGER_ON_RE.search(sql_content) is not None

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

    _PG_SERIAL_BASE_TYPES = {
        "serial": "INTEGER",
        "serial4": "INTEGER",
        "bigserial": "BIGINT",
        "serial8": "BIGINT",
        "smallserial": "SMALLINT",
        "serial2": "SMALLINT",
    }

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

    # Version-gated features (see core.sql_model.feature_gates). Inherited by
    # the PG-compatible family; divergent engines with their own quirks class
    # (Redshift, CockroachDB) redeclare ``feature_gates`` to opt out.
    feature_gates = {
        "set_not_null_reuses_validated_check": FeatureGate(
            min_version="12.0+",
            description=(
                "SET NOT NULL reuses a validated CHECK (col IS NOT NULL) "
                "to skip the full-table re-scan"
            ),
        ),
    }


__all__ = ["PostgresqlQuirks"]
