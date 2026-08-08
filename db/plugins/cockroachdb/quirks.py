"""CockroachDB :class:`DialectQuirks` - inherits PostgreSQL behavior."""

from __future__ import annotations

from db.plugins.postgresql.quirks import PostgresqlQuirks


class CockroachdbQuirks(PostgresqlQuirks):
    """CockroachDB quirks, inheriting PostgreSQL behavior."""

    is_ansi_reference_dialect = False
    is_default_sqlglot_read_fallback = False

    # Opt out of PostgreSQL's feature gates: CockroachDB versions its own
    # engine (v23.x reads as ">= 12" to a naive comparison) and PG
    # version-gated semantics do not transfer. ``feature_gates`` replaces the
    # parent dict wholesale — CockroachDB declares no gates.
    feature_gates = {}

    # CockroachDB always builds indexes online: per Cockroach Labs' own
    # CREATE INDEX reference, "CONCURRENTLY" is "optional, no-op syntax for
    # PostgreSQL compatibility. All indexes are created concurrently in
    # CockroachDB." Inheriting PostgreSQL's ``True`` here would recommend
    # adding a keyword that changes nothing, as though the plain form were
    # the one that blocks.
    supports_concurrent_index = False

    def __init__(self, dialect_name: str = "cockroachdb") -> None:
        super().__init__(dialect_name=dialect_name)


__all__ = ["CockroachdbQuirks"]
