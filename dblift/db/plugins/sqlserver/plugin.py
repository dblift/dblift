"""Entry-point declaration for the SQL Server plugin (Epic 26 story 26-12)."""

from __future__ import annotations

from dblift.db.plugins.sqlserver.config import SqlServerConfig
from dblift.db.plugins.sqlserver.provider import SqlServerProvider
from dblift.db.plugins.sqlserver.quirks import SqlserverQuirks
from dblift.db.plugins.sqlserver.sqlalchemy_url import build_sqlalchemy_url
from dblift.db.provider_registry import PluginInfo

PLUGIN: PluginInfo = PluginInfo(
    name="sqlserver",
    version="1.0.0",
    description="SQL Server database provider",
    dialects=["sqlserver", "mssql", "tsql", "sql_server"],
    provider_class=SqlServerProvider,
    transport="native",
    quirks_class=SqlserverQuirks,
    config_class=SqlServerConfig,
    sqlalchemy_url_builder=build_sqlalchemy_url,
    native_driver_module="pymssql",
    install_extra="sqlserver",
)
