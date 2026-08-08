"""Entry-point declaration for the timescaledb plugin.

This engine is wire-compatible with PostgreSQL, so it reuses PostgreSQL's
provider, config, SQLAlchemy URL builder, and ``psycopg`` driver through the
shared factory in :mod:`db.plugins._pg_compatible`, attaching only a distinct
dialect identity. Users keep their ``postgresql://`` connection string and
select this engine via ``type: timescaledb``.
"""

from __future__ import annotations

from db.plugins._pg_compatible import make_pg_compatible_plugin
from db.provider_registry import PluginInfo

PLUGIN: PluginInfo = make_pg_compatible_plugin(
    "timescaledb",
    "TimescaleDB (PostgreSQL extension) database provider",
    # TimescaleDB does not support CREATE INDEX CONCURRENTLY directly on a
    # hypertable (confirmed against Tiger Data's own CREATE INDEX reference,
    # current as of 2026-08). The documented alternative for a non-blocking
    # build is a different clause entirely --
    # ``WITH (timescaledb.transaction_per_chunk)`` -- not CONCURRENTLY.
    # Inheriting PostgreSQL's ``True`` here would recommend syntax this
    # engine doesn't support for the case it's meant to help.
    quirks_overrides={"supports_concurrent_index": False},
)
