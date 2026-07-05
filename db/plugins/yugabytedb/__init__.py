"""YugabyteDB (PostgreSQL-compatible) database provider plugin (PostgreSQL-compatible)."""

__plugin_name__ = "yugabytedb"
__plugin_version__ = "1.0.0"
__plugin_description__ = "YugabyteDB (PostgreSQL-compatible) database provider"
__plugin_dialects__ = ["yugabytedb"]
__plugin_transport__ = "native"
__plugin_class__ = "YugabytedbProvider"

from .provider import YugabytedbProvider

__all__ = ["YugabytedbProvider"]
