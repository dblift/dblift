"""Discovery metadata for the mariadb provider."""

from dblift.db.provider_metadata import PluginDescriptor

DESCRIPTOR = PluginDescriptor(
    name="mariadb",
    dialects=("mariadb",),
    factory="dblift.db.plugins.mariadb.plugin:PLUGIN",
)
