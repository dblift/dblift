"""YugabyteDB (PostgreSQL-compatible) native provider (PostgreSQL-compatible)."""

from __future__ import annotations

from db.plugins.postgresql.provider import PostgreSqlProvider


class YugabytedbProvider(PostgreSqlProvider):
    """YugabyteDB (PostgreSQL-compatible) — wire-compatible with PostgreSQL; reuses the PostgreSQL provider."""

    canonical_dialect_key = "yugabytedb"


__all__ = ["YugabytedbProvider"]
