"""Oracle :class:`DialectQuirks`."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, List, Optional, Tuple

from dblift.db.base_quirks import BaseQuirks
from dblift.db.error import ErrorCategory
from dblift.db.feature_gate import FeatureGate

if TYPE_CHECKING:
    from dblift.db.version import DatabaseVersion


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
    pre-processing, and Oracle-specific DDL rendering.
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

    def is_schema_history_race_error(self, error_message: str) -> bool:
        """Oracle's ``CREATE TABLE`` for the migration history table has no
        ``IF NOT EXISTS`` guard; a concurrent migration bootstrap loses with
        ORA-00955 ("name is already used by an existing object"), which the
        base English markers don't contain (they look for "already
        exists")."""
        if "ORA-00955" in (error_message or ""):
            return True
        return super().is_schema_history_race_error(error_message)

    sqlglot_unsupported_sql_patterns = (
        "PARTITION BY REFERENCE",
        "PARTITION BY RANGE",
        "PARTITION BY LIST",
        "INTERVAL (",
    )
    connection_probe_sql = "SELECT 1 FROM DUAL"
    boolean_false_literal = "0"
    unquoted_identifier_case = "uppercase"
    # quote_qualified upper-cases idents to match Oracle's catalogue folding.
    # DB2 shares the folding quirks but must NOT inherit this.
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

    # Index DDL.
    index_drop_standalone_supports_if_exists = True  # native since 23ai / 19.28
    # Trigger DDL.
    trigger_terminator = "\n/"
    # Engine-internal materialized-view support objects to skip during
    # catalog reads. Non-empty also signals MV-name preloading.
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

    # Table DDL.
    table_supports_storage_params = True
    supports_sqlplus_preprocessing = True
    # Wave B hooks.
    native_driver_display = "python-oracledb"
    # Oracle TIMESTAMP / TIME accept only fractional-seconds precision.
    # validate-sql offline placeholder — a service_name is required, so a
    # bare host/port URL is not enough (see build_sqlalchemy_url).
    lint_placeholder_url = "oracle://localhost:1521/?service_name=XEPDB1"

    def __init__(self, dialect_name: str = "oracle") -> None:
        """Initialize Oracle quirks with the dialect name."""
        super().__init__(dialect_name=dialect_name)

    def error_patterns(self) -> "List[Tuple[re.Pattern[str], ErrorCategory]]":
        """Oracle ORA-code error-classification patterns (ADR-26 A2)."""
        return _ERROR_PATTERNS

    # ------------------------------------------------------------------
    # Migration-script preprocessing hooks (Tier 1 plugin-isolation).
    # Lazy imports keep ``dblift.db.plugins.oracle.parser`` out of the import
    # graph until a script actually needs SQL*Plus handling.
    # ------------------------------------------------------------------

    def extract_script_context(self, sql: str) -> Optional[object]:
        """Extract Oracle SQL*Plus directives (``SET SERVEROUTPUT``, ``DEFINE``, …)."""
        from dblift.db.plugins.oracle.parser.sqlplus_context import extract_sqlplus_context

        return extract_sqlplus_context(sql)

    def terminate_script_directives(self, sql: str) -> str:
        """Keep SQL*Plus directive lines from merging with the next statement."""
        from dblift.db.plugins.oracle.parser.sqlplus_context import terminate_sqlplus_directives

        return terminate_sqlplus_directives(sql)

    def apply_script_substitution(self, sql: str, ctx: Optional[object]) -> str:
        """Apply SQL*Plus ``&var`` / ``&&var`` substitution using *ctx*."""
        if ctx is None:
            return sql
        from dblift.db.plugins.oracle.parser.sqlplus_context import (
            SqlplusContext,
            apply_define_substitution,
        )

        if not isinstance(ctx, SqlplusContext):
            return sql
        return apply_define_substitution(sql, ctx)

    def parse_error_policy_directive(self, stmt: str) -> Optional[str]:
        """Return the Oracle ``WHENEVER SQLERROR`` policy encoded in *stmt*, or ``None``."""
        from dblift.db.plugins.oracle.parser._sqlplus import parse_whenever_sqlerror

        return parse_whenever_sqlerror(stmt)

    def enable_session_output(self, connection: Any) -> None:
        """Enable Oracle ``DBMS_OUTPUT`` capture on the active native connection."""
        from dblift.db.plugins.oracle.oracle.dbms_output import enable_dbms_output

        enable_dbms_output(connection)

    def read_session_output(self, connection: Any, log: Any) -> None:
        """Drain Oracle ``DBMS_OUTPUT`` and route each line to *log*."""
        from dblift.db.plugins.oracle.oracle.dbms_output import read_dbms_output

        read_dbms_output(connection, log)

    def parser_class(self, parser_type: str) -> Optional[type]:
        """Oracle parser dispatch: hybrid → :class:`HybridParser`, sqlglot →
        :class:`SqlGlotParser` (``oracle`` dialect), regex → :class:`OracleParser`."""
        if parser_type == "hybrid":
            from dblift.core.sql_parser.hybrid_parser import HybridParser

            return HybridParser
        if parser_type == "sqlglot":
            from dblift.core.sql_parser.sqlglot_parser import SqlGlotParser

            return SqlGlotParser
        if parser_type == "regex":
            from dblift.db.plugins.oracle.parser.oracle_parser import OracleParser

            return OracleParser
        return None

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

    # Edition-gated features (see core.sql_model.feature_gates). The pattern
    # matches the v$version banner, which doubles as the captured edition.
    feature_gates = {
        "online_index_build": FeatureGate(
            # Enterprise Edition and Oracle Database Free (23ai/26ai) both
            # support CREATE INDEX ... ONLINE — Free ships the full
            # Enterprise feature set, only resource-limited, not
            # feature-limited (issue #908).
            edition_pattern=r"enterprise|free",
            description="CREATE INDEX ... ONLINE",
        ),
        "row_limit_fetch_first": FeatureGate(
            min_version="12.1+",
            description="SELECT row limiting with FETCH FIRST n ROWS ONLY",
        ),
        "online_table_move": FeatureGate(
            # Oracle's Database Licensing Information User Manual (Table 1-4,
            # High Availability) lists "ALTER TABLE ... MOVE ONLINE
            # operations" as N for Standard Edition 2, Y for Enterprise
            # Edition and above -- same edition floor as online_index_build,
            # including Free (issue #908: Free ships the full Enterprise
            # feature set, only resource-limited). Online move of a whole
            # (non-partitioned) table is a 12.2 feature; 12.1 only supports
            # it for partitions/subpartitions.
            edition_pattern=r"enterprise|free",
            min_version="12.2+",
            description="ALTER TABLE ... MOVE ONLINE",
        ),
    }

    _MARKETING_VERSION_RE = re.compile(r"\b(\d{2})(?:c|g|ai)\b", re.IGNORECASE)

    def parse_server_version(self, raw: "Optional[str]") -> "Optional[DatabaseVersion]":
        """Oracle banners without a ``Release x.y.z`` clause (e.g. ``"Oracle
        Database 23ai Free"``) still carry a marketing version — fall back
        to its major number when the generic dotted-run parse finds nothing.
        """
        from dblift.db.version import DatabaseVersion, parse_version

        version = parse_version(raw)
        if version is not None or not raw:
            return version
        match = self._MARKETING_VERSION_RE.search(raw)
        if match is None:
            return None
        return DatabaseVersion(major=int(match.group(1)), full_version=raw)


__all__ = ["OracleQuirks"]
