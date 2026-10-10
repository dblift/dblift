"""Discovery metadata for the alloydb provider."""

from dblift.db.provider_metadata import PluginDescriptor

DESCRIPTOR = PluginDescriptor(
    name="alloydb",
    dialects=("alloydb",),
    factory="dblift.db.plugins.alloydb.plugin:PLUGIN",
)
