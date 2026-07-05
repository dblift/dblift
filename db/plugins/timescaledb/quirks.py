"""TimescaleDB (PostgreSQL extension) :class:`DialectQuirks` — inherits PostgreSQL behavior."""

from __future__ import annotations

from db.plugins.postgresql.quirks import PostgresqlQuirks


class TimescaledbQuirks(PostgresqlQuirks):
    """TimescaleDB (PostgreSQL extension) quirks, inheriting every PostgreSQL quirk.

    TimescaleDB (PostgreSQL extension) speaks the PostgreSQL wire protocol, so statement splitting,
    rendering, comparison, and introspection all reuse PostgreSQL's behavior.
    Only the ANSI-reference flag is overridden: exactly one registered plugin
    (PostgreSQL) may be the reference dialect, so PostgreSQL-derived plugins
    must not re-claim it. Engine-specific deviations land here if and when the
    codebase needs them.
    """

    # Exactly one plugin owns the ANSI reference dialect (PostgreSQL); a
    # PG-derived plugin that inherited ``True`` would break
    # ``ProviderRegistry.reference_dialect_name`` (which requires a single
    # winner), so reset it here.
    is_ansi_reference_dialect = False
    # PostgreSQL is likewise the single owner of the sqlglot read-dialect
    # fallback; a PG-derived plugin must not claim it either.
    is_default_sqlglot_read_fallback = False

    def __init__(self, dialect_name: str = "timescaledb") -> None:
        super().__init__(dialect_name=dialect_name)


__all__ = ["TimescaledbQuirks"]
