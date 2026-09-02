"""Entry-point declaration for the Snowflake plugin."""

from __future__ import annotations

from dblift.db.plugins.snowflake.config import SnowflakeConfig
from dblift.db.plugins.snowflake.provider import SnowflakeProvider
from dblift.db.plugins.snowflake.quirks import SnowflakeQuirks
from dblift.db.plugins.snowflake.sqlalchemy_url import build_sqlalchemy_url
from dblift.db.provider_registry import PluginInfo

PLUGIN: PluginInfo = PluginInfo(
    name="snowflake",
    version="1.0.0",
    description="Snowflake database provider",
    dialects=["snowflake"],
    provider_class=SnowflakeProvider,
    transport="native",
    quirks_class=SnowflakeQuirks,
    config_class=SnowflakeConfig,
    sqlalchemy_url_builder=build_sqlalchemy_url,
    native_driver_module="snowflake.connector",
    install_extra="snowflake",
)
