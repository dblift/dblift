"""Discovery metadata for the redshift provider."""

from dblift.db.provider_metadata import PluginDescriptor

DESCRIPTOR = PluginDescriptor(
    name="redshift",
    dialects=("redshift",),
    factory="dblift.db.plugins.redshift.plugin:PLUGIN",
)
