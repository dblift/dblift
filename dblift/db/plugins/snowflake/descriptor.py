"""Discovery metadata for the snowflake provider."""

from dblift.db.provider_metadata import PluginDescriptor

DESCRIPTOR = PluginDescriptor(
    name="snowflake",
    dialects=("snowflake",),
    factory="dblift.db.plugins.snowflake.plugin:PLUGIN",
)
