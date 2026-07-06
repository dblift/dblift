"""Supabase (PostgreSQL) native provider (PostgreSQL-compatible)."""

from __future__ import annotations

from db.plugins.postgresql.provider import PostgreSqlProvider


class SupabaseProvider(PostgreSqlProvider):
    """Supabase (PostgreSQL) — wire-compatible with PostgreSQL; reuses the PostgreSQL provider."""

    canonical_dialect_key = "supabase"


__all__ = ["SupabaseProvider"]
