"""Entry-point declaration for the Google AlloyDB for PostgreSQL plugin.

Google AlloyDB for PostgreSQL is wire-compatible with PostgreSQL: this plugin reuses PostgreSQL's
config class (``config_dialect="postgresql"``), SQLAlchemy URL builder, and
``psycopg`` driver, attaching only a distinct identity + quirks subclass. Users
keep their ``postgresql://`` connection string and select this engine via
``type: alloydb``.
"""

from __future__ import annotations

from db.plugins.alloydb.provider import AlloydbProvider
from db.plugins.alloydb.quirks import AlloydbQuirks
from db.plugins.postgresql.sqlalchemy_url import build_sqlalchemy_url
from db.provider_registry import PluginInfo

PLUGIN: PluginInfo = PluginInfo(
    name="alloydb",
    version="1.0.0",
    description="Google AlloyDB for PostgreSQL database provider",
    dialects=["alloydb"],
    provider_class=AlloydbProvider,
    transport="native",
    quirks_class=AlloydbQuirks,
    config_dialect="postgresql",  # Google AlloyDB for PostgreSQL shares PostgreSQL's config class
    sqlalchemy_url_builder=build_sqlalchemy_url,
    native_driver_module="psycopg",
)
