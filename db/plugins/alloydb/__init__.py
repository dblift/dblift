"""Google AlloyDB for PostgreSQL database provider plugin (PostgreSQL-compatible)."""

__plugin_name__ = "alloydb"
__plugin_version__ = "1.0.0"
__plugin_description__ = "Google AlloyDB for PostgreSQL database provider"
__plugin_dialects__ = ["alloydb"]
__plugin_transport__ = "native"
__plugin_class__ = "AlloydbProvider"

from .provider import AlloydbProvider

__all__ = ["AlloydbProvider"]
