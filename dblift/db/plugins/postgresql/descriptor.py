"""Discovery metadata for the postgresql provider."""

from dblift.db.provider_metadata import PluginDescriptor

DESCRIPTOR = PluginDescriptor(
    name="postgresql",
    dialects=("postgresql", "postgres"),
    factory="dblift.db.plugins.postgresql.plugin:PLUGIN",
)
