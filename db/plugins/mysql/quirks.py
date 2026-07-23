"""MySQL :class:`DialectQuirks` — Epic 26."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Type

from core.utils.database_url_parser import DatabaseUrlParser
from db.base_quirks import BaseQuirks
from db.error import ErrorCategory
from db.feature_gate import FeatureGate

if TYPE_CHECKING:
    from core.sql_generator.alter.base_alter_generator import BaseAlterGenerator
    from core.sql_generator.base_generator import BaseSqlGenerator


# Each entry: (compiled regex, ErrorCategory). Sourced by
# ``DatabaseErrorClassifier`` via ``error_patterns()`` (ADR-26 A2).
_ERROR_PATTERNS: List[Tuple[re.Pattern[str], ErrorCategory]] = [
    # Network / connection
    (re.compile(r"\b2003\b.*Can't connect", re.IGNORECASE), ErrorCategory.NETWORK),
    (re.compile(r"\b2013\b.*Lost connection", re.IGNORECASE), ErrorCategory.NETWORK),
    (re.compile(r"\b2006\b.*server has gone away", re.IGNORECASE), ErrorCategory.NETWORK),
    (re.compile(r"\b2002\b.*Can't connect", re.IGNORECASE), ErrorCategory.NETWORK),
    # Locking
    (re.compile(r"\b1205\b.*Lock wait timeout", re.IGNORECASE), ErrorCategory.LOCKING),
    (re.compile(r"\b1213\b.*Deadlock", re.IGNORECASE), ErrorCategory.LOCKING),
    # Authentication
    (re.compile(r"\b1045\b.*Access denied", re.IGNORECASE), ErrorCategory.AUTHENTICATION),
    # Schema
    (re.compile(r"\b1146\b.*doesn't exist", re.IGNORECASE), ErrorCategory.SCHEMA),
    (re.compile(r"\b1054\b.*Unknown column", re.IGNORECASE), ErrorCategory.SCHEMA),
    # Constraint
    (re.compile(r"\b1062\b.*Duplicate entry", re.IGNORECASE), ErrorCategory.CONSTRAINT),
    (re.compile(r"\b1452\b.*foreign key constraint", re.IGNORECASE), ErrorCategory.CONSTRAINT),
    # SQL Syntax
    (re.compile(r"\b1064\b.*syntax", re.IGNORECASE), ErrorCategory.SQL_SYNTAX),
]


class MysqlQuirks(BaseQuirks):
    """MySQL-specific :class:`DialectQuirks` for the MySQL dialect.

    Covers MySQL's deviations from ANSI SQL: backtick identifier
    quoting, ``AUTO_INCREMENT`` rather than IDENTITY, no transactional
    DDL (DDL auto-commits, ``setAutoCommit(false)`` is unreliable),
    ``DELIMITER`` wrapping for stored programs (procedures, functions,
    triggers, events), ``DEFINER`` clauses on triggers, ``ALGORITHM``
    on views, ``ON UPDATE CURRENT_TIMESTAMP`` column defaults, and
    catalog-mode metadata queries (no separate schema concept).
    """

    # Capability matrix (was ``_CAPABILITIES["mysql"]``).
    supports_transactions = True
    supports_transactional_ddl = False  # DDL auto-commits
    schema_required = True
    uppercase_identifiers = False
    clean_strategy = "introspector"
    connection_identifier_attrs = ("url", "host", "database")
    missing_connection_identifier_hint = "MySQL connection requires url or host/database fields"
    sqlglot_dialect = "mysql"
    pygments_lexer = "mysql"
    quote_open = "`"
    quote_close = "`"
    drop_supports_if_exists = True
    provider_compat_snapshot_skips_existence_check = True
    tinyint1_is_boolean = True
    metadata_catalog_mode = "catalog"
    # Procedure / function DDL (story 26-5).
    proc_body_wrap_style = "mysql_characteristics"
    # Index DDL (story 26-5).
    index_qualifies_with_schema = False
    index_supports_online_offline = True
    index_supports_mysql_typed_keywords = True
    index_drop_includes_table = True
    index_drop_table_form_supports_if_exists = False
    # Trigger DDL (story 26-5).
    trigger_supports_definer_clause = True
    # Event scheduler timestamp-quoting (story 26-5).
    event_supports_mysql_schedule = True
    # Table DDL (story 26-5).
    table_drop_style = "if_exists"
    table_supports_inline_collate = True
    table_check_strip_utf8mb4 = True
    table_uses_storage_engine_clause = True
    # Wave A hooks (story 26-6).
    view_supports_algorithm = True
    proc_skip_empty_comparison = True
    table_column_default_has_on_update = True
    # Wave B hooks.
    native_driver_display = "pymysql"
    # Wave C hooks (story 26-9): migration engine transaction semantics.
    clean_schema_auto_commits = True
    supports_session_autocommit = False
    # MySQL read-only introspection can leave InnoDB transactions open;
    # roll back afterward to free the connection promptly.
    requires_rollback_after_introspection = True

    def derive_schema_name(self, database_config: Any) -> Optional[str]:
        """Use MySQL's selected database/catalog as DBLift's effective schema."""
        database = getattr(database_config, "database", None)
        if database:
            return str(database)
        return DatabaseUrlParser.parse_database_name(getattr(database_config, "url", None))

    # SQL functions filtered out when extracting partition column names
    # from MySQL ``partition_expression`` strings (e.g. ``YEAR(date_col)``
    # → keep ``date_col``, drop ``YEAR``). Class-level so it's allocated
    # once at import time, not on every ``extract_partition_scheme_from_row``
    # call.
    _SQL_PARTITION_FUNCTIONS: "frozenset[str]" = frozenset(
        {
            "YEAR",
            "MONTH",
            "DAY",
            "TO_CHAR",
            "TO_DATE",
            "EXTRACT",
            "DATE",
            "TIMESTAMP",
            "CAST",
            "CONVERT",
        }
    )

    def __init__(self, dialect_name: str = "mysql") -> None:
        """Initialize MySQL quirks with the dialect name."""
        super().__init__(dialect_name=dialect_name)

    def error_patterns(self) -> "List[Tuple[re.Pattern[str], ErrorCategory]]":
        """MySQL numeric error-code classification patterns (ADR-26 A2).

        Inherited by :class:`MariadbQuirks` — MariaDB is MySQL
        wire-compatible and shares the same numeric error codes.
        """
        return _ERROR_PATTERNS

    def engine_pool_options(self) -> "dict[str, Any]":
        """MySQL/MariaDB: disable pool reset-on-return to avoid connection-state churn."""
        return {"pool_reset_on_return": None}

    def build_snapshot_table_ddl(
        self,
        qualified_table: str,
        snapshot_id_size: int,
        checksum_size: int,
    ) -> str:
        """MySQL does not support DBLift-managed snapshot table DDL."""
        raise NotImplementedError("MySQL does not support DBLift-managed snapshot table DDL")

    def build_provider_compat_snapshot_ddl(
        self, qualified_table: str, snapshot_id_size: int, checksum_size: int
    ) -> "Optional[str]":
        """Legacy MySQL provider-compat snapshot DDL (idempotent, InnoDB)."""
        return (
            f"CREATE TABLE IF NOT EXISTS {qualified_table} ("
            f"snapshot_id VARCHAR({snapshot_id_size}) PRIMARY KEY, "
            "captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
            f"checksum VARCHAR({checksum_size}), "
            "model_data LONGTEXT NOT NULL"
            ") ENGINE=InnoDB"
        )

    def build_data_history_table_ddl(
        self,
        qualified_table: str,
        id_size: int = 100,
        checksum_size: int = 128,
    ) -> str:
        """MySQL-specific DDL for data history table (with ENGINE)."""
        return (
            f"CREATE TABLE {qualified_table} ("
            f"id VARCHAR({id_size}) PRIMARY KEY, "
            f"dataset VARCHAR(100), "
            f"sql_checksum VARCHAR({checksum_size}), "
            f"installed_by VARCHAR(100), "
            f"installed_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
            f"status VARCHAR(20), "
            f"plan_fingerprint VARCHAR(128), "
            f"summary TEXT, "
            f"vcs_ref VARCHAR(200), "
            f"note TEXT"
            ") ENGINE=InnoDB"
        )

    def build_data_change_set_table_ddl(
        self,
        qualified_table: str,
        history_id_size: int = 100,
        checksum_size: int = 128,
    ) -> str:
        """MySQL-specific DDL for data change-set table using LONGTEXT.

        ``(dataset, history_id)`` primary key enforces one change-set row per
        applied correction (the table is shared across datasets).
        """
        return (
            f"CREATE TABLE {qualified_table} ("
            f"dataset VARCHAR(100) NOT NULL, "
            f"history_id VARCHAR({history_id_size}) NOT NULL, "
            f"checksum VARCHAR({checksum_size}), "
            f"model_data LONGTEXT NOT NULL, "
            f"PRIMARY KEY (dataset, history_id)"
            ") ENGINE=InnoDB"
        )

    def build_data_audit_table_ddl(
        self,
        qualified_table: str,
        history_id_size: int = 100,
        checksum_size: int = 128,
    ) -> str:
        """MySQL-specific append-only audit-log DDL (InnoDB)."""
        return (
            f"CREATE TABLE {qualified_table} ("
            f"dataset VARCHAR(100) NOT NULL, "
            f"seq INTEGER NOT NULL, "
            f"history_id VARCHAR({history_id_size}) NOT NULL, "
            f"event VARCHAR(20) NOT NULL, "
            f"sql_checksum VARCHAR({checksum_size}), "
            f"installed_by VARCHAR(100), "
            f"recorded_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
            f"prev_hash VARCHAR(64) NOT NULL, "
            f"row_hash VARCHAR(64) NOT NULL, "
            f"PRIMARY KEY (dataset, seq)"
            ") ENGINE=InnoDB"
        )

    def ddl_generator_class(self) -> Optional[Type["BaseSqlGenerator"]]:
        """DDL generator relocated to the paid package; registered by register_pro_generators()."""
        return None

    def alter_generator_class(self) -> Optional[Type["BaseAlterGenerator"]]:
        """ALTER generator relocated to the paid package; registered by register_pro_generators()."""
        return None

    def vendor_queries_class(self) -> "Optional[Type[Any]]":
        """MySQL-family rich metadata queries are registered by PRO."""
        return None

    def introspector_class(self) -> "Optional[Type[Any]]":
        """MySQL-family rich introspection is registered by PRO."""
        return None

    def parser_class(self, parser_type: str) -> Optional[type]:
        """MySQL parser dispatch: hybrid → :class:`HybridParser`, sqlglot →
        :class:`SqlGlotParser`, regex → :class:`MySqlRegexParser`."""
        if parser_type == "hybrid":
            from core.sql_parser.hybrid_parser import HybridParser

            return HybridParser
        if parser_type == "sqlglot":
            from core.sql_parser.sqlglot_parser import SqlGlotParser

            return SqlGlotParser
        if parser_type == "regex":
            from db.plugins.mysql.parser.mysql_regex_parser import MySqlRegexParser

            return MySqlRegexParser
        return None

    # Story 26-3: MySQL DELIMITER wrapping has two distinct call paths
    # with different object-type sets — preserve both rather than
    # collapsing into one (PR #241 Bugbot).
    #
    #   ``_DELIMITER_OBJECT_TYPES`` (narrow) — PROCEDURE/FUNCTION only.
    #     Used by ``SqlGenerator.generate_ddl`` to wrap CREATE
    #     statements with ``DELIMITER //...//\nDELIMITER ;``.
    #
    #   ``_BLOCK_DELIMITER_OBJECT_TYPES`` (wider) — adds TRIGGER and
    #     EVENT. Used by the ``$$``-flavoured helper
    #     ``_requires_mysql_delimiter`` /
    #     ``_wrap_mysql_delimiter_block`` in sql_generator.py.
    _DELIMITER_OBJECT_TYPES = frozenset({"PROCEDURE", "FUNCTION"})
    _BLOCK_DELIMITER_OBJECT_TYPES = frozenset({"PROCEDURE", "FUNCTION", "TRIGGER", "EVENT"})
    _DEFINITION_PRESERVE_TYPES = frozenset({"VIEW", "PROCEDURE", "FUNCTION", "TRIGGER", "EVENT"})

    def render_drop_for_object(
        self,
        obj_type: str,
        obj_name: str,
        schema_prefix: str,
        table_name: Optional[str],
    ) -> Optional[str]:
        """``DROP TABLE IF EXISTS`` — MySQL has no ``CASCADE`` on ``DROP TABLE``.

        All other object types defer to the generic ``DROP ... IF EXISTS`` fallback.
        """
        # MySQL omits CASCADE on DROP TABLE.
        if obj_type == "TABLE":
            return f"DROP TABLE IF EXISTS {schema_prefix}{obj_name}"
        return None

    def requires_dialect_specific_wrapping(self, object_type_name: str) -> bool:
        """True for ``PROCEDURE``/``FUNCTION`` — wrap with ``DELIMITER //`` markers."""
        return object_type_name in self._DELIMITER_OBJECT_TYPES

    def requires_block_delimiter_wrapping(self, object_type_name: str) -> bool:
        """True for ``PROCEDURE``/``FUNCTION``/``TRIGGER``/``EVENT`` — ``$$`` helper path."""
        return object_type_name in self._BLOCK_DELIMITER_OBJECT_TYPES

    def wrap_dialect_specific_block(self, sql: str) -> str:
        """Wrap *sql* in ``DELIMITER //`` … ``//`` … ``DELIMITER ;`` for stored programs."""
        return f"DELIMITER //\n{sql}\n//\nDELIMITER ;"

    def preserves_object_definition(self, object_type_name: str) -> bool:
        """Return True if the generator must round-trip the verbatim CREATE definition.

        MySQL views, procedures, functions, triggers, and events store
        the user-supplied source text in ``information_schema``; the
        introspector reads it back and the SQL generator should not
        re-render those bodies (whitespace, quoting and the MySQL
        ``DELIMITER`` wrapper would otherwise drift on round-trip).
        Other object types are re-rendered from the structured model.
        """
        return object_type_name in self._DEFINITION_PRESERVE_TYPES

    # round_trip extra object types.
    def round_trip_extra_object_types(self) -> "list[str]":
        """MySQL round-trip covers user-defined types and scheduled events."""
        return ["user_defined_types", "events"]

    # Column ALTER hooks — MySQL uses MODIFY for type changes.
    def render_column_type_change(
        self, col_diff: object, formatted_table: str, formatted_column: str, dialect: str
    ) -> "Optional[object]":
        """``ALTER TABLE … MODIFY <col> <type>`` — MySQL's column-type change form."""
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

    # Story 27-2: MySQL/MariaDB identity — AUTO_INCREMENT.
    def render_identity_clause(self, col: object) -> "Optional[str]":
        """MySQL identity columns use ``AUTO_INCREMENT`` (no seed/increment syntax)."""
        return "AUTO_INCREMENT"

    # Story 27-5: MySQL normalises ENUM/CHAR/TEXT default values to single-
    # quoted strings; backtick and double-quote wrapping is stripped.
    def unwrap_default_value(self, default_str: str, column: object) -> str:
        """Normalise character-column defaults to single-quoted form.

        For ``CHAR``/``TEXT``/``CLOB``/``ENUM`` columns, strip backtick or
        double-quote wrapping and re-quote with single quotes (escaping any
        inner ``'``). Non-character columns pass through unchanged.
        """
        data_type = (getattr(column, "data_type", "") or "").upper()
        is_character_type = any(t in data_type for t in ("CHAR", "TEXT", "CLOB", "ENUM"))
        if is_character_type:
            if default_str.startswith("'") and default_str.endswith("'"):
                return default_str
            if default_str.startswith("`") and default_str.endswith("`"):
                default_str = default_str[1:-1]
            elif default_str.startswith('"') and default_str.endswith('"'):
                default_str = default_str[1:-1]
            escaped = default_str.replace("'", "''")
            return f"'{escaped}'"
        return default_str

    def enrich_view_from_row(self, view: Any, row: Dict[str, Any], view_status: Any = None) -> None:
        """MySQL / MariaDB views carry ``DEFINER`` (``user@host``) and
        ``SQL SECURITY`` (DEFINER | INVOKER) clauses recorded in
        ``information_schema.views``. The ``ALGORITHM`` clause is fetched
        via ``SHOW CREATE VIEW`` elsewhere (gated by its own dialect
        check inside the extractor's ``_get_mysql_view_algorithm`` helper)."""
        from core.utils.row_access import get_row_value

        definer = get_row_value(row, "definer")
        if definer:
            view.definer = definer
            if view_status:
                view_status.add_property_status("definer", True)
        elif view_status:
            view_status.add_property_status("definer", False)

        sql_security = get_row_value(row, "sql_security")
        if sql_security:
            view.sql_security = sql_security
            if view_status:
                view_status.add_property_status("sql_security", True)
        elif view_status:
            view_status.add_property_status("sql_security", False)

    def apply_index_vendor_properties(
        self, idx_data: Dict[str, Any], index_kwargs: Dict[str, Any]
    ) -> None:
        """MySQL: carry ``FULLTEXT`` / ``SPATIAL`` index types through to the
        ``Index`` row so the DDL generator can emit them; everything else
        already lives in the canonical ``type`` slot."""
        if idx_data.get("type"):
            index_type = idx_data["type"].upper()
            if index_type in ("FULLTEXT", "SPATIAL"):
                index_kwargs["type"] = index_type

    def enrich_trigger_from_row(
        self, trigger: Any, row: Dict[str, Any], trigger_status: Any = None
    ) -> None:
        """MySQL / MariaDB triggers carry a ``DEFINER`` clause (``user@host``).

        Records the per-property capture status so the introspection summary
        reports ``definer captured: yes`` or ``no`` for each trigger.
        Inherited unchanged by MariaDB.
        """
        from core.utils.row_access import get_row_value

        definer = get_row_value(row, "definer")
        if definer:
            trigger.definer = definer
            if trigger_status:
                trigger_status.add_property_status("definer", True)
        elif trigger_status:
            trigger_status.add_property_status("definer", False)

    def correct_computed_column_flag(
        self, is_generated: bool, column_def: "Optional[str]", is_identity: bool
    ) -> bool:
        """MySQL / MariaDB catalog rows can flag a column with a non-NULL default
        (e.g. ``DEFAULT CURRENT_TIMESTAMP``) as generated. Real
        ``GENERATED ALWAYS AS (...)`` columns surface a ``GENERATED``
        prefix in the COLUMN_DEF; everything else is a regular default."""
        if not is_generated:
            return False
        if column_def and not column_def.strip().upper().startswith("GENERATED"):
            return False
        return True

    def enhance_columns(
        self, extractor: Any, schema: str, table: str, columns: "list[Any]"
    ) -> None:
        """Replace ``ENUM`` with the full ``enum('a','b',…)`` definition.

        The base column query returns the bare ``ENUM`` type name for MySQL /
        MariaDB enum columns; the member list lives in ``COLUMN_TYPE`` and
        surfaces only via the vendor ``get_columns_query``. MariaDB inherits this
        hook unchanged."""
        if extractor.vendor_queries is None:
            return
        query_fn = getattr(extractor.vendor_queries, "get_columns_query", None)
        if not callable(query_fn):
            return
        try:
            col_query = query_fn(schema, table)
            if not col_query:
                return
            rows = extractor.provider.query_executor.execute_query(extractor.connection, col_query)
            col_type_map: Dict[str, str] = {}
            for row in rows:
                col_name = row.get("column_name") or row.get("COLUMN_NAME")
                col_type = row.get("column_type") or row.get("COLUMN_TYPE")
                if col_name and col_type:
                    col_type_map[col_name.lower()] = col_type

            for column in columns:
                full_type = col_type_map.get(column.name.lower(), "")
                if full_type and full_type.upper().startswith("ENUM"):
                    column.data_type = full_type
        except Exception as e:
            extractor.log.debug(f"Could not enhance MySQL ENUM types for {table}: {e}")

    def fetch_routine_parameters_fallback(
        self, extractor: Any, schema: str, name: str, kind: str
    ) -> "list[Any]":
        """MySQL / MariaDB read parameters from ``information_schema.PARAMETERS``
        when the JSON aggregate in the main routines query comes back empty."""
        result: "list[Any]" = extractor._fetch_mysql_routine_parameters(schema, name)
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
        """MySQL / MariaDB: BUG-01 — ``information_schema.ROUTINES`` exposes
        only the body, not the full CREATE statement. Skip when a
        definition is already attached; otherwise issue ``SHOW CREATE
        PROCEDURE`` / ``SHOW CREATE FUNCTION`` and refresh ``body`` from
        the ``BEGIN`` offset."""
        if routine.definition is not None:
            return
        from core.utils.metadata_helpers import (
            _fetch_mysql_show_create_routine,
        )

        create_stmt = _fetch_mysql_show_create_routine(extractor, schema, name, kind, status)
        if create_stmt:
            routine.definition = create_stmt
            upper_stmt = create_stmt.upper()
            begin_idx = upper_stmt.find("BEGIN")
            if begin_idx != -1:
                routine.body = create_stmt[begin_idx:].strip()

    def apply_routine_volatility_from_row(
        self, extractor: Any, routine: Any, row: Dict[str, Any]
    ) -> None:
        """MySQL / MariaDB: derive ``volatility`` from ``is_deterministic``.

        Empty / missing falls through to ``VOLATILE``; only ``YES`` maps
        to ``IMMUTABLE``. The caller applies the row's own ``volatility``
        column afterwards, so a real projection still overrides this."""
        from core.utils.row_access import get_row_value

        deterministic = (get_row_value(row, "is_deterministic") or "").upper()
        routine.volatility = "IMMUTABLE" if deterministic == "YES" else "VOLATILE"

    def apply_routine_definer_from_row(
        self, extractor: Any, routine: Any, row: Dict[str, Any]
    ) -> None:
        """MySQL / MariaDB: ``definer`` column has final authority (it runs
        after the generic ``execute_as_principal`` / ``EXECUTE AS OWNER``
        path), so it can replace ``"OWNER"`` with the real ``user@host``."""
        from core.utils.row_access import get_row_value

        definer_val = get_row_value(row, "definer")
        if definer_val:
            routine.definer = definer_val

    def extract_partition_scheme_from_row(
        self, extractor: Any, row: Dict[str, Any], table: Any
    ) -> None:
        """MySQL / MariaDB: ``partition_method`` + ``partition_expression``
        with SQL-function stripping (``YEAR(col)`` → ``col``)."""
        import re

        from core.utils.row_access import get_row_value

        part_method = get_row_value(row, "partition_method")
        part_expr = get_row_value(row, "partition_expression")
        if part_method:
            table.partition_method = part_method.upper()
        if part_expr:
            cols = re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\b", part_expr)
            cols = [c for c in cols if c.upper() not in self._SQL_PARTITION_FUNCTIONS]
            if cols:
                table.partition_columns = cols

    provides_view_algorithm = True

    def fetch_view_algorithm(self, extractor: Any, schema: str, view_name: str) -> "Optional[str]":
        """MySQL / MariaDB don't expose the view algorithm via
        ``information_schema.VIEWS``; pull it from ``SHOW CREATE VIEW``
        (which embeds ``ALGORITHM=…`` after the leading ``CREATE``)."""
        import re

        if not getattr(extractor.provider, "query_executor", None):
            return None
        try:
            safe_schema = schema.replace("`", "``")
            safe_view = view_name.replace("`", "``")
            sql = f"SHOW CREATE VIEW `{safe_schema}`.`{safe_view}`"
            rows = extractor.provider.query_executor.execute_query(extractor.connection, sql, [])
            if not rows:
                return None
            row = rows[0]
            create_stmt = row.get("Create View") or row.get("CREATE VIEW") or row.get("create view")
            if not create_stmt or not isinstance(create_stmt, str):
                return None
            match = re.search(r"ALGORITHM=(\w+)", create_stmt.upper())
            if match:
                return match.group(1)
        except Exception as exc:
            extractor.log.debug(
                f"Could not fetch MySQL view algorithm for {schema}.{view_name}: {exc}"
            )
        return None

    def apply_vendor_table_properties(self, table: Any, row: Dict[str, Any]) -> None:
        """Apply MySQL storage engine + row format + collation + create options."""
        from core.utils.row_access import get_row_value

        storage_engine = get_row_value(row, "storage_engine")
        if storage_engine:
            table.set_dialect_option("mysql", "storage_engine", storage_engine)
        row_format = get_row_value(row, "row_format")
        if row_format:
            table.set_dialect_option("mysql", "row_format", row_format)
        table_collation = get_row_value(row, "table_collation")
        if table_collation:
            table.set_dialect_option("mysql", "table_collation", table_collation)
        next_auto_increment = get_row_value(row, "next_auto_increment")
        if next_auto_increment is not None:
            table.set_dialect_option("mysql", "next_auto_increment", next_auto_increment)
        create_options = get_row_value(row, "create_options")
        if create_options:
            table.set_dialect_option("mysql", "create_options", create_options)

    def fk_reference_query(
        self, schema: str, table: str, col: str
    ) -> "Tuple[Optional[str], list[Any]]":
        """MySQL ``information_schema.key_column_usage`` query finding FKs targeting ``col``."""
        sql = """
            SELECT
                constraint_name,
                CONCAT(table_schema, '.', table_name) as table_name
            FROM information_schema.key_column_usage
            WHERE referenced_table_schema = %s
                AND referenced_table_name = %s
                AND referenced_column_name = %s
        """
        return (sql, self.fk_reference_bind_params(schema, table, col))

    def index_reference_query(
        self, schema: str, table: str, col: str
    ) -> "Tuple[Optional[str], list[Any]]":
        """MySQL ``information_schema.statistics`` query listing indexes covering ``col``."""
        sql = """
            SELECT DISTINCT index_name
            FROM information_schema.statistics
            WHERE table_schema = %s
                AND table_name = %s
                AND column_name = %s
        """
        return (sql, [schema, table, col])

    def type_equivalents(self) -> "dict[str, str]":
        """MySQL alias → canonical type map.

        Notably ``BOOLEAN`` → ``TINYINT`` (MySQL's ``BOOLEAN`` is ``TINYINT(1)``),
        ``BIT``/``BOOL`` → ``BOOLEAN``, ``LONG``/``LONG VARCHAR`` → ``MEDIUMTEXT``.
        """
        return {
            "INT": "INTEGER",
            "BOOL": "BOOLEAN",
            "BOOLEAN": "TINYINT",  # MySQL BOOLEAN is TINYINT(1)
            "BIT": "BOOLEAN",
            "CHARACTER VARYING": "VARCHAR",
            "CHARACTER": "CHAR",
            "LONG": "MEDIUMTEXT",
            "LONG VARCHAR": "MEDIUMTEXT",
            "DOUBLE PRECISION": "DOUBLE",
        }

    version_specific_type_mappings = {("mysql", "5.7+"): {"JSON": "JSON"}}

    # Version-gated features (see core.sql_model.feature_gates).
    feature_gates = {
        "rename_column": FeatureGate(
            min_version="8.0+",
            description="ALTER TABLE ... RENAME COLUMN",
        ),
    }

    def type_preferences(self) -> "dict[str, str]":
        """MySQL prefers ``INT`` (not ``INTEGER``) and ``DATETIME`` (not ``TIMESTAMP``)."""
        return {"INTEGER": "INT", "VARCHAR": "VARCHAR", "TIMESTAMP": "DATETIME"}

    def render_computed_column(
        self, col: Any, formatted_col_name: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """MySQL: ``AS (expr) STORED|VIRTUAL`` (no GENERATED ALWAYS prefix)."""
        if not getattr(col, "is_computed", False) or not getattr(col, "computed_expression", None):
            return None, None
        stored = "STORED" if getattr(col, "computed_stored", False) else "VIRTUAL"
        return f"AS ({col.computed_expression}) {stored}", None


__all__ = ["MysqlQuirks"]
