"""Entry-point declaration for the Neon (serverless PostgreSQL) plugin.

Neon (serverless PostgreSQL) is wire-compatible with PostgreSQL: this plugin reuses PostgreSQL's
config class (``config_dialect="postgresql"``), SQLAlchemy URL builder, and
``psycopg`` driver, attaching only a distinct identity + quirks subclass. Users
keep their ``postgresql://`` connection string and select this engine via
``type: neon``.
"""

from __future__ import annotations

from db.plugins.neon.provider import NeonProvider
from db.plugins.neon.quirks import NeonQuirks
from db.plugins.postgresql.sqlalchemy_url import build_sqlalchemy_url
from db.provider_registry import PluginInfo

PLUGIN: PluginInfo = PluginInfo(
    name="neon",
    version="1.0.0",
    description="Neon (serverless PostgreSQL) database provider",
    dialects=["neon"],
    provider_class=NeonProvider,
    transport="native",
    quirks_class=NeonQuirks,
    config_dialect="postgresql",  # Neon (serverless PostgreSQL) shares PostgreSQL's config class
    sqlalchemy_url_builder=build_sqlalchemy_url,
    native_driver_module="psycopg",
)
