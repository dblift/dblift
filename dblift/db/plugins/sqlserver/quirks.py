"""SQL Server :class:`DialectQuirks`."""

from __future__ import annotations

import re
from typing import Any, Optional

from dblift.db.base_quirks import BaseQuirks
from dblift.db.feature_gate import FeatureGate

_PK_CLUSTERED_RE = re.compile(r"(PRIMARY\s+KEY)\s+(CLUSTERED|NONCLUSTERED)", re.IGNORECASE)
_UNIQUE_CLUSTERED_RE = re.compile(r"(UNIQUE)\s+(CLUSTERED|NONCLUSTERED)", re.IGNORECASE)


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
    is_sqlserver_family = True
    # sqlglot's tsql grammar rejects DROP INDEX's modern form
    # ("DROP INDEX index ON table") when the table is schema-qualified —
    # the ordinary, everyday spelling, not an edge case. It parses the
    # unqualified form and the legacy dot-qualified form ("DROP INDEX
    # table.index") fine; only the combination of ON *and* a qualified
    # table fails. The regex parser already extracts this shape
    # correctly (index name + schema), so skip sqlglot for it entirely
    # instead of letting it raise on every routine DROP INDEX (#379).
    # The gap between INDEX and ON excludes ";" so the match cannot cross
    # into a *different* statement in a multi-statement ``extract_objects``
    # call and false-positive on an unrelated "... ON x.y" elsewhere in the
    # batch (e.g. a JOIN clause) — this must describe the one DROP INDEX
    # statement, not the whole blob it may be embedded in.
    sqlglot_unsupported_sql_regex_patterns = (r"DROP\s+INDEX\s+[^;]+\bON\s+[^\s;,()]*\.",)

    def is_schema_history_race_error(self, error_message: str) -> bool:
        """SQL Server's ``CREATE TABLE`` for the migration history table has
        no ``IF NOT EXISTS`` guard; a concurrent migration bootstrap loses
        with Msg 2714 ("There is already an object named ..."), which the
        base English markers don't contain."""
        if "already an object named" in (error_message or "").lower():
            return True
        return super().is_schema_history_race_error(error_message)

    connection_identifier_attrs = ("url", "host", "database")
    missing_connection_identifier_hint = (
        "SQL Server connection requires url or host/database fields"
    )
    quote_open = "["
    quote_close = "]"
    boolean_false_literal = "0"
    supports_go_batch_separator = True

    def is_batch_separator(self, stmt: str) -> bool:
        """Return ``True`` for T-SQL ``GO`` batch separators (SSMS / sqlcmd)."""
        from dblift.db.plugins.sqlserver.parser.tsql_batch_separator import is_tsql_batch_separator

        return is_tsql_batch_separator(stmt)

    parser_default_schema = "dbo"

    def derive_schema_name(self, database_config: Any) -> Optional[str]:
        """Use SQL Server's conventional default schema when none is supplied."""
        return self.parser_default_schema

    drop_supports_if_exists = True  # SQL Server 2016+ supports DROP ... IF EXISTS
    unquoted_identifier_case = "case_insensitive"
    # Procedure / function DDL.
    proc_param_inout_keyword = "OUTPUT"
    # Index DDL.
    index_drop_includes_table = True
    index_drop_table_form_supports_if_exists = True
    # UDT / Table DDL.
    table_uses_filegroup_syntax = True

    # Wave B hooks.
    native_driver_display = "pymssql"
    # SQL Server encodes ``VARCHAR(MAX)`` / ``NVARCHAR(MAX)`` via the
    # column-size sentinels ``-1`` (VARCHAR) and ``2147483647`` (NVARCHAR).
    # validate-sql offline placeholder.
    lint_placeholder_url = "mssql://localhost:1433/dblift_validate_sql"

    def __init__(self, dialect_name: str = "sqlserver") -> None:
        """Initialize SQL Server quirks with the dialect name."""
        super().__init__(dialect_name=dialect_name)

    def parser_class(self, parser_type: str) -> Optional[type]:
        """SQL Server parser dispatch: hybrid → :class:`HybridParser`, sqlglot →
        :class:`SqlGlotParser` (``tsql`` dialect), regex → :class:`SqlServerRegexParser`."""
        if parser_type == "hybrid":
            from dblift.core.sql_parser.hybrid_parser import HybridParser

            return HybridParser
        if parser_type == "sqlglot":
            from dblift.core.sql_parser.sqlglot_parser import SqlGlotParser

            return SqlGlotParser
        if parser_type == "regex":
            from dblift.db.plugins.sqlserver.parser.sqlserver_regex_parser import (
                SqlServerRegexParser,
            )

            return SqlServerRegexParser
        return None

    def preprocess_sql_for_sqlglot(self, sql_content: str) -> str:
        """Strip CLUSTERED/NONCLUSTERED from PK/UNIQUE — sqlglot can't parse them."""
        result = _PK_CLUSTERED_RE.sub(r"\1", sql_content)
        return _UNIQUE_CLUSTERED_RE.sub(r"\1", result)

    non_transactional_sql_patterns = (
        (
            r"^CREATE\s+FULLTEXT\s+CATALOG\b",
            "SQL Server CREATE FULLTEXT CATALOG cannot run inside a user transaction",
        ),
        (
            r"^CREATE\s+FULLTEXT\s+INDEX\b",
            "SQL Server CREATE FULLTEXT INDEX cannot run inside a user transaction",
        ),
        (
            r"^DROP\s+FULLTEXT\s+INDEX\b",
            "SQL Server DROP FULLTEXT INDEX cannot run inside a user transaction",
        ),
        (
            r"^DROP\s+FULLTEXT\s+CATALOG\b",
            "SQL Server DROP FULLTEXT CATALOG cannot run inside a user transaction",
        ),
    )

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

    # Edition-gated features (see core.sql_model.feature_gates). The edition
    # pattern matches SERVERPROPERTY('Edition') strings; Azure SQL always
    # supports online index builds.
    feature_gates = {
        "online_index_build": FeatureGate(
            edition_pattern=r"enterprise|developer|evaluation|azure",
            description="WITH (ONLINE = ON) index builds",
        ),
        # ALTER TABLE ... ALTER COLUMN WITH (ONLINE = ON): introduced in SQL
        # Server 2016 (internal version 13.0), same edition set
        # as online_index_build (Enterprise/Developer/Evaluation/Azure)
        # only. Without a proven server, callers stay conservative rather
        # than assuming a feature two years newer than online index builds
        # is available on the same edition floor.
        "online_alter_column": FeatureGate(
            min_version="13.0+",
            edition_pattern=r"enterprise|developer|evaluation|azure",
            description="WITH (ONLINE = ON) ALTER COLUMN",
        ),
    }


__all__ = ["SqlserverQuirks"]
