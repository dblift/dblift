"""Lock tables created by earlier dblift versions keep working under the lease.

Earlier versions created the lock table without an owner column and never
refreshed the lock timestamp. Upgrading must add the column in place, and a
row written by an earlier version (no owner) must not be treated as a dead
lease after the short lease expiry — it may belong to an older dblift that is
still migrating. Such rows are reclaimable after 24 hours, the stale-lock rule
SQLite already applied.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import yaml

from dblift.api.client import DBLiftClient

pytestmark = [pytest.mark.unit]

_SQLITE_LEGACY_TABLE = """
    CREATE TABLE "dblift_migration_lock" (
        lock_name TEXT NOT NULL PRIMARY KEY,
        acquired_at TEXT DEFAULT (datetime('now')) NOT NULL,
        acquired_by TEXT NOT NULL,
        process_id TEXT,
        lock_mode INTEGER DEFAULT 1 NOT NULL
    )
"""


def _sqlite_client(tmp_path: Path, legacy_row_age_hours: float | None):
    db_file = tmp_path / "app.db"
    with sqlite3.connect(db_file) as conn:
        conn.execute(_SQLITE_LEGACY_TABLE)
        if legacy_row_age_hours is not None:
            conn.execute(
                "INSERT INTO dblift_migration_lock (lock_name, acquired_at, acquired_by, "
                "process_id) VALUES ('dblift_migration_lock_main', "
                "datetime('now', ?), 'old@host', '1')",
                [f"-{legacy_row_age_hours * 3600:.0f} seconds"],
            )
    config = tmp_path / "dblift.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "database": {"type": "sqlite", "path": str(db_file)},
                "migrations": {"directory": str(tmp_path)},
            }
        )
    )
    return DBLiftClient.from_config_file(str(config)), db_file


def _columns(db_file: Path) -> list[str]:
    with sqlite3.connect(db_file) as conn:
        return [row[1] for row in conn.execute('PRAGMA table_info("dblift_migration_lock")')]


def test_sqlite_legacy_lock_table_gains_owner_column(tmp_path):
    client, db_file = _sqlite_client(tmp_path, legacy_row_age_hours=None)
    try:
        schema = client.config.database.schema
        assert client.provider.acquire_migration_lock(schema, wait_timeout_seconds=2) is True
        assert "owner_token" in _columns(db_file)
        with sqlite3.connect(db_file) as conn:
            (owner,) = conn.execute("SELECT owner_token FROM dblift_migration_lock").fetchone()
        assert owner
        assert client.provider.release_migration_lock(schema) is True
    finally:
        client.close()


def test_sqlite_recent_legacy_lock_row_is_not_reclaimed(tmp_path):
    client, _ = _sqlite_client(tmp_path, legacy_row_age_hours=2)
    try:
        schema = client.config.database.schema
        assert client.provider.acquire_migration_lock(schema, wait_timeout_seconds=2) is False
    finally:
        client.close()


def test_sqlite_day_old_legacy_lock_row_is_reclaimed(tmp_path):
    client, _ = _sqlite_client(tmp_path, legacy_row_age_hours=25)
    try:
        schema = client.config.database.schema
        assert client.provider.acquire_migration_lock(schema, wait_timeout_seconds=5) is True
        assert client.provider.release_migration_lock(schema) is True
    finally:
        client.close()


def _duckdb_client(tmp_path: Path, legacy_row_age_hours: float | None):
    duckdb = pytest.importorskip("duckdb")
    pytest.importorskip("duckdb_engine")
    db_file = tmp_path / "app.duckdb"
    conn = duckdb.connect(str(db_file))
    try:
        conn.execute("""
            CREATE TABLE main.dblift_migration_lock (
                lock_name VARCHAR PRIMARY KEY,
                locked_at TIMESTAMP DEFAULT now()
            )
            """)
        if legacy_row_age_hours is not None:
            conn.execute(
                "INSERT INTO main.dblift_migration_lock VALUES "
                f"('migration', CAST(now() AS TIMESTAMP) - INTERVAL {legacy_row_age_hours} HOUR)"
            )
    finally:
        conn.close()
    config = tmp_path / "dblift.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "database": {"type": "duckdb", "url": f"duckdb:///{db_file}"},
                "migrations": {"directory": str(tmp_path)},
            }
        )
    )
    return DBLiftClient.from_config_file(str(config)), db_file


def test_duckdb_legacy_lock_table_gains_owner_column(tmp_path):
    client, _ = _duckdb_client(tmp_path, legacy_row_age_hours=None)
    try:
        schema = client.config.database.schema
        assert client.provider.acquire_migration_lock(schema, wait_timeout_seconds=2) is True
        rows = client.provider.execute_query(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'dblift_migration_lock'"
        )
        assert "owner_token" in {str(row["column_name"]).lower() for row in rows}
        assert client.provider.release_migration_lock(schema) is True
    finally:
        client.close()


def test_duckdb_recent_legacy_lock_row_is_not_reclaimed(tmp_path):
    client, _ = _duckdb_client(tmp_path, legacy_row_age_hours=2)
    try:
        schema = client.config.database.schema
        assert client.provider.acquire_migration_lock(schema, wait_timeout_seconds=2) is False
    finally:
        client.close()


def test_duckdb_day_old_legacy_lock_row_is_reclaimed(tmp_path):
    client, _ = _duckdb_client(tmp_path, legacy_row_age_hours=25)
    try:
        schema = client.config.database.schema
        assert client.provider.acquire_migration_lock(schema, wait_timeout_seconds=5) is True
        assert client.provider.release_migration_lock(schema) is True
    finally:
        client.close()


def test_sqlite_lease_uses_the_utc_clock_of_the_database_host(tmp_path):
    """The lease timestamp is SQLite's own UTC clock, whatever the time zone
    of the process that wrote it, and no lease statement binds a client
    timestamp."""
    import subprocess
    import sys
    import textwrap
    from datetime import datetime, timezone

    client, db_file = _sqlite_client(tmp_path, legacy_row_age_hours=None)
    client.close()
    script = textwrap.dedent("""
        import re, sqlite3, sys
        traced = []
        real_connect = sqlite3.connect
        def connect(*args, **kwargs):
            conn = real_connect(*args, **kwargs)
            conn.set_trace_callback(traced.append)
            return conn
        sqlite3.connect = connect
        from dblift.api.client import DBLiftClient
        client = DBLiftClient.from_config_file(sys.argv[1])
        schema = client.config.database.schema
        assert client.provider.acquire_migration_lock(schema, 2)
        with real_connect(sys.argv[2]) as conn:
            print("STORED", conn.execute("SELECT acquired_at FROM dblift_migration_lock").fetchone()[0])
        client.provider.release_migration_lock(schema)
        client.close()
        for sql in traced:
            if "dblift_migration_lock" in sql and re.search(r"'\\d{4}-\\d{2}-\\d{2}", sql):
                print("CLIENT-TIMESTAMP", sql)
            if "dblift_migration_lock" in sql and "localtime" in sql.lower():
                print("LOCALTIME", sql)
        """)
    env = {**__import__("os").environ, "TZ": "Pacific/Kiritimati"}  # UTC+14
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "dblift.yaml"), str(db_file)],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "CLIENT-TIMESTAMP" not in result.stdout, result.stdout
    assert "LOCALTIME" not in result.stdout, result.stdout
    stored = result.stdout.split("STORED ", 1)[1].splitlines()[0].strip()
    written = datetime.fromisoformat(stored).replace(tzinfo=timezone.utc)
    assert abs((datetime.now(timezone.utc) - written).total_seconds()) < 60
