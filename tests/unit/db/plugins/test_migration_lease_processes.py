"""Orphaned migration locks are reclaimed; live ones are not (real processes).

A ``migrate`` process killed with SIGKILL never reaches the ``finally`` that
releases the migration lock. Before the lease, SQLite and DuckDB kept that
lock row until someone deleted it by hand: every later ``migrate`` waited the
full lock timeout and failed. These tests run real ``dblift`` processes
against real SQLite / DuckDB files, with the lease expiry shortened so each
test stays within a few seconds of one lease window.
"""

from __future__ import annotations

import importlib.util
import os
import signal
import sqlite3
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
EXPIRY = 2.0

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(os.name != "posix", reason="uses POSIX signals"),
]

# Runs ``dblift migrate`` with a short lease so a reclaim fits in a test.
_MIGRATE = textwrap.dedent("""
    import sys
    try:
        import dblift.db.plugins.lease_lock as lease
        lease.LEASE_EXPIRY_SECONDS = float(sys.argv[1])
    except ImportError:  # dblift without the lease: run unchanged
        pass
    sys.argv = ["dblift", "--config", sys.argv[2], "migrate"]
    from dblift.cli.main import main
    sys.exit(main())
    """)

# Takes the migration lock through the public provider API, then behaves as
# told by ``mode``: ``sleep`` holds until killed; ``long-write`` holds a write
# transaction for three lease windows (a long migration), keeps the lock two
# more windows, then releases; ``wait-stdin`` holds until a line on stdin, then
# reports whether the lease was lost and whether its release removed anything.
_HOLDER = textwrap.dedent("""
    import sqlite3, sys, time
    expiry = float(sys.argv[1])
    try:
        import dblift.db.plugins.lease_lock as lease
        lease.LEASE_EXPIRY_SECONDS = expiry
    except ImportError:  # dblift without the lease: run unchanged
        pass
    from dblift.api.client import DBLiftClient
    client = DBLiftClient.from_config_file(sys.argv[2])
    mode, db_path = sys.argv[3], sys.argv[4]
    schema = client.config.database.schema
    provider = client.provider
    if not provider.acquire_migration_lock(schema, wait_timeout_seconds=int(expiry * 6)):
        print("NOT-ACQUIRED", flush=True)
        sys.exit(3)
    print("HELD", flush=True)
    if mode == "sleep":
        while True:
            time.sleep(1)
    if mode == "long-write":
        work = sqlite3.connect(db_path, isolation_level=None)
        work.execute("BEGIN IMMEDIATE")
        work.execute("CREATE TABLE holder_work (x INTEGER)")
        time.sleep(expiry * 3)
        work.execute("COMMIT")
        deadline = time.monotonic() + expiry * 2
        while time.monotonic() < deadline:
            row = work.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 't1'"
            ).fetchone()
            if row:
                print("STOLEN", flush=True)
            time.sleep(0.2)
    if mode == "wait-stdin":
        sys.stdin.readline()
        time.sleep(expiry)
        print("LOST", provider.migration_lock_lost(), flush=True)
    print("RELEASED", provider.release_migration_lock(schema), flush=True)
    client.close()
    """)


def _project(tmp_path: Path, engine: str) -> tuple[Path, Path]:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1__create_t1.sql").write_text("CREATE TABLE t1 (id INTEGER);\n")
    if engine == "sqlite":
        db_file = tmp_path / "app.db"
        database = {"type": "sqlite", "path": str(db_file)}
    else:
        db_file = tmp_path / "app.duckdb"
        database = {"type": "duckdb", "url": f"duckdb:///{db_file}"}
    config = tmp_path / "dblift.yaml"
    config.write_text(
        yaml.safe_dump({"database": database, "migrations": {"directory": str(migrations)}})
    )
    return config, db_file


def _migrate(config: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", _MIGRATE, str(EXPIRY), str(config)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=100,
        check=False,
    )


def _start_holder(config: Path, db_file: Path, mode: str) -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, "-c", _HOLDER, str(EXPIRY), str(config), mode, str(db_file)],
        cwd=REPO_ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    line = proc.stdout.readline().strip()
    if line != "HELD":
        proc.kill()
        out, err = proc.communicate(timeout=10)
        pytest.fail(f"holder did not take the lock: {line!r}\n{out}\n{err}")
    return proc


def _table_exists(engine: str, db_file: Path, table: str) -> bool:
    if engine == "sqlite":
        with sqlite3.connect(db_file) as conn:
            row = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", [table]
            ).fetchone()
        return row is not None
    import duckdb

    conn = duckdb.connect(str(db_file))
    try:
        rows = conn.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name = ?", [table]
        ).fetchall()
    finally:
        conn.close()
    return bool(rows)


