"""Entry-point declaration for the Citus (distributed PostgreSQL) plugin.

Citus (distributed PostgreSQL) is wire-compatible with PostgreSQL: this plugin reuses PostgreSQL's
config class (``config_dialect="postgresql"``), SQLAlchemy URL builder, and
``psycopg`` driver, attaching only a distinct identity + quirks subclass. Users
keep their ``postgresql://`` connection string and select this engine via
``type: citus``.
"""

from __future__ import annotations

from db.plugins.citus.provider import CitusProvider
from db.plugins.citus.quirks import CitusQuirks
from db.plugins.postgresql.sqlalchemy_url import build_sqlalchemy_url
from db.provider_registry import PluginInfo

PLUGIN: PluginInfo = PluginInfo(
    name="citus",
    version="1.0.0",
    description="Citus (distributed PostgreSQL) database provider",
    dialects=["citus"],
    provider_class=CitusProvider,
    transport="native",
    quirks_class=CitusQuirks,
    config_dialect="postgresql",  # Citus (distributed PostgreSQL) shares PostgreSQL's config class
    sqlalchemy_url_builder=build_sqlalchemy_url,
    native_driver_module="psycopg",
)
