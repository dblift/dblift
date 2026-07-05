"""Entry-point declaration for the Supabase (PostgreSQL) plugin.

Supabase (PostgreSQL) is wire-compatible with PostgreSQL: this plugin reuses PostgreSQL's
config class (``config_dialect="postgresql"``), SQLAlchemy URL builder, and
``psycopg`` driver, attaching only a distinct identity + quirks subclass. Users
keep their ``postgresql://`` connection string and select this engine via
``type: supabase``.
"""

from __future__ import annotations

from db.plugins.postgresql.sqlalchemy_url import build_sqlalchemy_url
from db.plugins.supabase.provider import SupabaseProvider
from db.plugins.supabase.quirks import SupabaseQuirks
from db.provider_registry import PluginInfo

PLUGIN: PluginInfo = PluginInfo(
    name="supabase",
    version="1.0.0",
    description="Supabase (PostgreSQL) database provider",
    dialects=["supabase"],
    provider_class=SupabaseProvider,
    transport="native",
    quirks_class=SupabaseQuirks,
    config_dialect="postgresql",  # Supabase (PostgreSQL) shares PostgreSQL's config class
    sqlalchemy_url_builder=build_sqlalchemy_url,
    native_driver_module="psycopg",
)
