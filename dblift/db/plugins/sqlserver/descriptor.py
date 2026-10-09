"""Discovery metadata for the sqlserver provider."""

from dblift.db.provider_metadata import PluginDescriptor

DESCRIPTOR = PluginDescriptor(
    name="sqlserver",
    dialects=("sqlserver", "mssql", "tsql", "sql_server"),
    factory="dblift.db.plugins.sqlserver.plugin:PLUGIN",
)
