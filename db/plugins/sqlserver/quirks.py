"""SQL Server :class:`DialectQuirks` — Epic 26."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple, Type

from db.base_quirks import BaseQuirks

_PK_CLUSTERED_RE = re.compile(r"(PRIMARY\s+KEY)\s+(CLUSTERED|NONCLUSTERED)", re.IGNORECASE)
_UNIQUE_CLUSTERED_RE = re.compile(r"(UNIQUE)\s+(CLUSTERED|NONCLUSTERED)", re.IGNORECASE)

if TYPE_CHECKING:
    from core.sql_generator.alter.base_alter_generator import BaseAlterGenerator
    from core.sql_generator.base_generator import BaseSqlGenerator


class SqlserverQuirks(BaseQuirks):
    """SQL Server-specific :class:`DialectQuirks` for the T-SQL dialect.

    Covers SQL Server's deviations from ANSI SQL: square-bracket
    identifier quoting, case-insensitive identifier comparison,
    ``TOP n`` rather than ``LIMIT n``, ``GO`` batch separators,
    ``CLUSTERED`` / ``NONCLUSTERED`` index qualifiers (stripped before
    sqlglot), ``IDENTITY(seed,increment)`` columns, ``OUTPUT`` for
    INOUT procedure parameters, parenthesised default expressions,
    memory-optimised and system-versioned tables.
    """

    # Capability matrix (was ``_CAPABILITIES["sqlserver"]``).
    supports_transactions = True
    supports_transactional_ddl = True
    schema_required = True
    uppercase_identifiers = False
    clean_strategy = "introspector"
    sqlglot_dialect = "tsql"
    pygments_lexer = "tsql"
    connection_identifier_attrs = ("url", "host", "database")
    missing_connection_identifier_hint = (
        "SQL Server connection requires url or host/database fields"
    )
    quote_open = "["
    quote_close = "]"
    boolean_false_literal = "0"
    select_supports_limit = False  # SQL Server uses TOP, not LIMIT
    supports_go_batch_separator = True

    def is_batch_separator(self, stmt: str) -> bool:
        """Return ``True`` for T-SQL ``GO`` batch separators (SSMS / sqlcmd)."""
        from db.plugins.sqlserver.parser.tsql_batch_separator import is_tsql_batch_separator

        return is_tsql_batch_separator(stmt)

    parser_default_schema = "dbo"

    def derive_schema_name(self, database_config: Any) -> Optional[str]:
        """Use SQL Server's conventional default schema when none is supplied."""
        return self.parser_default_schema

    drop_supports_if_exists = True  # SQL Server 2016+ supports DROP ... IF EXISTS
    unquoted_identifier_case = "case_insensitive"
    # Procedure / function DDL (story 26-5).
    proc_body_wrap_style = "begin_end"
    proc_param_inout_keyword = "OUTPUT"
    # Index DDL (story 26-5).
    index_qualifies_with_schema = False
    index_with_options_style = "uppercase"
    index_drop_includes_table = True
    index_drop_table_form_supports_if_exists = True
    # Trigger DDL (story 26-5).
    trigger_supports_for_each_row = False  # SQL Server has no FOR EACH ROW
    # Sequence DDL (story 26-5).
    seq_nocycle_keyword = "NO CYCLE"
    # UDT / Table DDL (story 26-5).
    udt_distinct_uses_from_syntax = True
    table_uses_filegroup_syntax = True
    supports_online_index = True
    metadata_catalog_mode = "catalog+schema"
    # Table DDL (story 26-5).
    table_temporary_style = "hash_prefix"
    table_supports_constraint_nocheck = True
    # Wave A hooks (story 26-6).
    table_supports_memory_optimized = True
    table_supports_system_versioned = True

    def render_system_versioning_alter(
        self,
        formatted_table: str,
        enable: bool,
        history_formatted: Optional[str] = None,
        formatted_period_start: Optional[str] = None,
        formatted_period_end: Optional[str] = None,
    ) -> Optional[str]:
        """Emit T-SQL to toggle ``SYSTEM_VERSIONING`` on a temporal table."""
        if not enable:
            return f"ALTER TABLE {formatted_table} SET (SYSTEM_VERSIONING = OFF);"
        return (
            f"ALTER TABLE {formatted_table} "
            f"ADD PERIOD FOR SYSTEM_TIME ({formatted_period_start}, {formatted_period_end});\n"
            f"ALTER TABLE {formatted_table} "
            f"SET (SYSTEM_VERSIONING = ON (HISTORY_TABLE = {history_formatted}));"
        )

    default_index_type = "NONCLUSTERED"
    # Wave B hooks.
    native_driver_display = "pymssql"
    # SQL Server encodes ``VARCHAR(MAX)`` / ``NVARCHAR(MAX)`` via the
    # column-size sentinels ``-1`` (VARCHAR) and ``2147483647`` (NVARCHAR).
    varchar_max_sentinel_sizes: Tuple[int, ...] = (-1, 2147483647)

    def enhance_columns(
        self, extractor: Any, schema: str, table: str, columns: "list[Any]"
    ) -> None:
        """Backfill default values from ``sys.default_constraints``.

        SQL Server stores many defaults in their own constraint object;
        this hook fetches them via the vendor query and merges them in (skipping columns
        that already carry a default)."""
        if extractor.vendor_queries is None:
            return
        try:
            extractor.log.debug(f"SQL Server: Enhancing default values for {schema}.{table}")
            query, params = extractor.vendor_queries.get_column_defaults_query(schema, table)
            if not query:
                return
            defaults_rs = extractor.provider.query_executor.execute_query(
                extractor.connection, query, params
            )
            extractor.log.debug(f"SQL Server: Default value query returned {len(defaults_rs)} rows")

            defaults_map: Dict[str, str] = {}
            for row in defaults_rs:
                col_name = row.get("column_name", row.get("COLUMN_NAME"))
                default_val = row.get("default_value", row.get("DEFAULT_VALUE"))
                if col_name and default_val:
                    default_val = default_val.strip()
                    if default_val.startswith("(") and default_val.endswith(")"):
                        default_val = default_val[1:-1]
                    defaults_map[col_name.lower()] = default_val

            for column in columns:
                enhanced = defaults_map.get(column.name.lower())
                if enhanced and not column.default_value:
                    column.default_value = enhanced
        except Exception as e:
            extractor.log.debug(f"Could not enhance default values for SQL Server: {e}")
            extractor.track_warning(
                f"Could not enhance default values: {e}",
                object_type="table",
                object_name=table,
                property_name="column_defaults",
                exception=e,
            )

    def __init__(self, dialect_name: str = "sqlserver") -> None:
        """Initialize SQL Server quirks with the dialect name."""
        super().__init__(dialect_name=dialect_name)

    def build_snapshot_table_ddl(
        self,
        qualified_table: str,
        snapshot_id_size: int,
        checksum_size: int,
    ) -> str:
        """Render the SQL Server snapshot table DDL — ``NVARCHAR`` / ``NVARCHAR(MAX)``."""
        return (
            f"CREATE TABLE {qualified_table} ("
            f"snapshot_id NVARCHAR({snapshot_id_size}) PRIMARY KEY, "
            f"captured_at NVARCHAR({snapshot_id_size}) NOT NULL, "
            f"checksum NVARCHAR({checksum_size}) NOT NULL, "
            f"model_data NVARCHAR(MAX) NOT NULL)"
        )

    def ddl_generator_class(self) -> Optional[Type["BaseSqlGenerator"]]:
        """Return the SQL Server-specific :class:`SQLServerSqlGenerator` (lazy import)."""
        from db.plugins.sqlserver.generator.ddl_generator import SQLServerSqlGenerator

        return SQLServerSqlGenerator

    def alter_generator_class(self) -> Optional[Type["BaseAlterGenerator"]]:
        """Return the SQL Server-specific :class:`SQLServerAlterGenerator` (lazy import)."""
        from db.plugins.sqlserver.generator.alter_generator import SQLServerAlterGenerator

        return SQLServerAlterGenerator

    def vendor_queries_class(self) -> "Optional[Type[Any]]":
        """Return the SQL Server :class:`SQLServerMetadataQueries` bundle (lazy import)."""
        from db.plugins.sqlserver.introspection.sqlserver_queries import (
            SQLServerMetadataQueries,
        )

        return SQLServerMetadataQueries

    def introspector_class(self) -> "Optional[Type[Any]]":
        """Return the SQL Server :class:`SQLServerIntrospector` (F.3.d, lazy import)."""
        from db.plugins.sqlserver.introspection.sqlserver_introspector import (
            SQLServerIntrospector,
        )

        return SQLServerIntrospector

    def parser_class(self, parser_type: str) -> Optional[type]:
        """SQL Server parser dispatch: hybrid → :class:`HybridParser`, sqlglot →
        :class:`SqlGlotParser` (``tsql`` dialect), regex → :class:`SqlServerRegexParser`."""
        if parser_type == "hybrid":
            from core.sql_parser.hybrid_parser import HybridParser

            return HybridParser
        if parser_type == "sqlglot":
            from core.sql_parser.sqlglot_parser import SqlGlotParser

            return SqlGlotParser
        if parser_type == "regex":
            from db.plugins.sqlserver.parser.sqlserver_regex_parser import (
                SqlServerRegexParser,
            )

            return SqlServerRegexParser
        return None

    def preprocess_sql_for_sqlglot(self, sql_content: str) -> str:
        """Strip CLUSTERED/NONCLUSTERED from PK/UNIQUE — sqlglot can't parse them."""
        result = _PK_CLUSTERED_RE.sub(r"\1", sql_content)
        return _UNIQUE_CLUSTERED_RE.sub(r"\1", result)

    # Story 26-3: SQL Server DROP INDEX needs an ON-clause.
    def render_drop_for_object(
        self,
        obj_type: str,
        obj_name: str,
        schema_prefix: str,
        table_name: Optional[str],
    ) -> Optional[str]:
        """``DROP INDEX IF EXISTS idx ON tbl`` — SQL Server binds the index name to its table."""
        if obj_type == "INDEX":
            target = table_name or "unknown"
            return f"DROP INDEX IF EXISTS {obj_name} ON {schema_prefix}{target}"
        return None

    # round_trip extra object types.
    def round_trip_extra_object_types(self) -> "list[str]":
        """SQL Server round-trip covers user-defined types and synonyms."""
        return ["user_defined_types", "synonyms"]

    # Column ALTER hooks.
    def render_column_nullable_change(
        self, col_diff: object, formatted_table: str, formatted_column: str, dialect: str
    ) -> "Optional[object]":
        """``ALTER TABLE … ALTER COLUMN <col> NOT NULL|NULL`` — T-SQL nullable toggle.

        Setting NOT NULL emits a pre-check counting NULL rows so the migration
        fails cleanly when existing data would violate the constraint.
        """
        from core.sql_generator.sql_statement import SqlStatement

        nullable_diff = getattr(col_diff, "nullable_diff", None)
        if nullable_diff is None:
            return None
        expected_nullable, _ = nullable_diff
        if not expected_nullable:
            return SqlStatement(
                sql=f"ALTER TABLE {formatted_table} ALTER COLUMN {formatted_column} NOT NULL;",
                statement_type="ALTER",
                object_type="COLUMN",
                object_name=f"{formatted_table}.{formatted_column}",
                dialect=dialect,
                pre_check=f"SELECT COUNT(*) FROM {formatted_table} WHERE {formatted_column} IS NULL;",
                error_if_check_fails=True,
                error_message="Cannot set NOT NULL: column contains NULL values",
            )
        return SqlStatement(
            sql=f"ALTER TABLE {formatted_table} ALTER COLUMN {formatted_column} NULL;",
            statement_type="ALTER",
            object_type="COLUMN",
            object_name=f"{formatted_table}.{formatted_column}",
            dialect=dialect,
        )

    def render_column_type_change(
        self, col_diff: object, formatted_table: str, formatted_column: str, dialect: str
    ) -> "Optional[object]":
        """``ALTER TABLE … ALTER COLUMN <col> <type>`` — T-SQL column-type change."""
        from core.sql_generator.sql_statement import SqlStatement

        data_type_diff = getattr(col_diff, "data_type_diff", None)
        if data_type_diff is None:
            return None
        expected_type, _ = data_type_diff
        return SqlStatement(
            sql=f"ALTER TABLE {formatted_table} ALTER COLUMN {formatted_column} {expected_type};",
            statement_type="ALTER",
            object_type="COLUMN",
            object_name=f"{formatted_table}.{formatted_column}",
            dialect=dialect,
        )

    # Story 27-1: strip IDENTITY suffix from type string; collapse DATETIME(n).
    def normalize_column_data_type(self, col: object, data_type: str) -> str:
        """Strip trailing ``IDENTITY`` on identity cols; collapse ``DATETIME(n)`` → ``DATETIME``."""
        import re

        result = data_type
        if getattr(col, "is_identity", False):
            result = re.sub(r"\s+identity\s*$", "", result, flags=re.IGNORECASE)
        if re.match(r"^datetime\s*\(", result, re.IGNORECASE):
            result = "datetime"
        return result

    # Story 27-2: SQL Server identity — IDENTITY(seed, increment).
    def render_identity_clause(self, col: object) -> "Optional[str]":
        """SQL Server identity columns use ``IDENTITY(seed, increment)`` (defaults: 1, 1)."""
        seed = getattr(col, "identity_seed", 1) or 1
        increment = getattr(col, "identity_increment", 1) or 1
        return f"IDENTITY({seed},{increment})"

    # Story 27-5: SQL Server wraps defaults in parentheses — unwrap when safe.
    def unwrap_default_value(self, default_str: str, column: object) -> str:
        """Strip outer ``(`` … ``)`` from a DEFAULT when the inner expression is a literal.

        SQL Server stores defaults wrapped in parens (e.g. ``(0)``); the wrapper is
        removed when the inner text contains no operators or boolean keywords, so
        compound expressions like ``(a+b)`` stay quoted.
        """
        if default_str.startswith("(") and default_str.endswith(")"):
            inner = default_str[1:-1].strip()
            if not any(op in inner for op in ["+", "-", "*", "/", "=", "<", ">", "AND", "OR"]):
                return inner
        return default_str

    non_transactional_sql_patterns = (
        (
            r"^CREATE\s+FULLTEXT\s+CATALOG\b",
            "SQL Server CREATE FULLTEXT CATALOG cannot run inside a user transaction",
        ),
    )

    def apply_vendor_table_properties(self, table: Any, row: Dict[str, Any]) -> None:
        """Apply SQL Server filegroup / memory-optimised / system-versioned flags."""
        from core.introspection._utils import get_row_value

        filegroup = get_row_value(row, "filegroup_name")
        if filegroup:
            table.filegroup = filegroup
        if get_row_value(row, "is_memory_optimized") == "YES":
            table.memory_optimized = True
        if get_row_value(row, "is_system_versioned") == "YES":
            table.system_versioned = True
            history_table = get_row_value(row, "history_table_name")
            history_schema = get_row_value(row, "history_schema_name")
            period_start = get_row_value(row, "period_start_column")
            period_end = get_row_value(row, "period_end_column")
            if history_table:
                table.history_table = history_table
            if history_schema:
                table.history_schema = history_schema
            if period_start:
                table.period_start_column = period_start
            if period_end:
                table.period_end_column = period_end

    def existence_check_sql(self, table_name: str) -> str:
        """Use ``SELECT TOP 1 1`` — SQL Server has no ``LIMIT`` clause."""
        return (
            f"SELECT CASE WHEN EXISTS (SELECT TOP 1 1 FROM {table_name})"
            f" THEN 1 ELSE 0 END as has_data"
        )

    def apply_routine_volatility_from_row(
        self, extractor: Any, routine: Any, row: Dict[str, Any]
    ) -> None:
        """SQL Server: derive ``volatility`` from ``is_deterministic`` (``1``
        / ``YES`` / ``TRUE`` → IMMUTABLE, else VOLATILE). Only relevant for
        functions (the SQL Server vendor procedure query doesn't project
        ``is_deterministic``)."""
        from core.introspection._utils import get_row_value

        deterministic = get_row_value(row, "is_deterministic")
        if deterministic is not None:
            normalized = str(deterministic).strip().upper()
            routine.volatility = "IMMUTABLE" if normalized in {"1", "YES", "TRUE"} else "VOLATILE"

    def extract_partition_scheme_from_row(
        self, extractor: Any, row: Dict[str, Any], table: Any
    ) -> None:
        """SQL Server: ``partition_function`` + ``partition_type``
        (RANGE_LEFT / RANGE_RIGHT — always ``RANGE`` for the model)
        + comma-separated ``partition_columns``."""
        from core.introspection._utils import get_row_value

        part_func = get_row_value(row, "partition_function")
        part_type = get_row_value(row, "partition_type")
        part_cols = get_row_value(row, "partition_columns")
        if part_func and part_type:
            table.partition_method = "RANGE"
        if part_cols:
            table.partition_columns = [c.strip() for c in part_cols.split(",")]

    def script_header_session_init(self) -> "list[str]":
        """SQL Server: pin ``ANSI_NULLS`` and ``QUOTED_IDENTIFIER`` ON in
        the script header so the emitted DDL parses consistently
        regardless of the connection's defaults."""
        return [
            "SET ANSI_NULLS ON;",
            "SET QUOTED_IDENTIFIER ON;",
            "SET ANSI_PADDING ON;",
            "SET ANSI_WARNINGS ON;",
            "SET CONCAT_NULL_YIELDS_NULL ON;",
            "SET ARITHABORT ON;",
            "SET NUMERIC_ROUNDABORT OFF;",
            "--",
        ]

    def fetch_unique_constraints(
        self, extractor: Any, schema: str, table: str
    ) -> "Optional[list[Any]]":
        """SQL Server UNIQUE constraints come from ``sys.key_constraints``
        (``type='UQ'``) joined with ``sys.index_columns`` —
        generic index catalog rows would conflate them with standalone UNIQUE
        indexes."""
        from core.introspection.extractors.constraint_extractor import (
            _build_unique_constraints_from_dict,
        )

        try:
            unique_indexes = extractor._get_unique_constraints_sqlserver(schema, table)
        except Exception as e:
            extractor.log.warning(f"Error getting unique constraints for {schema}.{table}: {e}")
            return []
        return _build_unique_constraints_from_dict(extractor, unique_indexes)

    def fk_reference_query(
        self, schema: str, table: str, col: str
    ) -> "Tuple[Optional[str], list[Any]]":
        """SQL Server ``sys.foreign_keys`` + ``foreign_key_columns`` query for FKs on ``col``."""
        sql = """
            SELECT
                fk.name as constraint_name,
                OBJECT_SCHEMA_NAME(fk.parent_object_id) + '.'
                    + OBJECT_NAME(fk.parent_object_id) as table_name
            FROM sys.foreign_keys fk
            INNER JOIN sys.foreign_key_columns fkc
                ON fk.object_id = fkc.constraint_object_id
            INNER JOIN sys.columns c
                ON fkc.referenced_column_id = c.column_id
                AND fkc.referenced_object_id = c.object_id
            WHERE OBJECT_SCHEMA_NAME(fk.referenced_object_id) = ?
                AND OBJECT_NAME(fk.referenced_object_id) = ?
                AND c.name = ?
        """
        return (sql, self.fk_reference_bind_params(schema, table, col))

    def index_reference_query(
        self, schema: str, table: str, col: str
    ) -> "Tuple[Optional[str], list[Any]]":
        """SQL Server ``sys.indexes`` + ``sys.index_columns`` query for indexes on ``col``."""
        sql = """
            SELECT i.name as index_name
            FROM sys.indexes i
            INNER JOIN sys.index_columns ic
                ON i.object_id = ic.object_id AND i.index_id = ic.index_id
            INNER JOIN sys.columns c
                ON ic.object_id = c.object_id AND ic.column_id = c.column_id
            WHERE OBJECT_SCHEMA_NAME(i.object_id) = ?
                AND OBJECT_NAME(i.object_id) = ?
                AND c.name = ?
                AND i.is_primary_key = 0
        """
        return (sql, [schema, table, col])

    def type_equivalents(self) -> "dict[str, str]":
        """SQL Server alias → canonical type map.

        Notably ``TEXT``/``NTEXT``/``IMAGE`` (deprecated LOB types) map to
        ``VARCHAR``/``NVARCHAR``/``VARBINARY``; ``SMALLDATETIME`` → ``DATETIME``.
        """
        return {
            "INT": "INTEGER",
            "CHARACTER VARYING": "VARCHAR",
            "CHARACTER": "CHAR",
            "NATIONAL CHARACTER VARYING": "NVARCHAR",
            "NATIONAL CHARACTER": "NCHAR",
            "NATIONAL CHAR VARYING": "NVARCHAR",
            "SMALLDATETIME": "DATETIME",
            "TEXT": "VARCHAR",
            "NTEXT": "NVARCHAR",
            "IMAGE": "VARBINARY",
        }

    version_specific_type_mappings = {("sqlserver", "13.0+"): {"JSON": "JSON"}}

    def type_preferences(self) -> "dict[str, str]":
        """SQL Server prefers ``INT`` (not ``INTEGER``) and ``DATETIME2`` (not ``TIMESTAMP``).

        T-SQL's ``TIMESTAMP`` is a rowversion type, not a datetime; ``DATETIME2``
        is the correct timestamp-with-precision name.
        """
        return {"INTEGER": "INT", "VARCHAR": "VARCHAR", "TIMESTAMP": "DATETIME2"}

    def render_computed_column(
        self, col: Any, formatted_col_name: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """SQL Server: ``col AS (expr) [PERSISTED]`` (replaces the type prefix)."""
        if not getattr(col, "is_computed", False) or not getattr(col, "computed_expression", None):
            return None, None
        persisted = "PERSISTED" if getattr(col, "computed_stored", False) else ""
        new_parts0 = f"{formatted_col_name} AS ({col.computed_expression})"
        return (persisted if persisted else None), new_parts0


__all__ = ["SqlserverQuirks"]
