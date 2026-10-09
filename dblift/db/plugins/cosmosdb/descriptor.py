"""Discovery metadata for the cosmosdb provider."""

from dblift.db.provider_metadata import PluginDescriptor

DESCRIPTOR = PluginDescriptor(
    name="cosmosdb",
    dialects=("cosmosdb", "cosmos", "nosql"),
    factory="dblift.db.plugins.cosmosdb.plugin:PLUGIN",
)
