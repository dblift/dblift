"""MySQL :class:`DialectQuirks`."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from dblift.core.utils.database_url_parser import DatabaseUrlParser
from dblift.db.base_quirks import BaseQuirks
from dblift.db.error import ErrorCategory
from dblift.db.feature_gate import FeatureGate

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
    quote_open = "`"
    quote_close = "`"
    drop_supports_if_exists = True
    tinyint1_is_boolean = True
    # Index DDL.
    index_drop_includes_table = True
    index_drop_table_form_supports_if_exists = False
    # sqlglot's mysql grammar rejects DROP INDEX ("... always requires an ON
    # clause" — see index_drop_includes_table above) when the ON target is
    # schema-qualified, i.e. every DROP INDEX outside the default catalog.
    # The unqualified form parses fine. The regex parser already extracts
    # this shape correctly (index name + schema), so skip sqlglot for it
    # entirely instead of letting it raise on a routine DROP INDEX (#379).
    # The gap between INDEX and ON excludes ";" so the match cannot cross
    # into a *different* statement in a multi-statement ``extract_objects``
    # call and false-positive on an unrelated "... ON x.y" elsewhere in the
    # batch (e.g. a JOIN clause) — this must describe the one DROP INDEX
    # statement, not the whole blob it may be embedded in.
    sqlglot_unsupported_sql_regex_patterns = (r"DROP\s+INDEX\s+[^;]+\bON\s+[^\s;,()]*\.",)
    # Trigger DDL.
    trigger_supports_definer_clause = True
    # Event scheduler timestamp-quoting.
    event_supports_mysql_schedule = True
    # Table DDL.
    table_uses_storage_engine_clause = True
    # Wave B hooks.
    native_driver_display = "pymysql"
    # validate-sql offline placeholder. Inherited by MariaDB, whose config
    # class is MySQL's own (config_dialect="mysql") and builds mysql:// URLs.
    lint_placeholder_url = "mysql://localhost/dblift_validate_sql"

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

    def parser_class(self, parser_type: str) -> Optional[type]:
        """MySQL parser dispatch: hybrid → :class:`HybridParser`, sqlglot →
        :class:`SqlGlotParser`, regex → :class:`MySqlRegexParser`."""
        if parser_type == "hybrid":
            from dblift.core.sql_parser.hybrid_parser import HybridParser

            return HybridParser
        if parser_type == "sqlglot":
            from dblift.core.sql_parser.sqlglot_parser import SqlGlotParser

            return SqlGlotParser
        if parser_type == "regex":
            from dblift.db.plugins.mysql.parser.mysql_regex_parser import MySqlRegexParser

            return MySqlRegexParser
        return None

    def enrich_view_from_row(self, view: Any, row: Dict[str, Any], view_status: Any = None) -> None:
        """MySQL / MariaDB views carry ``DEFINER`` (``user@host``) and
        ``SQL SECURITY`` (DEFINER | INVOKER) clauses recorded in
        ``information_schema.views``. The ``ALGORITHM`` clause is fetched
        via ``SHOW CREATE VIEW`` elsewhere, through the separate
        ``fetch_view_algorithm`` hook."""
        from dblift.core.utils.row_access import get_row_value

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
        from dblift.core.utils.row_access import get_row_value

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
        """MySQL / MariaDB: ``information_schema.ROUTINES`` exposes
        only the body, not the full CREATE statement. Skip when a
        definition is already attached; otherwise issue ``SHOW CREATE
        PROCEDURE`` / ``SHOW CREATE FUNCTION`` and refresh ``body`` from
        the ``BEGIN`` offset."""
        if routine.definition is not None:
            return
        from dblift.core.utils.metadata_helpers import (
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
        from dblift.core.utils.row_access import get_row_value

        deterministic = (get_row_value(row, "is_deterministic") or "").upper()
        routine.volatility = "IMMUTABLE" if deterministic == "YES" else "VOLATILE"

    def apply_routine_definer_from_row(
        self, extractor: Any, routine: Any, row: Dict[str, Any]
    ) -> None:
        """MySQL / MariaDB: ``definer`` column has final authority (it runs
        after the generic ``execute_as_principal`` / ``EXECUTE AS OWNER``
        path), so it can replace ``"OWNER"`` with the real ``user@host``."""
        from dblift.core.utils.row_access import get_row_value

        definer_val = get_row_value(row, "definer")
        if definer_val:
            routine.definer = definer_val

    def extract_partition_scheme_from_row(
        self, extractor: Any, row: Dict[str, Any], table: Any
    ) -> None:
        """MySQL / MariaDB: ``partition_method`` + ``partition_expression``
        with SQL-function stripping (``YEAR(col)`` → ``col``)."""
        import re

        from dblift.core.utils.row_access import get_row_value

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
        from dblift.core.utils.row_access import get_row_value

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

    # Version-gated features (see core.sql_model.feature_gates).
    feature_gates = {
        "rename_column": FeatureGate(
            min_version="8.0+",
            description="ALTER TABLE ... RENAME COLUMN",
        ),
        "json_bind_cast": FeatureGate(
            min_version="5.7.8+",
            description="Native JSON parameter casting with CAST(? AS JSON)",
        ),
        "instant_add_column": FeatureGate(
            # INSTANT is the default ALGORITHM as of 8.0.12 (INPLACE before
            # that, which still rebuilds/rewrites the table for ADD COLUMN).
            # Version-only: this is not edition-gated, but still narrower
            # than "any ADD COLUMN is instant" -- callers must separately
            # account for the per-statement restrictions this gate does not
            # model (ROW_FORMAT=COMPRESSED, FULLTEXT index, an added
            # AUTO_INCREMENT column disallowing concurrent DML, and, before
            # 8.0.29, INSTANT only adding a column as the last column).
            min_version="8.0.12+",
            description="ALTER TABLE ... ADD COLUMN, ALGORITHM=INSTANT",
        ),
    }


__all__ = ["MysqlQuirks"]
