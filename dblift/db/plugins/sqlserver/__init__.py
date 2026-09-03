"""SQL Server database provider plugin."""

__plugin_name__ = "sqlserver"
__plugin_version__ = "1.0.0"
__plugin_description__ = "SQL Server database provider"
__plugin_dialects__ = ["sqlserver", "mssql", "tsql", "sql_server"]
__plugin_class__ = "SqlServerProvider"

from .provider import SqlServerProvider

__all__ = ["SqlServerProvider"]
