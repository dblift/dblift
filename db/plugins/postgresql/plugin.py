"""Entry-point declaration for the PostgreSQL plugin (Epic 26 story 26-12).

The :class:`PluginInfo` constant exported by this module is registered
through the ``dblift.providers`` entry-point group in ``pyproject.toml``.
``ProviderRegistry.discover_plugins`` reads it via
``importlib.metadata.entry_points`` so first-party and third-party
plugins are discovered through the same mechanism.
"""

from __future__ import annotations

from db.plugins.postgresql.config import PostgreSqlConfig
from db.plugins.postgresql.provider import PostgreSqlProvider
from db.plugins.postgresql.quirks import PostgresqlQuirks
from db.plugins.postgresql.sqlalchemy_url import build_sqlalchemy_url
from db.provider_registry import PluginInfo

PLUGIN: PluginInfo = PluginInfo(
    name="postgresql",
    version="1.0.0",
    description="PostgreSQL database provider",
    dialects=["postgresql", "postgres"],
    provider_class=PostgreSqlProvider,
    transport="native",
    quirks_class=PostgresqlQuirks,
    config_class=PostgreSqlConfig,
    sqlalchemy_url_builder=build_sqlalchemy_url,
    native_driver_module="psycopg",
)
