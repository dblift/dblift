"""Discovery metadata for the yugabytedb provider."""

from dblift.db.provider_metadata import PluginDescriptor

DESCRIPTOR = PluginDescriptor(
    name="yugabytedb",
    dialects=("yugabytedb",),
    factory="dblift.db.plugins.yugabytedb.plugin:PLUGIN",
)
