"""Entry-point declaration for the yugabytedb plugin.

This engine is wire-compatible with PostgreSQL, so it reuses PostgreSQL's
provider, config, SQLAlchemy URL builder, and ``psycopg`` driver through the
shared factory in :mod:`db.plugins._pg_compatible`, attaching only a distinct
dialect identity. Users keep their ``postgresql://`` connection string and
select this engine via ``type: yugabytedb``.
"""

from __future__ import annotations

from db.plugins._pg_compatible import make_pg_compatible_plugin
from db.provider_registry import PluginInfo

PLUGIN: PluginInfo = make_pg_compatible_plugin(
    "yugabytedb",
    "YugabyteDB (PostgreSQL-compatible) database provider",
    # YSQL auto-commits DDL (like Oracle/MySQL): a rolled-back migration
    # still leaves CREATE TABLE objects behind. Do not inherit PostgreSQL's
    # transactional-DDL claim.
    quirks_overrides={"supports_transactional_ddl": False},
)
