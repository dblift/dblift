"""Discovery metadata for the cockroachdb provider."""

from dblift.db.provider_metadata import PluginDescriptor

DESCRIPTOR = PluginDescriptor(
    name="cockroachdb",
    dialects=("cockroachdb",),
    factory="dblift.db.plugins.cockroachdb.plugin:PLUGIN",
)
