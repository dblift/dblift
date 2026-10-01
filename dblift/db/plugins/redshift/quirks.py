"""Redshift :class:`DialectQuirks` - inherits PostgreSQL behavior."""

from __future__ import annotations

from typing import Optional

from dblift.db.plugins.postgresql.quirks import PostgresqlQuirks


class RedshiftQuirks(PostgresqlQuirks):
    """Redshift quirks, inheriting PostgreSQL behavior."""

    is_ansi_reference_dialect = False
    is_default_sqlglot_read_fallback = False

    # Redshift's DDL diverges from plain Postgres syntax (e.g. the
    # DISTKEY/SORTKEY table-distribution clauses below), and sqlglot ships a
    # dedicated ``redshift`` dialect for exactly that reason. Inheriting
    # PostgreSQL's ``sqlglot_dialect = "postgres"`` parses that divergent
    # syntax but then fails to render it back out.
    sqlglot_dialect = "redshift"

    # Opt out of PostgreSQL's feature gates: Redshift's engine diverged long
    # ago (its version() banner even reports PostgreSQL 8.0.x), so PG
    # version-gated semantics do not transfer. ``feature_gates`` replaces the
    # parent dict wholesale — Redshift declares no gates.
    feature_gates = {}

    def __init__(self, dialect_name: str = "redshift") -> None:
        super().__init__(dialect_name=dialect_name)

    def parser_class(self, parser_type: str) -> Optional[type]:
        """Kept non-nesting, unverified: no local Redshift engine, and no
        documentation found that addresses comment nesting in top-level SQL
        (the AWS "Structure of PL/pgSQL" page says block comments don't nest,
        but that sentence describes comments inside a PL/pgSQL procedure
        body's ``$$ ... $$``, not the outer SQL scanner ``split_statements``
        tokenizes — it is not evidence for this). Keep the pre-#333 reader
        (first ``*/`` closes) as the safer default rather than inherit
        PostgreSQL's nesting unverified; everything else about PostgreSQL
        parsing still applies.
        """
        if parser_type == "regex":
            from dblift.db.plugins.postgresql.parser.postgresql_regex_parser import (
                NonNestingPostgreSqlRegexParser,
            )

            return NonNestingPostgreSqlRegexParser
        return super().parser_class(parser_type)

    def build_snapshot_table_ddl(
        self,
        qualified_table: str,
        snapshot_id_size: int,
        checksum_size: int,
    ) -> str:
        """Render snapshot storage with Redshift's widest VARCHAR payload column."""
        return (
            f"CREATE TABLE {qualified_table} ("
            f"snapshot_id VARCHAR({snapshot_id_size}) PRIMARY KEY, "
            f"captured_at VARCHAR({snapshot_id_size}) NOT NULL, "
            f"checksum VARCHAR({checksum_size}) NOT NULL, "
            f"model_data VARCHAR(MAX) NOT NULL)"
        )


__all__ = ["RedshiftQuirks"]
