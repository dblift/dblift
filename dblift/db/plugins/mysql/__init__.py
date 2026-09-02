"""MySQL database provider plugin."""

__plugin_name__ = "mysql"
__plugin_version__ = "1.0.0"
__plugin_description__ = "MySQL database provider"
__plugin_dialects__ = ["mysql"]
__plugin_class__ = "MySqlProvider"

from .provider import MySqlProvider

__all__ = ["MySqlProvider"]
