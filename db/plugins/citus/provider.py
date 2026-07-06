"""Citus (distributed PostgreSQL) native provider (PostgreSQL-compatible)."""

from __future__ import annotations

from db.plugins.postgresql.provider import PostgreSqlProvider


class CitusProvider(PostgreSqlProvider):
    """Citus (distributed PostgreSQL) — wire-compatible with PostgreSQL; reuses the PostgreSQL provider."""

    canonical_dialect_key = "citus"


__all__ = ["CitusProvider"]
