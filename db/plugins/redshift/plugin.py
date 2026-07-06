"""Entry-point declaration for the Redshift plugin.

Redshift is PostgreSQL-compatible: this plugin reuses PostgreSQL's config
class (``config_dialect="postgresql"``), SQLAlchemy URL builder, and
``psycopg`` driver, attaching only a distinct identity + quirks subclass. Users
keep their ``postgresql://`` connection string and select this engine via
``type: redshift``.
"""

from __future__ import annotations

from db.plugins.postgresql.sqlalchemy_url import build_sqlalchemy_url
from db.plugins.redshift.provider import RedshiftProvider
from db.plugins.redshift.quirks import RedshiftQuirks
from db.provider_registry import PluginInfo

PLUGIN: PluginInfo = PluginInfo(
    name="redshift",
    version="1.0.0",
    description="Redshift database provider",
    dialects=["redshift"],
    provider_class=RedshiftProvider,
    transport="native",
    quirks_class=RedshiftQuirks,
    config_dialect="postgresql",
    sqlalchemy_url_builder=build_sqlalchemy_url,
    native_driver_module="psycopg",
)
