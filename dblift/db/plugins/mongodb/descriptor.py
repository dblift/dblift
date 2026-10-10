"""Discovery metadata for the mongodb provider."""

from dblift.db.provider_metadata import PluginDescriptor

DESCRIPTOR = PluginDescriptor(
    name="mongodb",
    dialects=("mongodb", "mongo"),
    factory="dblift.db.plugins.mongodb.plugin:PLUGIN",
)
