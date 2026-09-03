"""SQLite database provider plugin."""

__plugin_name__ = "sqlite"
__plugin_version__ = "1.0.0"
__plugin_description__ = "SQLite database provider (native Python sqlite3)"
__plugin_dialects__ = ["sqlite", "sqlite3"]
__plugin_transport__ = "native"
__plugin_class__ = "SQLiteProvider"

from .provider import SQLiteProvider

__all__ = ["SQLiteProvider"]
