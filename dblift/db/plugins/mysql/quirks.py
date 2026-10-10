"""MySQL :class:`DialectQuirks`."""

from __future__ import annotations

import re
from typing import Any, List, Optional, Tuple

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
