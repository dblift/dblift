"""Amazon Aurora PostgreSQL database provider plugin (PostgreSQL-compatible)."""

__plugin_name__ = "aurora-postgresql"
__plugin_version__ = "1.0.0"
__plugin_description__ = "Amazon Aurora PostgreSQL database provider"
__plugin_dialects__ = ["aurora-postgresql"]
__plugin_transport__ = "native"
__plugin_class__ = "AuroraPostgresqlProvider"

from .provider import AuroraPostgresqlProvider

__all__ = ["AuroraPostgresqlProvider"]
