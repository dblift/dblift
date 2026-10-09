"""DB2 :class:`DialectQuirks`."""

from __future__ import annotations

import re
from typing import Any, List, Optional, Tuple

from dblift.db.base_quirks import BaseQuirks
from dblift.db.error import ErrorCategory

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
    # DB2 identity metadata needs a catalog fallback in addition to the
    # projected column flag; ColumnExtractor consults a preloaded identity
    # column set when this is True.
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
