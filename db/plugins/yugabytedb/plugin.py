"""Entry-point declaration for the YugabyteDB (PostgreSQL-compatible) plugin.

YugabyteDB (PostgreSQL-compatible) is wire-compatible with PostgreSQL: this plugin reuses PostgreSQL's
config class (``config_dialect="postgresql"``), SQLAlchemy URL builder, and
``psycopg`` driver, attaching only a distinct identity + quirks subclass. Users
keep their ``postgresql://`` connection string and select this engine via
``type: yugabytedb``.
"""

from __future__ import annotations

from db.plugins.postgresql.sqlalchemy_url import build_sqlalchemy_url
from db.plugins.yugabytedb.provider import YugabytedbProvider
from db.plugins.yugabytedb.quirks import YugabytedbQuirks
from db.provider_registry import PluginInfo

PLUGIN: PluginInfo = PluginInfo(
    name="yugabytedb",
    version="1.0.0",
    description="YugabyteDB (PostgreSQL-compatible) database provider",
    dialects=["yugabytedb"],
    provider_class=YugabytedbProvider,
    transport="native",
    quirks_class=YugabytedbQuirks,
    config_dialect="postgresql",  # YugabyteDB (PostgreSQL-compatible) shares PostgreSQL's config class
    sqlalchemy_url_builder=build_sqlalchemy_url,
    native_driver_module="psycopg",
)
