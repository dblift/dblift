"""Discovery metadata for the db2 provider."""

from dblift.db.provider_metadata import PluginDescriptor

DESCRIPTOR = PluginDescriptor(
    name="db2",
    dialects=("db2", "ibm_db_sa"),
    factory="dblift.db.plugins.db2.plugin:PLUGIN",
)
