"""Oracle :class:`DialectQuirks` — Epic 26."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Type

from db.base_quirks import BaseQuirks
from db.error import ErrorCategory
from db.feature_gate import FeatureGate

if TYPE_CHECKING:
    from core.introspection.version_detector import DatabaseVersion
    from core.sql_generator.alter.base_alter_generator import BaseAlterGenerator
    from core.sql_generator.base_generator import BaseSqlGenerator


# Each entry: (compiled regex, ErrorCategory). Sourced by
# ``DatabaseErrorClassifier`` via ``error_patterns()`` (ADR-26 A2).
_ERROR_PATTERNS: List[Tuple[re.Pattern[str], ErrorCategory]] = [
    # Network / connection
    (re.compile(r"ORA-17800", re.IGNORECASE), ErrorCategory.NETWORK),
    (re.compile(r"ORA-17002", re.IGNORECASE), ErrorCategory.NETWORK),
    (re.compile(r"ORA-12541", re.IGNORECASE), ErrorCategory.NETWORK),
    (re.compile(r"ORA-12514", re.IGNORECASE), ErrorCategory.NETWORK),
    (re.compile(r"ORA-12170", re.IGNORECASE), ErrorCategory.TIMEOUT),
    (re.compile(r"ORA-12571", re.IGNORECASE), ErrorCategory.NETWORK),
    (re.compile(r"ORA-03113", re.IGNORECASE), ErrorCategory.NETWORK),
    (re.compile(r"ORA-03114", re.IGNORECASE), ErrorCategory.NETWORK),
    # Locking
    (re.compile(r"ORA-00060", re.IGNORECASE), ErrorCategory.LOCKING),
    (re.compile(r"ORA-00054", re.IGNORECASE), ErrorCategory.LOCKING),
    # Authentication / Authorization
    (re.compile(r"ORA-01017", re.IGNORECASE), ErrorCategory.AUTHENTICATION),
    (re.compile(r"ORA-01031", re.IGNORECASE), ErrorCategory.AUTHORIZATION),
    (re.compile(r"ORA-01045", re.IGNORECASE), ErrorCategory.AUTHENTICATION),
    # Schema
    (re.compile(r"ORA-00942", re.IGNORECASE), ErrorCategory.SCHEMA),
    (re.compile(r"ORA-00904", re.IGNORECASE), ErrorCategory.SCHEMA),
    # Constraint
    (re.compile(r"ORA-00001", re.IGNORECASE), ErrorCategory.CONSTRAINT),
    (re.compile(r"ORA-02291", re.IGNORECASE), ErrorCategory.CONSTRAINT),
    (re.compile(r"ORA-02292", re.IGNORECASE), ErrorCategory.CONSTRAINT),
    # SQL Syntax
    (re.compile(r"ORA-00900", re.IGNORECASE), ErrorCategory.SQL_SYNTAX),
    (re.compile(r"ORA-00933", re.IGNORECASE), ErrorCategory.SQL_SYNTAX),
    # Resource
    (re.compile(r"ORA-04031", re.IGNORECASE), ErrorCategory.RESOURCE),
    (re.compile(r"ORA-01653", re.IGNORECASE), ErrorCategory.RESOURCE),
]


class OracleQuirks(BaseQuirks):
    """Oracle-specific :class:`DialectQuirks` for the Oracle PL/SQL dialect.

    Covers Oracle's deviations from ANSI SQL: uppercase-folded unquoted
    identifiers stored upper-cased in the data dictionary, ``FROM DUAL``
    on probe SELECTs, no ``LIMIT`` (``ROWNUM`` / ``FETCH FIRST n``), native
    ``IF [NOT] EXISTS`` DDL (23ai+, backported to 19.28+ — no version gate,
    older targets simply error at execution time),
    PL/SQL trigger / function bodies wrapped in ``BEGIN ... END;``,
    ``CREATE OR REPLACE`` for procedures / functions / synonyms,
    ``CASCADE CONSTRAINTS`` on DROP TABLE, tablespace and storage
    clauses, deferrable constraints, ``OBJECT`` types, ``SYS*PLUS``
    pre-processing, and DDL-needs-explicit-commit semantics with
    ``commit_with_autocommit_raises`` (ORA-17273).
    """

    # Capability matrix (was ``_CAPABILITIES["oracle"]``).
    supports_transactions = True
    supports_transactional_ddl = False  # DDL auto-commits
    schema_required = True
    uppercase_identifiers = True
    clean_strategy = "native"
    sqlglot_dialect = "oracle"
    # import-flyway reads the verbatim-cased Flyway source table directly,
    # because get_applied_migrations would uppercase the name and miss it.
    flyway_source_table_case_sensitive = True
    # Data-set ledger DDL: Oracle has no TEXT type (use CLOB) and defaults the
    # install timestamp from SYSTIMESTAMP.
    data_history_text_type = "CLOB"
    data_change_set_blob_type = "CLOB"
    data_timestamp_column_ddl = "TIMESTAMP DEFAULT SYSTIMESTAMP"

    def is_data_history_table_already_exists_error(self, error_message: str) -> bool:
        """The data-history ledger DDL doesn't use IF NOT EXISTS (shared across
        dialects); Oracle raises ORA-00955 when the table already exists."""
        return "ORA-00955" in (error_message or "")

    def is_data_change_set_table_already_exists_error(self, error_message: str) -> bool:
        """Same ORA-00955 detection as the data history table."""
        return self.is_data_history_table_already_exists_error(error_message)

    sqlglot_unsupported_sql_patterns = (
        "PARTITION BY REFERENCE",
        "PARTITION BY RANGE",
        "INTERVAL (",
    )
    connection_probe_sql = "SELECT 1 FROM DUAL"
    select_supports_limit = False
    boolean_false_literal = "0"
    unquoted_identifier_case = "uppercase"
    # quote_qualified upper-cases idents to match Oracle's catalogue folding.
    # DB2 shares the folding quirks but must NOT inherit this (story 26-5).
    quote_qualified_folds_to_uppercase = True
    connection_identifier_attrs = ("url", "service_name", "sid", "database")
    missing_connection_identifier_hint = (
        "Oracle connection requires url, service_name, sid, or host/database fields"
    )

    def derive_schema_name(self, database_config: Any) -> Optional[str]:
        """Use the Oracle user/current schema convention when schema is omitted."""
        username = getattr(database_config, "username", None)
        if username:
            return str(username).upper()
        return None

    # Procedure / function DDL (story 26-5).
    proc_supports_create_or_replace = True
    proc_function_returns_keyword = "RETURN"  # Oracle: ``RETURN`` (no S)
    proc_body_wrap_style = "plain"
    proc_drop_supports_if_exists = True
    # Index DDL (story 26-5).
    index_drop_standalone_supports_if_exists = True  # native since 23ai / 19.28
    index_supports_bitmap = True
    index_supports_local_partitioned = True
    index_supports_tablespace = True
    # Trigger DDL (story 26-5).
    trigger_terminator = "\n/"
    # Engine-internal materialized-view support objects to skip during
    # table introspection. Non-empty also signals TableExtractor to
    # preload MV names so it can filter them from the table list.
    materialized_view_support_table_prefixes: Tuple[str, ...] = (
        "MLOG$",
        "RUPD$",
        "MVIEW$_",
        "MVW$_",
        "I_SNAP$",
        "SNAP$",
        "AQ$",
        "DR$",
    )

    def wrap_trigger_body(self, body: str) -> str:
        """Oracle: wrap body in a valid PL/SQL block.

        Prepends ``BEGIN\\n`` if the body doesn't already start with
        ``DECLARE`` / ``BEGIN``; appends ``END;`` if missing, or fixes a
        trailing ``END`` without semicolon.
        """
        text = body.strip()
        if not text:
            return ""
        upper = text.upper()
        if not upper.startswith(("DECLARE", "BEGIN")):
            text = f"BEGIN\n{text}"
        trimmed = text.rstrip()
        if not re.search(r"\bEND\b\s*;?\s*$", trimmed, re.IGNORECASE):
            text = f"{text}\nEND;"
        elif not trimmed.endswith(";"):
            text = f"{trimmed};"
        return text

    # Sequence DDL (story 26-5).
    seq_default_nocache_when_unset = True
    seq_cache_one_means_nocache = True
    seq_drop_supports_if_exists = True
    # Synonym DDL (story 26-5).
    synonym_supports_create_or_replace = True
    # View DDL (story 26-5).
    view_drop_supports_if_exists = True
    # UDT DDL (story 26-5). Oracle ``CREATE TYPE foo AS OBJECT`` uses
    # semicolons in the body; SQL Server uses different syntax.
    udt_object_body_uses_semicolons = True
    udt_composite_object_modifier = " OBJECT"
    # Table DDL (story 26-5).
    table_drop_style = "if_exists_cascade_constraints"
    table_create_supports_if_not_exists = True
    table_temporary_style = "global_temporary"
    table_not_null_implicit_on_inline_pk = True
    table_fk_suppress_on_update = True
    table_supports_deferrable_constraints = True
    table_supports_constraint_state = True
    table_tablespace_style = "quoted"
    table_supports_storage_params = True
    supports_sqlplus_preprocessing = True
    # Wave A hooks (story 26-6).
    view_supports_force_noforce = True
    proc_uses_definition_field = True
    index_comment_template = "COMMENT ON INDEX {schema_prefix}{idx_name} IS '{escaped_comment}';"
    default_index_type = "NORMAL"
    # Wave B hooks.
    native_driver_display = "python-oracledb"
    # Oracle TIMESTAMP / TIME accept only fractional-seconds precision.
    time_type_supports_only_fractional_precision = True
    # Wave C hooks (story 26-9): migration engine transaction semantics.
    requires_explicit_commit_after_ddl = True
    supports_session_autocommit = False
    retry_drop_create_on_error = True
    # PR-C1: Oracle native driver raised ORA-17273 on commit() when autoCommit is True.
    commit_with_autocommit_raises = True
    # Oracle DDL (CREATE USER) needs autoCommit=False to persist reliably.
    ddl_requires_autocommit_off = True
    # PR-C2: Oracle CREATE USER cannot be silently retried — make schema
    # creation errors fatal for the round-trip test.
    strict_schema_creation_errors = True
    # Oracle stores unquoted identifiers upper-cased in USER_TABLES /
    # ALL_TABLES, so round-trip-tester DROP statements need to upper-case
    # the table name when it wasn't already quoted in the source.
    unquoted_identifiers_uppercase_in_dictionary = True

    def render_round_trip_drop_table_sql(self, target: str) -> str:
        """Native ``DROP TABLE IF EXISTS ... CASCADE CONSTRAINTS`` (23ai+/19.28+)
        so the drop survives FK references without erroring if absent."""
        return f"DROP TABLE IF EXISTS {target} CASCADE CONSTRAINTS"

    def replace_round_trip_schema_in_sql(
        self, sql: str, source_schema: str, target_schema: str
    ) -> str:
        """Oracle: wrap the target name in double quotes when rewriting
        bare unquoted ``<source>`` occurrences. Oracle stores unquoted
        identifiers upper-cased in the data dictionary; double-quoting
        the target preserves the test schema's case so cleanup matches."""
        # Quoted form: "source" → "target" (matches REFERENCES / FROM /
        # JOIN forms too, ``"`` is a non-word char so the regex stays
        # the same).
        quoted_pattern = re.escape(f'"{source_schema}"')
        sql = re.sub(quoted_pattern, f'"{target_schema}"', sql, flags=re.IGNORECASE)

        # Unquoted form → double-quoted target.
        unquoted_pattern = re.escape(source_schema)
        sql = re.sub(
            rf"\b{unquoted_pattern}\.",
            f'"{target_schema}".',
            sql,
            flags=re.IGNORECASE,
        )
        sql = re.sub(
            rf"\b{unquoted_pattern}\b",
            f'"{target_schema}"',
            sql,
            flags=re.IGNORECASE,
        )
        return sql

    def build_retry_drop_strategies(
        self,
        query_executor: Any,
        connection: Any,
        schema_clean: str,
        table_clean: str,
    ) -> "list[str]":
        """Look up the real owner/table_name in ALL_TABLES and try it first."""
        import logging

        log = logging.getLogger("core.validation.round_trip_tester")

        strategies: "list[str]" = [
            f'"{schema_clean}"."{table_clean}"',
            f"{schema_clean}.{table_clean}",
        ]
        try:
            schema_exact = schema_clean.replace('"', "")
            table_exact = table_clean.replace('"', "")
            find_table_sql = f"""
            SELECT owner, table_name
            FROM all_tables
            WHERE (owner = '{schema_exact}' OR owner = '{schema_exact.upper()}')
              AND (table_name = '{table_exact}' OR table_name = '{table_exact.upper()}')
              AND table_name NOT LIKE 'BIN$%'
            """
            table_info = query_executor.execute_query(connection, find_table_sql, [])
            if table_info and len(table_info) > 0:
                actual_owner = table_info[0].get("OWNER") or table_info[0].get("owner")
                actual_table = table_info[0].get("TABLE_NAME") or table_info[0].get("table_name")
                strategies.insert(0, f'"{actual_owner}"."{actual_table}"')
                log.debug(f"Oracle: Found table in data dictionary: {actual_owner}.{actual_table}")
        except Exception as find_err:
            log.debug(f"Oracle: Could not query data dictionary: {find_err}")
        return strategies

    def __init__(self, dialect_name: str = "oracle") -> None:
        """Initialize Oracle quirks with the dialect name."""
        super().__init__(dialect_name=dialect_name)

    def error_patterns(self) -> "List[Tuple[re.Pattern[str], ErrorCategory]]":
        """Oracle ORA-code error-classification patterns (ADR-26 A2)."""
        return _ERROR_PATTERNS

    def build_snapshot_table_ddl(
        self,
        qualified_table: str,
        snapshot_id_size: int,
        checksum_size: int,
    ) -> str:
        """Oracle snapshot table DDL is not owned by the Oracle plugin."""
        raise NotImplementedError("Oracle snapshot table DDL is not plugin-owned")

    def build_provider_compat_snapshot_ddl(
        self, qualified_table: str, snapshot_id_size: int, checksum_size: int
    ) -> "Optional[str]":
        """Legacy Oracle provider-compat snapshot DDL (VARCHAR2/CLOB, uppercase)."""
        return (
            f"CREATE TABLE {qualified_table} ("
            f"SNAPSHOT_ID VARCHAR2({snapshot_id_size}) PRIMARY KEY, "
            f"CAPTURED_AT VARCHAR2({snapshot_id_size}) NOT NULL, "
            f"CHECKSUM VARCHAR2({checksum_size}) NOT NULL, "
            "MODEL_DATA CLOB NOT NULL)"
        )

    # ------------------------------------------------------------------
    # Migration-script preprocessing hooks (Tier 1 plugin-isolation).
    # Lazy imports keep ``db.plugins.oracle.parser`` out of the import
    # graph until a script actually needs SQL*Plus handling.
    # ------------------------------------------------------------------

    def extract_script_context(self, sql: str) -> Optional[object]:
        """Extract Oracle SQL*Plus directives (``SET SERVEROUTPUT``, ``DEFINE``, …)."""
        from db.plugins.oracle.parser.sqlplus_context import extract_sqlplus_context

        return extract_sqlplus_context(sql)

    def terminate_script_directives(self, sql: str) -> str:
        """Append ``;`` to SQL*Plus directive lines so the tokenizer splits them."""
        from db.plugins.oracle.parser.sqlplus_context import terminate_sqlplus_directives

        return terminate_sqlplus_directives(sql)

    def apply_script_substitution(self, sql: str, ctx: Optional[object]) -> str:
        """Apply SQL*Plus ``&var`` / ``&&var`` substitution using *ctx*."""
        if ctx is None:
            return sql
        from db.plugins.oracle.parser.sqlplus_context import (
            SqlplusContext,
            apply_define_substitution,
        )

        if not isinstance(ctx, SqlplusContext):
            return sql
        return apply_define_substitution(sql, ctx)

    def is_script_directive(self, stmt: str) -> bool:
        """Return ``True`` for SQL*Plus client-side directives."""
        from db.plugins.oracle.parser._sqlplus import is_sqlplus_command

        return is_sqlplus_command(stmt)

    def parse_error_policy_directive(self, stmt: str) -> Optional[str]:
        """Return the Oracle ``WHENEVER SQLERROR`` policy encoded in *stmt*, or ``None``."""
        from db.plugins.oracle.parser._sqlplus import parse_whenever_sqlerror

        return parse_whenever_sqlerror(stmt)

    def enable_session_output(self, connection: Any) -> None:
        """Enable Oracle ``DBMS_OUTPUT`` capture on the active native connection."""
        from db.plugins.oracle.oracle.dbms_output import enable_dbms_output

        enable_dbms_output(connection)

    def read_session_output(self, connection: Any, log: Any) -> None:
        """Drain Oracle ``DBMS_OUTPUT`` and route each line to *log*."""
        from db.plugins.oracle.oracle.dbms_output import read_dbms_output

        read_dbms_output(connection, log)

    def ddl_generator_class(self) -> Optional[Type["BaseSqlGenerator"]]:
        """DDL generator relocated to the paid package; registered by register_pro_generators()."""
        return None

    def alter_generator_class(self) -> Optional[Type["BaseAlterGenerator"]]:
        """ALTER generator relocated to the paid package; registered by register_pro_generators()."""
        return None

    def vendor_queries_class(self) -> "Optional[Type[Any]]":
        """Oracle rich metadata queries are registered by PRO."""
        return None

    def introspector_class(self) -> "Optional[Type[Any]]":
        """Oracle rich introspection is registered by PRO."""
        return None

    def parser_class(self, parser_type: str) -> Optional[type]:
        """Oracle parser dispatch: hybrid → :class:`HybridParser`, sqlglot →
        :class:`SqlGlotParser` (``oracle`` dialect), regex → :class:`OracleParser`."""
        if parser_type == "hybrid":
            from core.sql_parser.hybrid_parser import HybridParser

            return HybridParser
        if parser_type == "sqlglot":
            from core.sql_parser.sqlglot_parser import SqlGlotParser

            return SqlGlotParser
        if parser_type == "regex":
            from db.plugins.oracle.parser.oracle_parser import OracleParser

            return OracleParser
        return None

    # Story 26-3: Oracle DROP variants — native IF EXISTS (23ai+/19.28+, no
    # version gate) for every object type, CASCADE CONSTRAINTS for tables.
    # TRIGGER/INDEX handled explicitly so they don't fall through the
    # generic quirks-driven fallback (which would emit a shape keyed on
    # ``drop_supports_if_exists`` — routing through ``render_drop_for_object``
    # keeps Oracle's drop grammar owned in one place. PR #241 Bugbot.)
    def render_drop_for_object(
        self,
        obj_type: str,
        obj_name: str,
        schema_prefix: str,
        table_name: Optional[str],
    ) -> Optional[str]:
        """Oracle DROP variants — native ``IF EXISTS``; ``CASCADE CONSTRAINTS`` on tables.

        Handles ``VIEW``/``MATERIALIZED_VIEW``/``TABLE``/``INDEX``/``SEQUENCE``/
        ``PROCEDURE``/``FUNCTION``/``TRIGGER`` so the entire Oracle DROP grammar
        is owned here.
        """
        if obj_type == "VIEW":
            return f"DROP VIEW IF EXISTS {schema_prefix}{obj_name}"
        if obj_type == "MATERIALIZED_VIEW":
            return f"DROP MATERIALIZED VIEW IF EXISTS {schema_prefix}{obj_name}"
        if obj_type == "TABLE":
            return f"DROP TABLE IF EXISTS {schema_prefix}{obj_name} CASCADE CONSTRAINTS"
        if obj_type == "INDEX":
            return f"DROP INDEX IF EXISTS {schema_prefix}{obj_name}"
        if obj_type == "SEQUENCE":
            return f"DROP SEQUENCE IF EXISTS {schema_prefix}{obj_name}"
        if obj_type in ("PROCEDURE", "FUNCTION"):
            return f"DROP {obj_type} IF EXISTS {schema_prefix}{obj_name}"
        if obj_type == "TRIGGER":
            return f"DROP TRIGGER IF EXISTS {schema_prefix}{obj_name}"
        return None

    # round_trip extra object types.
    def round_trip_extra_object_types(self) -> "list[str]":
        """Oracle round-trip covers user-defined OBJECT types, synonyms, and packages."""
        return ["user_defined_types", "synonyms", "packages"]

    # Column ALTER hooks — Oracle uses MODIFY instead of ALTER COLUMN.
    def render_column_nullable_change(
        self, col_diff: object, formatted_table: str, formatted_column: str, dialect: str
    ) -> "Optional[object]":
        """``ALTER TABLE … MODIFY <col> NOT NULL|NULL`` — Oracle's nullable-toggle form.

        Setting NOT NULL emits a pre-check counting NULL rows so a violating
        migration fails cleanly before the ALTER runs.
        """
        from core.sql_generator.sql_statement import SqlStatement

        nullable_diff = getattr(col_diff, "nullable_diff", None)
        if nullable_diff is None:
            return None
        expected_nullable, _ = nullable_diff
        if not expected_nullable:
            return SqlStatement(
                sql=f"ALTER TABLE {formatted_table} MODIFY {formatted_column} NOT NULL;",
                statement_type="ALTER",
                object_type="COLUMN",
                object_name=f"{formatted_table}.{formatted_column}",
                dialect=dialect,
                pre_check=f"SELECT COUNT(*) FROM {formatted_table} WHERE {formatted_column} IS NULL;",
                error_if_check_fails=True,
                error_message="Cannot set NOT NULL: column contains NULL values",
            )
        return SqlStatement(
            sql=f"ALTER TABLE {formatted_table} MODIFY {formatted_column} NULL;",
            statement_type="ALTER",
            object_type="COLUMN",
            object_name=f"{formatted_table}.{formatted_column}",
            dialect=dialect,
        )

    def render_column_default_change(
        self, col_diff: object, formatted_table: str, formatted_column: str, dialect: str
    ) -> "Optional[object]":
        """``ALTER TABLE … MODIFY <col> DEFAULT <expr|NULL>`` — Oracle's DEFAULT change form."""
        from core.sql_generator.sql_statement import SqlStatement

        default_diff = getattr(col_diff, "default_diff", None)
        if default_diff is None:
            return None
        expected_default, _ = default_diff
        if expected_default:
            sql = f"ALTER TABLE {formatted_table} MODIFY {formatted_column} DEFAULT {expected_default};"
        else:
            sql = f"ALTER TABLE {formatted_table} MODIFY {formatted_column} DEFAULT NULL;"
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
        """``ALTER TABLE … MODIFY <col> <type>`` — Oracle column-type change form."""
        from core.sql_generator.sql_statement import SqlStatement

        data_type_diff = getattr(col_diff, "data_type_diff", None)
        if data_type_diff is None:
            return None
        expected_type, _ = data_type_diff
        return SqlStatement(
            sql=f"ALTER TABLE {formatted_table} MODIFY {formatted_column} {expected_type};",
            statement_type="ALTER",
            object_type="COLUMN",
            object_name=f"{formatted_table}.{formatted_column}",
            dialect=dialect,
        )

    def unwrap_default_value(self, default_str: str, column: object) -> str:
        """Strip empty-parens function-call wrapping from Oracle TIMESTAMP defaults.

        Oracle rejects ``CURRENT_TIMESTAMP()`` / ``SYSTIMESTAMP()`` — bare
        keyword form is required. Precision variants (``CURRENT_TIMESTAMP(6)``)
        are also collapsed to the bare keyword in DEFAULT clauses where Oracle
        infers precision from the column type.
        """
        text = default_str.strip()
        upper = text.upper()
        if upper in ("CURRENT_TIMESTAMP()", "SYSTIMESTAMP()"):
            return text[:-2]
        if upper.startswith("CURRENT_TIMESTAMP("):
            return "CURRENT_TIMESTAMP"
        if upper.startswith("SYSTIMESTAMP("):
            return "SYSTIMESTAMP"
        return text

    # Story 27-2: Oracle identity — GENERATED AS IDENTITY with optional
    # seed/increment from column metadata.
    def render_identity_clause(self, col: object) -> "Optional[str]":
        """Oracle identity: ``GENERATED AS IDENTITY`` with optional ``START WITH/INCREMENT BY``.

        Emits the seed/increment clause only when at least one of the two is set
        on the column; otherwise returns the bare keyword.
        """
        seed = getattr(col, "identity_seed", None)
        increment = getattr(col, "identity_increment", None)
        if seed is not None or increment is not None:
            seed_str = str(seed) if seed is not None else "1"
            inc_str = str(increment) if increment is not None else "1"
            return f"GENERATED AS IDENTITY (START WITH {seed_str} INCREMENT BY {inc_str})"
        return "GENERATED AS IDENTITY"

    # Story 27-4: Oracle FK reference query uses schema twice.
    def fk_reference_bind_params(self, schema: str, table: str, column: str) -> "list[str]":
        """Oracle's FK lookup query references the schema twice (``r_owner`` and ``owner``)."""
        return [schema, schema, table, column]

    def is_internal_sequence(self, sequence: Any) -> bool:
        """Oracle ``IDENTITY`` columns auto-generate backing sequences named
        ``ISEQ$$_<oid>`` that live in the user schema but aren't user-
        authored — filter them out of introspection results so they
        don't appear in generated output."""
        name = (getattr(sequence, "name", "") or "").upper()
        return name.startswith("ISEQ$$_")

    def should_skip_index(self, name: str) -> bool:
        """Drop Oracle system-generated index names (``SYS_*`` / ``SYS$*``)."""
        if not name:
            return False
        normalized = name.strip().upper()
        return normalized.startswith("SYS_") or normalized.startswith("SYS$")

    def is_generated_not_null_check(self, row: Dict[str, Any], check_expr: str) -> bool:
        """Drop Oracle's implicit ``"<col>" IS NOT NULL`` check constraints.

        Oracle materializes a ``GENERATED NAME`` check constraint for every
        ``NOT NULL`` column; these are noise in introspection output, so the
        extractor skips them when this returns ``True``."""
        generated = str(row.get("generated") or row.get("GENERATED") or "").upper()
        if generated != "GENERATED NAME":
            return False
        return (
            re.match(r'^\s*\(?\s*"?[A-Z0-9_$#]+"?\s+IS\s+NOT\s+NULL\s*\)?\s*$', check_expr, re.I)
            is not None
        )

    def is_index_hidden_column(self, name: str) -> bool:
        """Oracle function-based indexes materialize expression columns under
        ``SYS_NCxxx``-style names. The extractor substitutes the original
        expression text when this returns ``True``."""
        from db.plugins.oracle.introspection.oracle_utils import is_hidden_column

        return bool(is_hidden_column(name))

    def apply_index_vendor_properties(
        self, idx_data: Dict[str, Any], index_kwargs: Dict[str, Any]
    ) -> None:
        """Oracle: surface ``BITMAP`` index type, tablespace placement, and
        partition locality (``LOCAL`` / ``GLOBAL``)."""
        if idx_data.get("type"):
            index_type = idx_data["type"].upper()
            if index_type == "BITMAP":
                index_kwargs["type"] = "BITMAP"
        if idx_data.get("tablespace"):
            index_kwargs["tablespace"] = idx_data["tablespace"]
        if idx_data.get("is_local") is not None:
            index_kwargs["is_local"] = idx_data["is_local"]

    def apply_vendor_table_properties(self, table: Any, row: Dict[str, Any]) -> None:
        """Apply Oracle tablespace + storage params.

        Falls back through several column-name variants because Oracle's
        catalog queries returned different aliases historically (``tablespace``,
        ``tablespace_name``, raw uppercase ``TABLESPACE_NAME``). Marks the
        ``tablespace`` property explicit so downstream comparators don't
        treat the default as a diff.
        """
        from core.utils.row_access import get_row_value

        tablespace = (
            get_row_value(row, "tablespace")
            or get_row_value(row, "tablespace_name")
            or row.get("TABLESPACE_NAME")
        )
        if tablespace:
            table.tablespace = tablespace
            if hasattr(table, "mark_property_explicit"):
                table.mark_property_explicit("tablespace")
        for attr, col in (
            ("pctfree", "pctfree_value"),
            ("pctused", "pctused_value"),
            ("initial", "initial_value"),
            ("next", "next_extent_size"),
        ):
            val = get_row_value(row, col)
            if val is not None:
                try:
                    table.set_dialect_option("oracle", attr, int(val))
                except (ValueError, TypeError):
                    pass

    def existence_check_sql(self, table_name: str) -> str:
        """``ROWNUM = 1`` + ``FROM DUAL`` — Oracle has no ``LIMIT`` and needs a FROM clause."""
        return (
            f"SELECT CASE WHEN EXISTS (SELECT 1 FROM {table_name} WHERE ROWNUM = 1)"
            f" THEN 1 ELSE 0 END as has_data FROM DUAL"
        )

    def fetch_unique_constraints(
        self, extractor: Any, schema: str, table: str
    ) -> "Optional[list[Any]]":
        """Oracle UNIQUE constraints — iterate the vendor indexes query
        and select non-PK unique entries. Names are run through
        :meth:`sanitize_constraint_name` to drop ``SYS_*`` patterns."""
        from core.utils.metadata_helpers import (
            _build_unique_constraints_from_dict,
        )

        if not getattr(extractor, "vendor_queries", None):
            return None
        try:
            unique_indexes = extractor._get_unique_constraints_oracle(schema, table)
        except Exception as e:
            extractor.log.warning(f"Error getting unique constraints for {schema}.{table}: {e}")
            return []
        return _build_unique_constraints_from_dict(extractor, unique_indexes)

    def sanitize_constraint_name(self, name: "Optional[str]") -> "Optional[str]":
        """Oracle drops ``SYS_*`` and ``SYS$*`` system-generated constraint
        names (e.g. ``SYS_C0013220``)."""
        if not name:
            return name
        normalized = name.strip().upper()
        if normalized.startswith("SYS_") or normalized.startswith("SYS$"):
            return None
        return name

    def fetch_routine_parameters_fallback(
        self, extractor: Any, schema: str, name: str, kind: str
    ) -> "list[Any]":
        """Oracle: ``ALL_ARGUMENTS`` fallback for procedure parameters.

        The procedure flow may call this when the JSON-aggregate column
        in the main query was empty. The function flow has its own
        DBMS_METADATA + regex-parse path and doesn't route through here."""
        if kind != "procedure":
            return []
        result: "list[Any]" = extractor._fetch_oracle_procedure_parameters(schema, name)
        return result

    def fetch_routine_full_definition(
        self,
        extractor: Any,
        schema: str,
        name: str,
        kind: str,
        routine: Any,
        status: Any = None,
    ) -> None:
        """Oracle: ``DBMS_METADATA.GET_DDL`` reconstruction is authoritative.
        Always issue the query (even if the row carries a body), replace
        ``routine.definition`` on success, and clear ``routine.body`` —
        the DDL is self-contained."""
        object_type = "PROCEDURE" if kind == "procedure" else "FUNCTION"
        ddl = extractor._fetch_oracle_ddl(object_type, name, schema)
        if ddl:
            routine.definition = ddl
            routine.body = None

    def clean_source_text(self, text: "Optional[str]") -> "Optional[str]":
        """Strip the ``<E>...</E>`` XML aggregator markup and unescape
        entities that ``DBMS_METADATA`` injects when concatenating PL/SQL
        rows from ``ALL_SOURCE``."""
        from db.plugins.oracle.introspection.oracle_utils import clean_source_text

        return clean_source_text(text)

    def normalize_partition_bound(self, value: Any) -> Any:
        """Collapse ``TO_DATE(...,'SYYYY-MM-DD HH24:MI:SS',
        'NLS_CALENDAR=...')`` partition bounds into a plain
        ``YYYY-MM-DD`` literal when the time component is midnight."""
        from db.plugins.oracle.introspection.oracle_utils import normalize_partition_bound

        return normalize_partition_bound(value)

    def extract_partition_scheme_from_row(
        self, extractor: Any, row: Dict[str, Any], table: Any
    ) -> None:
        """Oracle: ``partitioning_type`` (RANGE / LIST / HASH / …)
        and a comma-separated ``partition_columns`` projection."""
        from core.utils.row_access import get_row_value

        part_type = get_row_value(row, "partitioning_type")
        part_cols = get_row_value(row, "partition_columns")
        if part_type:
            table.partition_method = part_type.upper()
        if part_cols:
            table.partition_columns = [c.strip() for c in part_cols.split(",")]

    def postprocess_routine(self, extractor: Any, schema: str, routine: Any) -> None:
        """Oracle: strip embedded ``CREATE OR REPLACE PACKAGE`` specs from
        procedure / function definitions; the spec text is cached for the
        misc-object pass to reuse."""
        if not routine.definition:
            return
        stripped = extractor._strip_embedded_oracle_package_spec(schema, routine.definition)
        routine.definition = stripped

    def enrich_packages_from_catalog(
        self, extractor: Any, schema: str, packages: "list[Any]"
    ) -> None:
        """Oracle: backfill missing ``PACKAGE`` / ``PACKAGE BODY`` source.

        Procedure-extractor scans cache the spec text in
        ``_oracle_package_specs`` (extracted from embedded ``CREATE OR
        REPLACE PACKAGE`` blocks); anything still missing is fetched
        from ``ALL_SOURCE``."""
        for package in packages:
            schema_key = (schema or "").upper()
            cache_key = (schema_key, (package.name or "").upper())
            cached_spec = extractor._oracle_package_specs.get(cache_key)
            if cached_spec:
                package.spec = cached_spec
            elif not package.spec:
                source = extractor._fetch_oracle_source_text(schema, package.name, "PACKAGE")
                if source:
                    package.spec = source
            if not package.body:
                source_body = extractor._fetch_oracle_source_text(
                    schema, package.name, "PACKAGE BODY"
                )
                if source_body:
                    package.body = source_body

    def fk_reference_query(
        self, schema: str, table: str, col: str
    ) -> "Tuple[Optional[str], list[Any]]":
        """Oracle ``ALL_CONS_COLUMNS`` / ``ALL_CONSTRAINTS`` query for FKs targeting ``col``."""
        sql = """
            SELECT
                a.constraint_name,
                a.owner || '.' || a.table_name as table_name
            FROM all_cons_columns a
            JOIN all_constraints c ON a.constraint_name = c.constraint_name
            WHERE c.constraint_type = 'R'
                AND c.r_owner = :1
                AND c.r_constraint_name IN (
                    SELECT constraint_name FROM all_cons_columns
                    WHERE owner = :2 AND table_name = :3 AND column_name = :4
                )
        """
        return (sql, self.fk_reference_bind_params(schema, table, col))

    def index_reference_query(
        self, schema: str, table: str, col: str
    ) -> "Tuple[Optional[str], list[Any]]":
        """Return the Oracle ``ALL_IND_COLUMNS`` query listing indexes covering ``col``."""
        sql = """
            SELECT index_name
            FROM all_ind_columns
            WHERE table_owner = :1
                AND table_name = :2
                AND column_name = :3
        """
        return (sql, [schema, table, col])

    def type_equivalents(self) -> "dict[str, str]":
        """Oracle alias → canonical type map.

        Oracle collapses every numeric type (``INTEGER``/``INT``/``SMALLINT``/``BIGINT``/
        ``FLOAT``/``REAL``/``DOUBLE PRECISION``) to ``NUMBER``, and the legacy ``LONG``/
        ``LONG RAW`` to ``CLOB``/``BLOB``. ``VARCHAR2``/``NVARCHAR2`` → ``VARCHAR``/``NVARCHAR``.
        """
        return {
            "VARCHAR2": "VARCHAR",
            "NVARCHAR2": "NVARCHAR",
            "INTEGER": "NUMBER",
            "INT": "NUMBER",
            "SMALLINT": "NUMBER",
            "BIGINT": "NUMBER",
            "FLOAT": "NUMBER",
            "DOUBLE PRECISION": "NUMBER",
            "REAL": "NUMBER",
            "LONG": "CLOB",
            "LONG RAW": "BLOB",
        }

    version_specific_type_mappings = {("oracle", "12.2+"): {"JSON": "JSON"}}

    # Edition-gated features (see core.sql_model.feature_gates). The pattern
    # matches the v$version banner, which doubles as the captured edition.
    feature_gates = {
        "online_index_build": FeatureGate(
            edition_pattern=r"enterprise",
            description="CREATE INDEX ... ONLINE",
        ),
    }

    _MARKETING_VERSION_RE = re.compile(r"\b(\d{2})(?:c|g|ai)\b", re.IGNORECASE)

    def parse_server_version(self, raw: "Optional[str]") -> "Optional[DatabaseVersion]":
        """Oracle banners without a ``Release x.y.z`` clause (e.g. ``"Oracle
        Database 23ai Free"``) still carry a marketing version — fall back
        to its major number when the generic dotted-run parse finds nothing.
        """
        from core.introspection.version_detector import DatabaseVersion, parse_version

        version = parse_version(raw)
        if version is not None or not raw:
            return version
        match = self._MARKETING_VERSION_RE.search(raw)
        if match is None:
            return None
        return DatabaseVersion(major=int(match.group(1)), full_version=raw)

    def type_preferences(self) -> "dict[str, str]":
        """Oracle prefers ``NUMBER`` (for ``INTEGER``) and ``VARCHAR2`` (not ``VARCHAR``)."""
        return {"INTEGER": "NUMBER", "VARCHAR": "VARCHAR2", "TIMESTAMP": "TIMESTAMP"}

    def render_computed_column(
        self, col: Any, formatted_col_name: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """Oracle: ``GENERATED ALWAYS AS (expr) [VIRTUAL]``."""
        if not getattr(col, "is_computed", False) or not getattr(col, "computed_expression", None):
            return None, None
        virtual = "VIRTUAL" if not getattr(col, "computed_stored", False) else ""
        return f"GENERATED ALWAYS AS ({col.computed_expression}) {virtual}".strip(), None


__all__ = ["OracleQuirks"]
