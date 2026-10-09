"""Discovery metadata for the duckdb provider."""

from dblift.db.provider_metadata import PluginDescriptor

DESCRIPTOR = PluginDescriptor(
    name="duckdb",
    dialects=("duckdb",),
    factory="dblift.db.plugins.duckdb.plugin:PLUGIN",
)
