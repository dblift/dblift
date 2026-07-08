"""Redshift :class:`DialectQuirks` - inherits PostgreSQL behavior."""

from __future__ import annotations

from db.plugins.postgresql.quirks import PostgresqlQuirks


class RedshiftQuirks(PostgresqlQuirks):
    """Redshift quirks, inheriting PostgreSQL behavior."""

    is_ansi_reference_dialect = False
    is_default_sqlglot_read_fallback = False

    def __init__(self, dialect_name: str = "redshift") -> None:
        super().__init__(dialect_name=dialect_name)


__all__ = ["RedshiftQuirks"]
