"""PostgreSQL database provider plugin."""

__plugin_name__ = "postgresql"
__plugin_version__ = "1.0.0"
__plugin_description__ = "PostgreSQL database provider"
__plugin_dialects__ = ["postgresql", "postgres"]
__plugin_transport__ = "native"
__plugin_class__ = "PostgreSqlProvider"

from .provider import PostgreSqlProvider

__all__ = ["PostgreSqlProvider"]
