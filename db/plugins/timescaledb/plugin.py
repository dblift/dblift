"""Entry-point declaration for the TimescaleDB (PostgreSQL extension) plugin.

TimescaleDB (PostgreSQL extension) is wire-compatible with PostgreSQL: this plugin reuses PostgreSQL's
config class (``config_dialect="postgresql"``), SQLAlchemy URL builder, and
``psycopg`` driver, attaching only a distinct identity + quirks subclass. Users
keep their ``postgresql://`` connection string and select this engine via
``type: timescaledb``.
"""

from __future__ import annotations

from db.plugins.postgresql.sqlalchemy_url import build_sqlalchemy_url
from db.plugins.timescaledb.provider import TimescaledbProvider
from db.plugins.timescaledb.quirks import TimescaledbQuirks
from db.provider_registry import PluginInfo

PLUGIN: PluginInfo = PluginInfo(
    name="timescaledb",
    version="1.0.0",
    description="TimescaleDB (PostgreSQL extension) database provider",
    dialects=["timescaledb"],
    provider_class=TimescaledbProvider,
    transport="native",
    quirks_class=TimescaledbQuirks,
    config_dialect="postgresql",  # TimescaleDB (PostgreSQL extension) shares PostgreSQL's config class
    sqlalchemy_url_builder=build_sqlalchemy_url,
    native_driver_module="psycopg",
)
