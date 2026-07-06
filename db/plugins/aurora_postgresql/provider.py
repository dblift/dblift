"""Amazon Aurora PostgreSQL native provider (PostgreSQL-compatible)."""

from __future__ import annotations

from db.plugins.postgresql.provider import PostgreSqlProvider


class AuroraPostgresqlProvider(PostgreSqlProvider):
    """Amazon Aurora PostgreSQL — wire-compatible with PostgreSQL; reuses the PostgreSQL provider."""

    canonical_dialect_key = "aurora-postgresql"


__all__ = ["AuroraPostgresqlProvider"]
