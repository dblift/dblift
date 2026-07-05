"""Supabase (PostgreSQL) database provider plugin (PostgreSQL-compatible)."""

__plugin_name__ = "supabase"
__plugin_version__ = "1.0.0"
__plugin_description__ = "Supabase (PostgreSQL) database provider"
__plugin_dialects__ = ["supabase"]
__plugin_transport__ = "native"
__plugin_class__ = "SupabaseProvider"

from .provider import SupabaseProvider

__all__ = ["SupabaseProvider"]
