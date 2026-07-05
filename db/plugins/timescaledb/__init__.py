"""TimescaleDB (PostgreSQL extension) database provider plugin (PostgreSQL-compatible)."""

__plugin_name__ = "timescaledb"
__plugin_version__ = "1.0.0"
__plugin_description__ = "TimescaleDB (PostgreSQL extension) database provider"
__plugin_dialects__ = ["timescaledb"]
__plugin_transport__ = "native"
__plugin_class__ = "TimescaledbProvider"

from .provider import TimescaledbProvider

__all__ = ["TimescaledbProvider"]
