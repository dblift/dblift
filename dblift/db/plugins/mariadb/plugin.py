"""Entry-point declaration for the MariaDB plugin (Epic 26 story 26-13)."""

from __future__ import annotations

from dblift.db.plugins.mariadb.provider import MariadbProvider
from dblift.db.plugins.mariadb.quirks import MariadbQuirks
from dblift.db.plugins.mysql.sqlalchemy_url import build_sqlalchemy_url
from dblift.db.provider_registry import PluginInfo

PLUGIN: PluginInfo = PluginInfo(
    name="mariadb",
    version="1.0.0",
    description="MariaDB database provider",
    dialects=["mariadb"],
    provider_class=MariadbProvider,
    transport="native",
    quirks_class=MariadbQuirks,
    config_dialect="mysql",  # MariaDB shares MySQL's config class
    sqlalchemy_url_builder=build_sqlalchemy_url,
    native_driver_module="pymysql",
    install_extra="mariadb",
)
