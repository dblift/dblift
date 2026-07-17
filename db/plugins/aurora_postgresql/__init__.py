"""Amazon Aurora PostgreSQL database provider plugin package (PostgreSQL-compatible).

The provider and quirks classes are built by the shared factory invoked in
``plugin.py`` (:mod:`db.plugins._pg_compatible`); this package intentionally
ships no ``provider.py`` / ``quirks.py``.
"""

__plugin_name__ = "aurora-postgresql"
__plugin_version__ = "1.0.0"
__plugin_description__ = "Amazon Aurora PostgreSQL database provider"
__plugin_dialects__ = ["aurora-postgresql"]
__plugin_transport__ = "native"
