"""CockroachDB :class:`DialectQuirks` - inherits PostgreSQL behavior."""

from __future__ import annotations

from dblift.db.plugins.postgresql.quirks import PostgresqlQuirks


class CockroachdbQuirks(PostgresqlQuirks):
    """CockroachDB quirks, inheriting PostgreSQL behavior."""

    is_ansi_reference_dialect = False
    is_default_sqlglot_read_fallback = False

    # Opt out of PostgreSQL's feature gates: CockroachDB versions its own
    # engine (v23.x reads as ">= 12" to a naive comparison) and PG
    # version-gated semantics do not transfer. ``feature_gates`` replaces the
    # parent dict wholesale — CockroachDB declares no gates.
    feature_gates = {}

    # CockroachDB is a ground-up reimplementation, not a PostgreSQL fork, so
    # wire compatibility alone isn't evidence for its comment grammar. Run
    # directly against a single-node CockroachDB container: after
    # ``CREATE TABLE victim (id INT)``, ``/* outer /* inner */ DROP TABLE
    # victim; still outer */ SELECT 1;`` returned one ``SELECT 1`` row with
    # no error and left ``victim`` in place — the whole span read as one
    # comment. Block comments nest here the same way they do in PostgreSQL,
    # so this keeps inheriting the nesting parser unchanged.
    def __init__(self, dialect_name: str = "cockroachdb") -> None:
        super().__init__(dialect_name=dialect_name)

    def type_equivalents(self) -> dict[str, str]:
        """Normalize aliases using CockroachDB's default integer widths.

        Assumes ``default_int_size = 8`` and ``serial_normalization = rowid``;
        the normalizer cannot observe these session or cluster settings.
        With rowid normalization, every SERIAL spelling uses INT8 to fit
        ``unique_rowid()`` values, regardless of the requested serial size.
        Explicit INT4 and INT2 retain their PostgreSQL widths.
        """
        equivalents = super().type_equivalents()
        equivalents.update(
            {
                "INT": "BIGINT",
                "INTEGER": "BIGINT",
                "SERIAL": "BIGINT",
                "SERIAL2": "BIGINT",
                "SERIAL4": "BIGINT",
                "SERIAL8": "BIGINT",
                "SMALLSERIAL": "BIGINT",
                "BIGSERIAL": "BIGINT",
            }
        )
        return equivalents


__all__ = ["CockroachdbQuirks"]
