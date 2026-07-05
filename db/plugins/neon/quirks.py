"""Neon (serverless PostgreSQL) :class:`DialectQuirks` — inherits PostgreSQL behavior."""

from __future__ import annotations

from db.plugins.postgresql.quirks import PostgresqlQuirks


class NeonQuirks(PostgresqlQuirks):
    """Neon (serverless PostgreSQL) quirks, inheriting every PostgreSQL quirk.

    Neon (serverless PostgreSQL) speaks the PostgreSQL wire protocol, so statement splitting,
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

    def __init__(self, dialect_name: str = "neon") -> None:
        super().__init__(dialect_name=dialect_name)


__all__ = ["NeonQuirks"]
