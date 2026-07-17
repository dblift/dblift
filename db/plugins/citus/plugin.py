"""Entry-point declaration for the citus plugin.

This engine is wire-compatible with PostgreSQL, so it reuses PostgreSQL's
provider, config, SQLAlchemy URL builder, and ``psycopg`` driver through the
shared factory in :mod:`db.plugins._pg_compatible`, attaching only a distinct
dialect identity. Users keep their ``postgresql://`` connection string and
select this engine via ``type: citus``.
"""

from __future__ import annotations

from db.plugins._pg_compatible import make_pg_compatible_plugin
from db.provider_registry import PluginInfo

PLUGIN: PluginInfo = make_pg_compatible_plugin(
    "citus",
    "Citus (distributed PostgreSQL) database provider",
)
