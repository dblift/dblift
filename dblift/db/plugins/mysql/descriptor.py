"""Discovery metadata for the mysql provider."""

from dblift.db.provider_metadata import PluginDescriptor

DESCRIPTOR = PluginDescriptor(
    name="mysql",
    dialects=("mysql",),
    factory="dblift.db.plugins.mysql.plugin:PLUGIN",
)
