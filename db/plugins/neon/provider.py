"""Neon (serverless PostgreSQL) native provider (PostgreSQL-compatible)."""

from __future__ import annotations

from db.plugins.postgresql.provider import PostgreSqlProvider


class NeonProvider(PostgreSqlProvider):
    """Neon (serverless PostgreSQL) — wire-compatible with PostgreSQL; reuses the PostgreSQL provider."""

    canonical_dialect_key = "neon"


__all__ = ["NeonProvider"]
