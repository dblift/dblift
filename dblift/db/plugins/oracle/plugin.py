"""Entry-point declaration for the Oracle plugin (Epic 26 story 26-12)."""

from __future__ import annotations

from dblift.db.plugins.oracle.config import OracleConfig
from dblift.db.plugins.oracle.provider import OracleProvider
from dblift.db.plugins.oracle.quirks import OracleQuirks
from dblift.db.plugins.oracle.sqlalchemy_url import build_sqlalchemy_url
from dblift.db.provider_registry import PluginInfo

PLUGIN: PluginInfo = PluginInfo(
    name="oracle",
    version="1.0.0",
    description="Oracle database provider",
    dialects=["oracle"],
    provider_class=OracleProvider,
    transport="native",
    quirks_class=OracleQuirks,
    config_class=OracleConfig,
    sqlalchemy_url_builder=build_sqlalchemy_url,
    native_driver_module="oracledb",
    install_extra="oracle",
)
