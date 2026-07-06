"""Neon (serverless PostgreSQL) database provider plugin (PostgreSQL-compatible)."""

__plugin_name__ = "neon"
__plugin_version__ = "1.0.0"
__plugin_description__ = "Neon (serverless PostgreSQL) database provider"
__plugin_dialects__ = ["neon"]
__plugin_transport__ = "native"
__plugin_class__ = "NeonProvider"

from .provider import NeonProvider

__all__ = ["NeonProvider"]
