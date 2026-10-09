"""Discovery metadata for the sqlite provider."""

from dblift.db.provider_metadata import PluginDescriptor

DESCRIPTOR = PluginDescriptor(
    name="sqlite",
    dialects=("sqlite", "sqlite3"),
    factory="dblift.db.plugins.sqlite.plugin:PLUGIN",
)
