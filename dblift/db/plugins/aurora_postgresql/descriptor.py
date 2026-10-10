"""Discovery metadata for the aurora-postgresql provider."""

from dblift.db.provider_metadata import PluginDescriptor

DESCRIPTOR = PluginDescriptor(
    name="aurora-postgresql",
    dialects=("aurora-postgresql",),
    factory="dblift.db.plugins.aurora_postgresql.plugin:PLUGIN",
)
