"""Redshift native provider (PostgreSQL-compatible)."""

from __future__ import annotations

from db.plugins.postgresql.provider import PostgreSqlProvider


class RedshiftProvider(PostgreSqlProvider):
    """Redshift reuses the PostgreSQL provider."""

    canonical_dialect_key = "redshift"


__all__ = ["RedshiftProvider"]
