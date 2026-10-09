"""Discovery metadata for the oracle provider."""

from dblift.db.provider_metadata import PluginDescriptor

DESCRIPTOR = PluginDescriptor(
    name="oracle",
    dialects=("oracle",),
    factory="dblift.db.plugins.oracle.plugin:PLUGIN",
)
