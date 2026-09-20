"""Concurrent ``migrate()`` against a single SQLite file, from real OS
processes (not threads).

SQLite has no native advisory lock, so ``SQLiteLockingManager`` falls back to
a lock table and busy-polls it. Every statement on that path needs SQLite's
single writer lock, so the waiter's polling can collide with the holder's own
writes. Before the fix, no connection set an explicit ``busy_timeout``, and
nothing retried a "database is locked" error outside the lock-row INSERT
itself: a collision anywhere else (e.g. the very first history-table bootstrap
write) surfaced as an uncaught failure, and both processes could come away
with success=False and zero history rows -- the identical scenario succeeds
on PostgreSQL (the waiter blocks on the advisory lock, then finds the
migrations already applied and skips).

``test_second_writer_held_beyond_default_busy_timeout`` is the direct
reproduction: it holds SQLite's write lock from a second real process for
longer than the driver's implicit 5s default before letting ``migrate()``
run, which is what the report's "60 s"-of-nothing-applied slow-disk scenario
collapses to under an unfavorable window rather than a fast local disk's
usual case.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List

import pytest


def _write_migrations(migrations_dir: Path, count: int) -> None:
    migrations_dir.mkdir(parents=True, exist_ok=True)
    for i in range(1, count + 1):
        (migrations_dir / f"V1_0_{i}__t{i}.sql").write_text(
            f"CREATE TABLE t{i} (id INTEGER PRIMARY KEY);\n"
        )


def _history_rows(db_path: Path) -> Any:
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute("SELECT COUNT(*) FROM dblift_schema_history").fetchone()[0]
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()


def _run_migrate(
    migrations_dir: str,
    db_path: str,
    result_queue: "mp.Queue[Dict[str, Any]]",
    label: str,
    barrier: Any = None,
) -> None:
    """Worker body for a real OS process: run one ``migrate()`` call.

    ``migrate()`` has no ``wait_timeout_seconds`` parameter -- the CLI/API
    path always uses the 60s default (``migrate_command.py``). Tests that
    need a shorter lock-wait budget talk to the provider/locking-manager
    directly instead of through this helper.
    """
    from dblift.api.client import DBLiftClient
    from dblift.config import DbliftConfig

    config = DbliftConfig.from_dict(
        {"database": {"type": "sqlite", "path": db_path, "schema": "main"}}
    )
    client = DBLiftClient.from_config(config, migrations_dir=migrations_dir)
    if barrier is not None:
        barrier.wait()
    start = time.time()
    try:
        result = client.migrate()
        result_queue.put(
            {
                "label": label,
                "pid": os.getpid(),
                "success": result.success,
                "error": result.error_message,
                "applied": len(result.migrations),
                "elapsed": time.time() - start,
            }
        )
    except Exception as e:  # pragma: no cover - captured as a result, not raised
        result_queue.put(
            {
                "label": label,
                "pid": os.getpid(),
                "success": False,
                "error": f"{type(e).__name__}: {e}",
                "applied": 0,
                "elapsed": time.time() - start,
            }
        )
    finally:
        try:
            client.close()
        except Exception:
            pass


def _hold_write_lock(
    db_path: str, hold_seconds: float, ready_event: Any, release_event: Any
) -> None:
    """Worker body for a real OS process: grab SQLite's write lock and sit on it."""
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.execute("BEGIN IMMEDIATE")
    conn.execute("CREATE TABLE IF NOT EXISTS holder_marker (x INTEGER)")
    ready_event.set()
    time.sleep(hold_seconds)
    conn.execute("COMMIT")
    conn.close()
    release_event.set()