@pytest.mark.parametrize("engine", ["sqlite", "duckdb"])
def test_lock_of_a_sigkilled_holder_is_reclaimed_within_one_lease_window(tmp_path, engine):
    if engine == "duckdb":
        pytest.importorskip("duckdb_engine")
    config, db_file = _project(tmp_path, engine)
    holder = _start_holder(config, db_file, "sleep")
    holder.send_signal(signal.SIGKILL)
    holder.wait(timeout=10)

    started = time.monotonic()
    result = _migrate(config)
    elapsed = time.monotonic() - started

    assert result.returncode == 0, result.stdout + result.stderr
    assert _table_exists(engine, db_file, "t1")
    assert elapsed < EXPIRY + 20, f"reclaim took {elapsed:.1f}s"


def test_long_sqlite_write_transaction_of_a_live_holder_is_not_stolen(tmp_path):
    """The holder's own write transaction blocks its heartbeat for three lease
    windows; the waiting ``migrate`` must still not take the lock."""
    config, db_file = _project(tmp_path, "sqlite")
    holder = _start_holder(config, db_file, "long-write")
    time.sleep(0.5)

    result = _migrate(config)
    out, err = holder.communicate(timeout=60)

    assert "STOLEN" not in out, out + err
    assert "RELEASED True" in out, out + err
    assert result.returncode == 0, result.stdout + result.stderr
    assert _table_exists("sqlite", db_file, "t1")


def test_frozen_sqlite_holder_cannot_release_the_lease_that_replaced_it(tmp_path):
    """SIGSTOP stands in for a holder paused longer than the lease (GC, VM
    freeze). Its lease is reclaimed; once resumed it must find the lease lost
    and its release must leave the new holder's lease in place."""
    config, db_file = _project(tmp_path, "sqlite")
    stale = _start_holder(config, db_file, "wait-stdin")
    stale.send_signal(signal.SIGSTOP)
    try:
        time.sleep(EXPIRY + 1.5)
        successor = _start_holder(config, db_file, "wait-stdin")
    finally:
        stale.send_signal(signal.SIGCONT)

    stale_out, stale_err = stale.communicate("go\n", timeout=30)
    assert "LOST True" in stale_out, stale_out + stale_err
    assert "RELEASED False" in stale_out, stale_out + stale_err

    successor_out, successor_err = successor.communicate("go\n", timeout=30)
    assert "LOST False" in successor_out, successor_out + successor_err
    assert "RELEASED True" in successor_out, successor_out + successor_err


def _duckdb_client(config: Path):
    from dblift.api.client import DBLiftClient

    return DBLiftClient.from_config_file(str(config))


def test_live_duckdb_holder_is_not_stolen_while_its_heartbeat_runs(tmp_path, monkeypatch):
    """DuckDB lets only one process open the file, so a live holder's
    contenders are other connections in the same process."""
    pytest.importorskip("duckdb_engine")
    if importlib.util.find_spec("dblift.db.plugins.lease_lock") is not None:
        monkeypatch.setattr("dblift.db.plugins.lease_lock.LEASE_EXPIRY_SECONDS", 1.0)
    config, _ = _project(tmp_path, "duckdb")
    holder, waiter = _duckdb_client(config), _duckdb_client(config)
    schema = holder.config.database.schema
    try:
        assert holder.provider.acquire_migration_lock(schema, wait_timeout_seconds=2) is True
        assert waiter.provider.acquire_migration_lock(schema, wait_timeout_seconds=4) is False
        assert holder.provider.release_migration_lock(schema) is True
    finally:
        waiter.close()
        holder.close()


def test_stale_duckdb_holder_cannot_release_the_lease_that_replaced_it(tmp_path):
    pytest.importorskip("duckdb_engine")
    config, _ = _project(tmp_path, "duckdb")
    stale, successor = _duckdb_client(config), _duckdb_client(config)
    schema = stale.config.database.schema
    try:
        assert stale.provider.acquire_migration_lock(schema, wait_timeout_seconds=2) is True
        lock_table = stale.provider.get_schema_qualified_name(schema, "dblift_migration_lock")
        # Age the stale holder's lease past any expiry, as if its heartbeat
        # had stopped an hour ago.
        successor.provider.execute_statement(
            f"UPDATE {lock_table} SET locked_at = locked_at - INTERVAL 1 HOUR"
        )

        assert successor.provider.acquire_migration_lock(schema, wait_timeout_seconds=5) is True
        assert stale.provider.release_migration_lock(schema) is False
        assert successor.provider.release_migration_lock(schema) is True
    finally:
        successor.close()
        stale.close()


