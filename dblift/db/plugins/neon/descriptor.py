"""Discovery metadata for the neon provider."""

from dblift.db.provider_metadata import PluginDescriptor

DESCRIPTOR = PluginDescriptor(
    name="neon",
    dialects=("neon",),
    factory="dblift.db.plugins.neon.plugin:PLUGIN",
)
