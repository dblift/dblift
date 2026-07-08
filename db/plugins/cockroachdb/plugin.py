"""Entry-point declaration for the CockroachDB plugin.

CockroachDB is PostgreSQL-compatible: this plugin reuses PostgreSQL's config
class (``config_dialect="postgresql"``), SQLAlchemy URL builder, and
``psycopg`` driver, attaching only a distinct identity + quirks subclass. Users
keep their ``postgresql://`` connection string and select this engine via
``type: cockroachdb``.
"""

from __future__ import annotations

from db.plugins.cockroachdb.provider import CockroachdbProvider
from db.plugins.cockroachdb.quirks import CockroachdbQuirks
from db.plugins.postgresql.sqlalchemy_url import build_sqlalchemy_url
from db.provider_registry import PluginInfo

PLUGIN: PluginInfo = PluginInfo(
    name="cockroachdb",
    version="1.0.0",
    description="CockroachDB database provider",
    dialects=["cockroachdb"],
    provider_class=CockroachdbProvider,
    transport="native",
    quirks_class=CockroachdbQuirks,
    config_dialect="postgresql",
    sqlalchemy_url_builder=build_sqlalchemy_url,
    native_driver_module="psycopg",
)
