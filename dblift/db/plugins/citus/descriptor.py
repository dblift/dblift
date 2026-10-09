"""Discovery metadata for the citus provider."""

from dblift.db.provider_metadata import PluginDescriptor

DESCRIPTOR = PluginDescriptor(
    name="citus",
    dialects=("citus",),
    factory="dblift.db.plugins.citus.plugin:PLUGIN",
)
