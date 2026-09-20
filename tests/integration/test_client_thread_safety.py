"""Two threads sharing one DBLiftClient must not corrupt migration state.

The client holds a single provider/connection for its lifetime (see
``DBLiftClient``'s docstring). Nothing previously serialized access to it,
so two threads calling operations concurrently on the same client instance
raced on that one connection: ``MigrationExecutor.migrate()`` (and the other
operations) could be entered by both threads at once.

The CLI equivalent -- two OS processes -- serializes correctly through the
database-level migration lock, because each process has its own connection.
Sharing one client object across threads is a different hazard: it is the
*client*, not the database, that must keep two threads from interleaving on
one connection.

These tests instrument ``MigrationExecutor`` to detect concurrent entry
deterministically (a small sleep inside the patched method widens the
race window) rather than relying on timing luck against a fast in-memory
migration.

The client's operation lock is an ``RLock``, not a plain ``Lock``: event
listeners run synchronously, on the same thread, while an operation holds
the lock (``EventEmitter._dispatch`` calls each listener directly from
``emit()``). A listener that calls another operation on the same client
(e.g. ``client.info()`` from a ``MIGRATION_STARTED`` handler) must not
deadlock on a lock its own thread already holds.
"""

import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine

from dblift.api import DBLiftClient
from dblift.api.events import EventType
from dblift.core.migration.executor.migration_executor import MigrationExecutor


class _ConcurrencyProbe:
    """Tracks how many threads are simultaneously inside a patched method."""

    def __init__(self, hold_seconds: float = 0.2) -> None:
        self.hold_seconds = hold_seconds
        self._lock = threading.Lock()
        self._active = 0
        self.max_concurrent = 0
        self.call_count = 0

    def wrap(self, original):
        def wrapper(instance, *args, **kwargs):
            with self._lock:
                self._active += 1
                self.call_count += 1
                self.max_concurrent = max(self.max_concurrent, self._active)
            try:
                time.sleep(self.hold_seconds)
                return original(instance, *args, **kwargs)
            finally:
                with self._lock:
                    self._active -= 1

        return wrapper


def _client_with_migration(tmp_path: Path, sql: str = None) -> DBLiftClient:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1__init.sql").write_text(
        sql or "CREATE TABLE app_users (id INTEGER PRIMARY KEY, name TEXT NOT NULL);"
    )
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
    return DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations)


