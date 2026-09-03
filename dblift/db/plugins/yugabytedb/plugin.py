"""Entry-point declaration for the yugabytedb plugin.

This engine is wire-compatible with PostgreSQL, so it reuses PostgreSQL's
provider, config, SQLAlchemy URL builder, and ``psycopg`` driver through the
shared factory in :mod:`dblift.db.plugins._pg_compatible`, attaching only a distinct
dialect identity. Users keep their ``postgresql://`` connection string and
select this engine via ``type: yugabytedb``.
"""

from __future__ import annotations

from dblift.db.plugins._pg_compatible import make_pg_compatible_plugin
from dblift.db.provider_registry import PluginInfo

PLUGIN: PluginInfo = make_pg_compatible_plugin(
    "yugabytedb",
    "YugabyteDB (PostgreSQL-compatible) database provider",
    quirks_overrides={
        # YSQL auto-commits DDL (like Oracle/MySQL): a rolled-back migration
        # still leaves CREATE TABLE objects behind. Do not inherit
        # PostgreSQL's transactional-DDL claim.
        "supports_transactional_ddl": False,
        # YugabyteDB's own CREATE INDEX reference: "the default mode is
        # CONCURRENTLY, wherever possible" -- online index backfill is
        # already the default, and NONCONCURRENTLY is the actual opt-out
        # for restricted/blocking behavior. Inheriting PostgreSQL's
        # ``True`` here has it backwards: it would recommend explicitly
        # requesting what YugabyteDB already gives you, as though the
        # plain form were the blocking one.
        "supports_concurrent_index": False,
    },
)
