"""Discovery metadata for the timescaledb provider."""

from dblift.db.provider_metadata import PluginDescriptor

DESCRIPTOR = PluginDescriptor(
    name="timescaledb",
    dialects=("timescaledb",),
    factory="dblift.db.plugins.timescaledb.plugin:PLUGIN",
)
