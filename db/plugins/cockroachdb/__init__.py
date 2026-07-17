"""CockroachDB database provider plugin (PostgreSQL-compatible)."""

__plugin_name__ = "cockroachdb"
__plugin_version__ = "1.0.0"
__plugin_description__ = "CockroachDB database provider"
__plugin_dialects__ = ["cockroachdb"]
__plugin_transport__ = "native"
__plugin_class__ = "CockroachdbProvider"

from .provider import CockroachdbProvider

__all__ = ["CockroachdbProvider"]
