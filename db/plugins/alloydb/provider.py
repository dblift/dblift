"""Google AlloyDB for PostgreSQL native provider (PostgreSQL-compatible)."""

from __future__ import annotations

from db.plugins.postgresql.provider import PostgreSqlProvider


class AlloydbProvider(PostgreSqlProvider):
    """Google AlloyDB for PostgreSQL — wire-compatible with PostgreSQL; reuses the PostgreSQL provider."""

    canonical_dialect_key = "alloydb"


__all__ = ["AlloydbProvider"]