@pytest.mark.integration
@pytest.mark.sqlite
class TestSqliteConcurrentMigrate:
    def test_two_processes_fresh_file_apply_exactly_once(self, tmp_path):
        """Two real OS processes race `migrate()` on one fresh SQLite file.

        Exactly one applies all migrations; the other waits for the lock,
        discovers they were already applied, and skips -- same outcome as
        the PostgreSQL/MySQL native-lock providers. Both calls must succeed.
        """
        migrations_dir = tmp_path / "migrations"
        _write_migrations(migrations_dir, count=10)
        db_path = tmp_path / "test.db"

        ctx = mp.get_context("fork")
        barrier = ctx.Barrier(2)
        result_queue: "mp.Queue[Dict[str, Any]]" = ctx.Queue()
        procs = [
            ctx.Process(
                target=_run_migrate,
                args=(str(migrations_dir), str(db_path), result_queue, label, barrier),
            )
            for label in ("A", "B")
        ]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=60)
            assert not p.is_alive(), "migrate() process did not finish in time"

        results = [result_queue.get(timeout=1) for _ in procs]
        assert all(r["success"] for r in results), results
        assert sorted(r["applied"] for r in results) == [0, 10], results
        assert _history_rows(db_path) == 10

    def test_two_processes_one_has_nothing_to_apply(self, tmp_path):
        """A schema already fully migrated: two concurrent `migrate()` calls
        against it must both succeed and add nothing."""
        migrations_dir = tmp_path / "migrations"
        _write_migrations(migrations_dir, count=5)
        db_path = tmp_path / "test.db"

        ctx = mp.get_context("fork")
        first_queue: "mp.Queue[Dict[str, Any]]" = ctx.Queue()
        _run_migrate(str(migrations_dir), str(db_path), first_queue, "seed")
        seed_result = first_queue.get(timeout=1)
        assert seed_result["success"] and seed_result["applied"] == 5

        barrier = ctx.Barrier(2)
        result_queue: "mp.Queue[Dict[str, Any]]" = ctx.Queue()
        procs = [
            ctx.Process(
                target=_run_migrate,
                args=(str(migrations_dir), str(db_path), result_queue, label, barrier),
            )
            for label in ("A", "B")
        ]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=60)
            assert not p.is_alive()

        results = [result_queue.get(timeout=1) for _ in procs]
        assert all(r["success"] for r in results), results
        assert all(r["applied"] == 0 for r in results), results
        assert _history_rows(db_path) == 5

    def test_three_processes_fresh_file_apply_exactly_once(self, tmp_path):
        """Same guarantee under three-way contention, not just two."""
        migrations_dir = tmp_path / "migrations"
        _write_migrations(migrations_dir, count=12)
        db_path = tmp_path / "test.db"

        ctx = mp.get_context("fork")
        barrier = ctx.Barrier(3)
        result_queue: "mp.Queue[Dict[str, Any]]" = ctx.Queue()
        procs = [
            ctx.Process(
                target=_run_migrate,
                args=(str(migrations_dir), str(db_path), result_queue, label, barrier),
            )
            for label in ("A", "B", "C")
        ]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=60)
            assert not p.is_alive()

        results = [result_queue.get(timeout=1) for _ in procs]
        assert all(r["success"] for r in results), results
        assert sum(r["applied"] for r in results) == 12, results
        assert _history_rows(db_path) == 12

    def test_second_writer_held_beyond_default_busy_timeout(self, tmp_path):
        """A second real process holds SQLite's write lock for longer than
        the driver's implicit 5s default busy_timeout before `migrate()`
        even reaches lock acquisition. `migrate()` must wait it out and
        still succeed, not surface "database is locked" as a hard failure.
        """
        migrations_dir = tmp_path / "migrations"
        _write_migrations(migrations_dir, count=5)
        db_path = tmp_path / "test.db"

        ctx = mp.get_context("fork")
        ready_event = ctx.Event()
        release_event = ctx.Event()
        result_queue: "mp.Queue[Dict[str, Any]]" = ctx.Queue()

        hold_seconds = 6.0
        holder = ctx.Process(
            target=_hold_write_lock,
            args=(str(db_path), hold_seconds, ready_event, release_event),
        )
        holder.start()
        assert ready_event.wait(timeout=10), "holder never acquired the write lock"

        waiter = ctx.Process(
            target=_run_migrate,
            args=(str(migrations_dir), str(db_path), result_queue, "waiter"),
        )
        waiter.start()
        waiter.join(timeout=60)
        holder.join(timeout=10)

        assert not waiter.is_alive()
        result = result_queue.get(timeout=1)
        assert result["success"], result
        assert result["applied"] == 5, result
        assert _history_rows(db_path) == 5

    def test_process_killed_while_holding_lock_does_not_corrupt_history(self, tmp_path):
        """A process that dies mid-migration leaves the lock row behind
        (SQLite's stale-lock cleanup only reclaims rows older than 24
        hours). The next attempt must not hang forever or corrupt history
        -- it waits out its own timeout and reports failure cleanly.

        Talks to the provider/locking-manager directly (not the full
        `migrate()` pipeline, whose lock wait is hardcoded to 60s) so the
        test can use a short wait budget and stay fast. This documents
        current behavior -- it does not assert early stale-lock recovery,
        which this fix does not add.
        """
        db_path = tmp_path / "test.db"

        ctx = mp.get_context("fork")

        def _acquire_and_die(db_path: str) -> None:
            from dblift.config import DbliftConfig
            from dblift.db.plugins.sqlite.provider import SQLiteProvider

            config = DbliftConfig.from_dict(
                {"database": {"type": "sqlite", "path": db_path, "schema": "main"}}
            )
            provider = SQLiteProvider(config)
            provider.create_connection()
            provider.create_migration_lock_table_if_not_exists("main")
            acquired = provider.acquire_migration_lock("main", wait_timeout_seconds=10)
            assert acquired
            os._exit(9)  # simulate a kill: no lock release, no cleanup

        dying = ctx.Process(target=_acquire_and_die, args=(str(db_path),))
        dying.start()
        dying.join(timeout=15)
        assert not dying.is_alive()

        def _try_acquire_short_timeout(
            db_path: str, result_queue: "mp.Queue[Dict[str, Any]]"
        ) -> None:
            from dblift.config import DbliftConfig
            from dblift.db.plugins.sqlite.provider import SQLiteProvider

            config = DbliftConfig.from_dict(
                {"database": {"type": "sqlite", "path": db_path, "schema": "main"}}
            )
            provider = SQLiteProvider(config)
            provider.create_connection()
            start = time.time()
            acquired = provider.acquire_migration_lock("main", wait_timeout_seconds=2)
            result_queue.put({"acquired": acquired, "elapsed": time.time() - start})
            provider.close()

        result_queue: "mp.Queue[Dict[str, Any]]" = ctx.Queue()
        waiter = ctx.Process(target=_try_acquire_short_timeout, args=(str(db_path), result_queue))
        waiter.start()
        waiter.join(timeout=15)
        assert not waiter.is_alive()
        result = result_queue.get(timeout=1)

        # Current, documented behavior: the abandoned lock row is not
        # younger than 24h old, so it is not reclaimed -- acquisition waits
        # out its own (short, here) timeout and returns False rather than
        # hanging indefinitely or silently stealing the lock.
        assert result["acquired"] is False
        assert result["elapsed"] >= 2.0
        assert _history_rows(db_path) in (None, 0)

    def test_default_journal_mode_is_rollback_not_wal(self, tmp_path):
        """SQLite provider does not expose a journal_mode/WAL setting; every
        connection uses SQLite's default rollback journal. Documents the
        current state so a future WAL toggle is a deliberate, visible change
        rather than a silent side effect of some other edit."""
        from dblift.config import DbliftConfig
        from dblift.db.plugins.sqlite.provider import SQLiteProvider

        db_path = tmp_path / "test.db"
        config = DbliftConfig.from_dict(
            {"database": {"type": "sqlite", "path": str(db_path), "schema": "main"}}
        )
        provider = SQLiteProvider(config)
        try:
            connection = provider.create_connection()
            mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
            assert mode.lower() == "delete"
        finally:
            provider.close()

    def test_migrate_widens_busy_timeout_then_restores_it(self, tmp_path):
        """`migrate()` raises this connection's busy_timeout for its own
        duration (covering the history-table bootstrap and the lock path
        both), then restores the driver's short default afterward -- a
        later command reusing this same connection must not inherit the
        wait."""
        from dblift.api.client import DBLiftClient
        from dblift.config import DbliftConfig
        from dblift.core.constants import DEFAULT_MIGRATION_LOCK_TIMEOUT_SECONDS
        from dblift.db.plugins.sqlite.sqlite import DEFAULT_BUSY_TIMEOUT_SECONDS

        migrations_dir = tmp_path / "migrations"
        _write_migrations(migrations_dir, count=1)
        db_path = tmp_path / "test.db"

        config = DbliftConfig.from_dict(
            {"database": {"type": "sqlite", "path": str(db_path), "schema": "main"}}
        )
        client = DBLiftClient.from_config(config, migrations_dir=migrations_dir)
        try:
            seen_during_call: Dict[float, int] = {}
            original_set = client.provider.set_busy_timeout

            def spy(seconds: float) -> None:
                original_set(seconds)
                connection = client.provider._get_connection()
                seen_during_call[seconds] = connection.execute("PRAGMA busy_timeout").fetchone()[0]

            client.provider.set_busy_timeout = spy
            result = client.migrate()
            assert result.success

            # Raised to the migration lock budget during the call...
            assert seen_during_call[DEFAULT_MIGRATION_LOCK_TIMEOUT_SECONDS] == int(
                DEFAULT_MIGRATION_LOCK_TIMEOUT_SECONDS * 1000
            )
            # ...and restored to the driver's short default afterward.
            connection = client.provider._get_connection()
            final_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]
            assert final_timeout == int(DEFAULT_BUSY_TIMEOUT_SECONDS * 1000)
        finally:
            client.close()

    def test_ordinary_command_does_not_widen_busy_timeout(self, tmp_path):
        """A command with no lock contention (`info`) never touches this
        connection's busy_timeout -- it stays at the driver's short default
        for the whole call, so a genuinely locked file still fails fast
        rather than hanging for a minute."""
        from dblift.api.client import DBLiftClient
        from dblift.config import DbliftConfig
        from dblift.db.plugins.sqlite.sqlite import DEFAULT_BUSY_TIMEOUT_SECONDS

        migrations_dir = tmp_path / "migrations"
        _write_migrations(migrations_dir, count=1)
        db_path = tmp_path / "test.db"

        config = DbliftConfig.from_dict(
            {"database": {"type": "sqlite", "path": str(db_path), "schema": "main"}}
        )
        client = DBLiftClient.from_config(config, migrations_dir=migrations_dir)
        try:
            client.info()
            connection = client.provider._get_connection()
            timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]
            assert timeout == int(DEFAULT_BUSY_TIMEOUT_SECONDS * 1000)
        finally:
            client.close()
