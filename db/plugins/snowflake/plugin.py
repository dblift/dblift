"""Entry-point declaration for the Snowflake plugin."""

from __future__ import annotations

from db.plugins.snowflake.config import SnowflakeConfig
from db.plugins.snowflake.provider import SnowflakeProvider
from db.plugins.snowflake.quirks import SnowflakeQuirks
from db.plugins.snowflake.sqlalchemy_url import build_sqlalchemy_url
from db.provider_registry import PluginInfo

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
)
