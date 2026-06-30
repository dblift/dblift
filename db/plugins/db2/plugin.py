"""Entry-point declaration for the DB2 plugin (Epic 26 story 26-12)."""

from __future__ import annotations

from db.plugins.db2.config import Db2Config
from db.plugins.db2.provider import Db2Provider
from db.plugins.db2.quirks import Db2Quirks
from db.plugins.db2.sqlalchemy_url import build_sqlalchemy_url
from db.provider_registry import PluginInfo

PLUGIN: PluginInfo = PluginInfo(
    name="db2",
    version="1.0.0",
    description="DB2 database provider",
    dialects=["db2", "ibm_db_sa"],
    provider_class=Db2Provider,
    transport="native",
    quirks_class=Db2Quirks,
    config_class=Db2Config,
    sqlalchemy_url_builder=build_sqlalchemy_url,
    native_driver_module="ibm_db_sa",
)
