"""Snowflake database provider plugin."""

__plugin_name__ = "snowflake"
__plugin_version__ = "1.0.0"
__plugin_description__ = "Snowflake database provider"
__plugin_dialects__ = ["snowflake"]
__plugin_transport__ = "native"
__plugin_class__ = "SnowflakeProvider"

from .provider import SnowflakeProvider

__all__ = ["SnowflakeProvider"]