@pytest.mark.parametrize("journal", ["delete", "wal"])
def test_sqlite_read_first_migrations_are_not_failed_by_their_own_heartbeat(tmp_path, journal):
    """A migration transaction that reads before it writes must not lose its
    write to the holder's own heartbeat. With a deferred ``BEGIN`` SQLite
    refuses the read-to-write upgrade at once (``database is locked``, no
    busy wait) while the heartbeat holds the write lock, and in WAL mode the
    heartbeat's commit invalidates the transaction's read snapshot."""
    config, db_file = _project(tmp_path, "sqlite")
    migrations = tmp_path / "migrations"
    (migrations / "V1__create_t1.sql").unlink()
    with sqlite3.connect(db_file) as conn:
        conn.execute(f"PRAGMA journal_mode={journal}")
        conn.execute("CREATE TABLE seed (x INTEGER)")
        conn.execute("INSERT INTO seed VALUES (1)")
    count = 8
    slow_read = (
        "SELECT COUNT(*) FROM seed, (WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL "
        "SELECT x + 1 FROM c WHERE x < 3000000) SELECT x FROM c);\n"
    )
    for i in range(1, count + 1):
        (migrations / f"V{i}__read_then_write.sql").write_text(
            f"{slow_read}CREATE TABLE r{i} (id INTEGER);\n"
        )

    # Heartbeat every 0.2 s: it fires inside most read phases.
    result = subprocess.run(
        [sys.executable, "-c", _MIGRATE, "0.6", str(config)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=100,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    with sqlite3.connect(db_file) as conn:
        applied = conn.execute(
            "SELECT COUNT(*) FROM dblift_schema_history WHERE success = 1"
        ).fetchone()[0]
    assert applied == count


def test_forked_child_exiting_normally_keeps_the_parents_lock(tmp_path):
    """A child forked while the parent holds the lock inherits the lease
    object; its interpreter exit must not release the parent's lease."""
    from dblift.api.client import DBLiftClient
    from dblift.db.plugins import lease_lock

    config, db_file = _project(tmp_path, "sqlite")
    client = DBLiftClient.from_config_file(str(config))
    schema = client.config.database.schema
    try:
        assert client.provider.acquire_migration_lock(schema, wait_timeout_seconds=2) is True
        pid = os.fork()
        if pid == 0:  # child: run the lease's exit hook as a normal exit would
            try:
                lease_lock._release_held_leases()
            finally:
                os._exit(0)
        os.waitpid(pid, 0)
        with sqlite3.connect(db_file) as conn:
            rows = conn.execute("SELECT COUNT(*) FROM dblift_migration_lock").fetchone()[0]
        assert rows == 1
        assert client.provider.release_migration_lock(schema) is True
    finally:
        client.close()


def test_caller_committed_lock_row_without_heartbeat_is_not_stolen(tmp_path, monkeypatch):
    """With ``from_sqlalchemy(connection=...)`` the lock row lives on the
    caller's connection, where no heartbeat can run. If the caller commits
    it, the row must not look like a dead lease after the short expiry."""
    pytest.importorskip("duckdb_engine")
    from sqlalchemy import create_engine

    from dblift.api.client import DBLiftClient

    if importlib.util.find_spec("dblift.db.plugins.lease_lock") is not None:
        monkeypatch.setattr("dblift.db.plugins.lease_lock.LEASE_EXPIRY_SECONDS", 0.5)
        monkeypatch.setattr("dblift.db.plugins.lease_lock.POLL_INTERVAL_SECONDS", 0.1)
    db_file = tmp_path / "app.duckdb"
    (tmp_path / "migrations").mkdir()
    caller_engine = create_engine(f"duckdb:///{db_file}")
    caller_conn = caller_engine.connect()
    holder = DBLiftClient.from_sqlalchemy(
        migrations_dir=str(tmp_path / "migrations"), connection=caller_conn
    )
    contender = DBLiftClient.from_sqlalchemy(
        create_engine(f"duckdb:///{db_file}"), migrations_dir=str(tmp_path / "migrations")
    )
    schema = holder.config.database.schema
    try:
        assert holder.provider.acquire_migration_lock(schema, wait_timeout_seconds=2) is True
        caller_conn.commit()
        time.sleep(1.5)

        assert contender.provider.acquire_migration_lock(schema, wait_timeout_seconds=2) is False
        assert holder.provider.release_migration_lock(schema) is True
    finally:
        contender.close()
        holder.close()
        caller_conn.close()


def test_forked_child_closing_its_client_keeps_the_parents_lock(tmp_path):
    """A child forked inside the parent's ``with DBLiftClient(...)`` block
    unwinds that block when it exits normally; closing the inherited client
    must not release the parent's lease."""
    from dblift.api.client import DBLiftClient

    config, db_file = _project(tmp_path, "sqlite")
    client = DBLiftClient.from_config_file(str(config))
    schema = client.config.database.schema
    try:
        assert client.provider.acquire_migration_lock(schema, wait_timeout_seconds=2) is True
        pid = os.fork()
        if pid == 0:
            try:
                client.close()
            finally:
                os._exit(0)
        os.waitpid(pid, 0)
        with sqlite3.connect(db_file) as conn:
            rows = conn.execute("SELECT COUNT(*) FROM dblift_migration_lock").fetchone()[0]
        assert rows == 1
        assert client.provider.release_migration_lock(schema) is True
    finally:
        client.close()
