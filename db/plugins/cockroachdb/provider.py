"""CockroachDB native provider (PostgreSQL-compatible)."""

from __future__ import annotations

from db.plugins.postgresql.provider import PostgreSqlProvider


class CockroachdbProvider(PostgreSqlProvider):
    """CockroachDB reuses the PostgreSQL provider."""

    canonical_dialect_key = "cockroachdb"


__all__ = ["CockroachdbProvider"]
