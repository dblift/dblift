"""Redshift :class:`DialectQuirks` - inherits PostgreSQL behavior."""

from __future__ import annotations

from db.plugins.postgresql.quirks import PostgresqlQuirks


class RedshiftQuirks(PostgresqlQuirks):
    """Redshift quirks, inheriting PostgreSQL behavior."""

    is_ansi_reference_dialect = False
    is_default_sqlglot_read_fallback = False

    # Opt out of PostgreSQL's feature gates: Redshift's engine diverged long
    # ago (its version() banner even reports PostgreSQL 8.0.x), so PG
    # version-gated semantics do not transfer. ``feature_gates`` replaces the
    # parent dict wholesale — Redshift declares no gates.
    feature_gates = {}

    # Redshift has no ``INSERT … ON CONFLICT``: the clause was never
    # implemented, and its own upsert guidance is a staging table (or, since
    # 2023, ``MERGE``). Inheriting PostgreSQL's ``"on_conflict"`` here would
    # emit SQL the server rejects, so it reverts to the portable
    # UPDATE-then-INSERT fallback.
    upsert_style = "none"

    # Redshift has no JSONB type: semi-structured JSON is stored as ``SUPER``.
    # Inheriting PostgreSQL's ``"JSONB"`` here would emit ``CAST(? AS JSONB)``,
    # which the server rejects outright (*type "jsonb" does not exist*), so a
    # serialized JSON value binds as plain text with no cast at all — the same
    # reason ``upsert_style`` reverts to ``"none"`` above.
    json_bind_cast_type = None

    # Redshift has no ``CREATE INDEX`` at all (it uses sort keys and zone
    # maps instead of B-tree indexes), so inheriting PostgreSQL's
    # ``supports_concurrent_index = True`` would recommend a ``CONCURRENTLY``
    # form the server has no syntax for whatsoever — the same
    # never-declared-only-inherited gap ``upsert_style``/``json_bind_cast_type``
    # above already fixed for other capabilities.
    supports_concurrent_index = False

    def __init__(self, dialect_name: str = "redshift") -> None:
        super().__init__(dialect_name=dialect_name)

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
