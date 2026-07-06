"""Entry-point declaration for the Amazon Aurora PostgreSQL plugin.

Amazon Aurora PostgreSQL is wire-compatible with PostgreSQL: this plugin reuses PostgreSQL's
config class (``config_dialect="postgresql"``), SQLAlchemy URL builder, and
``psycopg`` driver, attaching only a distinct identity + quirks subclass. Users
keep their ``postgresql://`` connection string and select this engine via
``type: aurora-postgresql``.
"""

from __future__ import annotations

from db.plugins.aurora_postgresql.provider import AuroraPostgresqlProvider
from db.plugins.aurora_postgresql.quirks import AuroraPostgresqlQuirks
from db.plugins.postgresql.sqlalchemy_url import build_sqlalchemy_url
from db.provider_registry import PluginInfo

PLUGIN: PluginInfo = PluginInfo(
    name="aurora-postgresql",
    version="1.0.0",
    description="Amazon Aurora PostgreSQL database provider",
    dialects=["aurora-postgresql"],
    provider_class=AuroraPostgresqlProvider,
    transport="native",
    quirks_class=AuroraPostgresqlQuirks,
    config_dialect="postgresql",  # Amazon Aurora PostgreSQL shares PostgreSQL's config class
    sqlalchemy_url_builder=build_sqlalchemy_url,
    native_driver_module="psycopg",
)
