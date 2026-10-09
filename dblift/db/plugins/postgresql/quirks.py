"""PostgreSQL :class:`DialectQuirks`."""

from __future__ import annotations

import re
from typing import Any, List, Optional, Tuple

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

    def is_sqlglot_opaque_valid_ddl(self, sql_content: str) -> bool:
        """PG ``DROP TRIGGER name ON table`` — sqlglot rejects this valid DDL
        only when the table is schema-qualified (``ON schema.table``).
        Quoting alone — either identifier, or both — does not make sqlglot
        raise; it parses those forms without error."""
        return _DROP_TRIGGER_ON_RE.search(sql_content) is not None

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
