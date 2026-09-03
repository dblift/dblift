"""CockroachDB database provider plugin (PostgreSQL-compatible)."""

# Side-effect import: register the SQLAlchemy dialect so create_engine can
# resolve cockroachdb+psycopg even if plugin.py was not loaded yet.
from dblift.db.plugins.cockroachdb.sqlalchemy_dialect import (  # noqa: F401
    register_cockroach_dialect,
)

register_cockroach_dialect()

__plugin_name__ = "cockroachdb"
__plugin_version__ = "1.0.0"
__plugin_description__ = "CockroachDB database provider"
__plugin_dialects__ = ["cockroachdb"]
__plugin_transport__ = "native"
__plugin_class__ = "CockroachdbProvider"

from .provider import CockroachdbProvider

__all__ = ["CockroachdbProvider"]
