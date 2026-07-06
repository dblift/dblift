"""TimescaleDB (PostgreSQL extension) native provider (PostgreSQL-compatible)."""

from __future__ import annotations

from db.plugins.postgresql.provider import PostgreSqlProvider


class TimescaledbProvider(PostgreSqlProvider):
    """TimescaleDB (PostgreSQL extension) — wire-compatible with PostgreSQL; reuses the PostgreSQL provider."""

    canonical_dialect_key = "timescaledb"


__all__ = ["TimescaledbProvider"]