@pytest.mark.integration
class TestClientThreadSafety:
    def test_two_threads_migrate_on_one_client_are_serialized(self, tmp_path):
        """Two threads calling migrate() on one client never run
        MigrationExecutor.migrate() at the same time.

        Reproduction (before the fix): max_concurrent == 2 here — the client
        holds one provider/connection for its lifetime, but nothing stopped
        a second thread from entering the same operation while the first
        was still inside it, on that same connection.
        """
        client = _client_with_migration(tmp_path)
        probe = _ConcurrencyProbe(hold_seconds=0.2)
        errors = []

        def run():
            try:
                client.migrate()
            except Exception as e:  # noqa: BLE001 - captured for assertion
                errors.append(e)

        with patch.object(MigrationExecutor, "migrate", probe.wrap(MigrationExecutor.migrate)):
            barrier = threading.Barrier(2)

            def run_sync():
                barrier.wait(timeout=5)
                run()

            t1 = threading.Thread(target=run_sync)
            t2 = threading.Thread(target=run_sync)
            t1.start()
            t2.start()
            t1.join(timeout=30)
            t2.join(timeout=30)

        client.close()

        assert probe.call_count == 2
        assert probe.max_concurrent == 1, (
            "two threads sharing one DBLiftClient were both inside "
            "MigrationExecutor.migrate() at the same time -- the client did "
            "not serialize the shared connection"
        )
        assert not errors, f"unexpected exceptions: {errors}"

    def test_many_threads_migrate_on_one_client_are_serialized(self, tmp_path):
        """Ten threads hammering migrate() on one client never overlap."""
        client = _client_with_migration(tmp_path)
        probe = _ConcurrencyProbe(hold_seconds=0.05)
        errors = []
        n_threads = 10

        def run():
            try:
                client.migrate()
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        with patch.object(MigrationExecutor, "migrate", probe.wrap(MigrationExecutor.migrate)):
            barrier = threading.Barrier(n_threads)

            def run_sync():
                barrier.wait(timeout=5)
                run()

            threads = [threading.Thread(target=run_sync) for _ in range(n_threads)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)

        client.close()

        assert probe.call_count == n_threads
        assert probe.max_concurrent == 1
        assert not errors, f"unexpected exceptions: {errors}"

    def test_two_threads_different_methods_are_serialized(self, tmp_path):
        """migrate() and info() share the same connection and must not overlap."""
        client = _client_with_migration(tmp_path)
        probe = _ConcurrencyProbe(hold_seconds=0.2)
        errors = []

        def run_migrate():
            try:
                client.migrate()
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        def run_info():
            try:
                client.info()
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        with (
            patch.object(MigrationExecutor, "migrate", probe.wrap(MigrationExecutor.migrate)),
            patch.object(MigrationExecutor, "info", probe.wrap(MigrationExecutor.info)),
        ):
            barrier = threading.Barrier(2)

            def sync_migrate():
                barrier.wait(timeout=5)
                run_migrate()

            def sync_info():
                barrier.wait(timeout=5)
                run_info()

            t1 = threading.Thread(target=sync_migrate)
            t2 = threading.Thread(target=sync_info)
            t1.start()
            t2.start()
            t1.join(timeout=30)
            t2.join(timeout=30)

        client.close()

        assert probe.call_count == 2
        assert probe.max_concurrent == 1, (
            "migrate() and info() on one client ran concurrently on the "
            "shared connection instead of serializing"
        )
        assert not errors, f"unexpected exceptions: {errors}"

    def test_thread_raising_mid_operation_releases_the_lock(self, tmp_path):
        """A crashing operation must not leave the client's lock held forever."""
        client = _client_with_migration(tmp_path)

        def boom(self, *args, **kwargs):
            raise RuntimeError("simulated failure mid-operation")

        with patch.object(MigrationExecutor, "migrate", boom):
            with pytest.raises(RuntimeError, match="simulated failure mid-operation"):
                client.migrate()

        # The lock must be free now -- a second, real call should proceed
        # normally rather than hang.
        result = client.migrate()
        assert result.success
        client.close()

    def test_failed_migration_releases_the_database_level_lock(self, tmp_path):
        """A migration that fails mid-script must not leave the *database*-level
        migration lock stuck, on top of releasing the client's own lock.

        migrate_command.py acquires and releases the database-level lock in
        a try/finally entirely inside one MigrationExecutor.migrate() call,
        which itself runs entirely inside one hold of the client's operation
        lock. So the two locks can never deadlock against each other: by the
        time the client lock is released, the database lock's release has
        already been attempted. This proves it empirically for the failure
        path, not just by reading the control flow.
        """
        client = _client_with_migration(
            tmp_path,
            sql="CREATE TABLE t (id INTEGER PRIMARY KEY);\nTHIS IS NOT VALID SQL;",
        )

        first = client.migrate()
        assert not first.success

        start = time.perf_counter()
        second = client.migrate()
        elapsed = time.perf_counter() - start

        # The database lock retry loop waits up to 60s if the lock were
        # stuck; a fast return proves it wasn't.
        assert elapsed < 5, (
            f"second migrate() took {elapsed:.2f}s -- looks like it waited "
            "out a stuck database-level lock"
        )
        client.close()

    def test_event_listener_calling_another_operation_does_not_deadlock(self, tmp_path):
        """A listener may legally call another operation on the same client
        from within its own callback -- that must not deadlock.

        Reproduction (with a plain, non-reentrant Lock instead of RLock):
        the listener's nested client.info() call blocks forever trying to
        re-acquire a lock its own thread already holds for migrate().
        """
        client = _client_with_migration(tmp_path)
        listener_ran = {"value": False}

        def on_started(event):
            listener_ran["value"] = True
            client.info()  # nested call, same thread, lock already held

        client.events.on(EventType.MIGRATION_STARTED, on_started)

        result = {}

        def run():
            result["migrate"] = client.migrate()

        t = threading.Thread(target=run, daemon=True)
        t.start()
        t.join(timeout=5)

        assert not t.is_alive(), "listener calling client.info() deadlocked"
        assert listener_ran["value"]
        assert result["migrate"].success
        client.close()

    def test_single_threaded_migrate_still_works(self, tmp_path):
        """No regression: a single-threaded caller sees ordinary behavior."""
        client = _client_with_migration(tmp_path)
        result = client.migrate()
        assert result.success
        assert result.migrations_applied
        client.close()
