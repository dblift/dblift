"""Citus (distributed PostgreSQL) database provider plugin (PostgreSQL-compatible)."""

__plugin_name__ = "citus"
__plugin_version__ = "1.0.0"
__plugin_description__ = "Citus (distributed PostgreSQL) database provider"
__plugin_dialects__ = ["citus"]
__plugin_transport__ = "native"
__plugin_class__ = "CitusProvider"

from .provider import CitusProvider

__all__ = ["CitusProvider"]
