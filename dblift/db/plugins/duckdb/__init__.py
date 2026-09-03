"""DuckDB database provider plugin."""

__plugin_name__ = "duckdb"
__plugin_version__ = "1.0.0"
__plugin_description__ = "DuckDB database provider (SQLAlchemy via duckdb_engine)"
__plugin_dialects__ = ["duckdb"]
__plugin_transport__ = "native"
__plugin_class__ = "DuckDBProvider"

from .provider import DuckDBProvider

__all__ = ["DuckDBProvider"]
