"""Entry-point declaration for the MySQL plugin (Epic 26 story 26-12)."""

from __future__ import annotations

from dblift.db.plugins.mysql.config import MySqlConfig
from dblift.db.plugins.mysql.provider import MySqlProvider
from dblift.db.plugins.mysql.quirks import MysqlQuirks
from dblift.db.plugins.mysql.sqlalchemy_url import build_sqlalchemy_url
from dblift.db.provider_registry import PluginInfo

PLUGIN: PluginInfo = PluginInfo(
    name="mysql",
    version="1.0.0",
    description="MySQL database provider",
    dialects=["mysql"],
    provider_class=MySqlProvider,
    transport="native",
    quirks_class=MysqlQuirks,
    config_class=MySqlConfig,
    sqlalchemy_url_builder=build_sqlalchemy_url,
    native_driver_module="pymysql",
    install_extra="mysql",
)
