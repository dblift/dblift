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

    def test_event_listener_calling_migrate_from_migrate_does_not_misreport(self, tmp_path):
        """A listener must not silently run a second migration underneath
        the first and leave the outer call lying about what happened.

        Before the reentrancy guard: the nested migrate() actually applies
        the migration, then the *outer* migrate() finds nothing pending and
        returns success=True, migrations_applied=[] -- a false report of
        having done nothing while a real migration happened underneath it.

        ``EventEmitter._dispatch`` catches and swallows exceptions raised by
        listeners (pre-existing, unrelated to this fix -- a listener must
        not be able to crash the operation it's observing), so the *outer*
        migrate() call does not itself raise. The fix is that the nested
        call is refused with a clear error *before it touches the
        database*, so nothing runs underneath the outer call, and the
        outer call's own (accurate) result is what the caller sees.
        """
        client = _client_with_migration(tmp_path)
        nested_error = {}

        def on_started(event):
            try:
                client.migrate()
            except RuntimeError as e:
                nested_error["error"] = e

        client.events.on(EventType.MIGRATION_STARTED, on_started)

        outer = client.migrate()

        assert "error" in nested_error, "listener's nested migrate() did not raise"
        assert "migrate" in str(nested_error["error"])
        # The outer call's result is now accurate: it -- not some nested
        # call the caller never issued -- is what actually ran.
        assert outer.success
        assert outer.migrations_applied == ["1"]
        client.close()

    def test_event_listener_recursively_calling_migrate_does_not_recurse(self, tmp_path):
        """An unconditional listener->migrate() loop must fail on the first
        reentrant attempt, not recurse until RecursionError.
        """
        client = _client_with_migration(tmp_path)
        call_count = {"n": 0}
        nested_error = {}

        def on_started(event):
            call_count["n"] += 1
            try:
                client.migrate()  # always re-enters; must be refused immediately
            except RuntimeError as e:
                nested_error["error"] = e

        client.events.on(EventType.MIGRATION_STARTED, on_started)

        outer = client.migrate()

        # The listener fires exactly once: the refused nested call raises
        # before it ever reaches migrate()'s own MIGRATION_STARTED emit, so
        # there is no second (or recursive) invocation of the listener.
        assert call_count["n"] == 1
        assert "error" in nested_error
        assert outer.success
        client.close()

    def test_close_does_not_overlap_an_in_flight_migrate(self, tmp_path):
        """close()/__exit__ touch self.provider directly and previously
        bypassed the operation lock entirely -- a concurrent close() could
        run while migrate() was still using the connection. They now take
        the same lock.
        """
        client = _client_with_migration(tmp_path)
        probe = _ConcurrencyProbe(hold_seconds=0.2)
        errors = []

        def run_migrate():
            try:
                client.migrate()
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        with (
            patch.object(DBLiftClient, "_exit_unlocked", probe.wrap(DBLiftClient._exit_unlocked)),
            patch.object(MigrationExecutor, "migrate", probe.wrap(MigrationExecutor.migrate)),
        ):
            barrier = threading.Barrier(2)

            def sync_migrate():
                barrier.wait(timeout=5)
                run_migrate()

            def sync_close():
                barrier.wait(timeout=5)
                client.close()

            t1 = threading.Thread(target=sync_migrate)
            t2 = threading.Thread(target=sync_close)
            t1.start()
            t2.start()
            t1.join(timeout=30)
            t2.join(timeout=30)

        assert probe.call_count == 2
        assert probe.max_concurrent == 1, (
            "close() ran concurrently with an in-flight migrate() on the "
            "shared connection instead of serializing"
        )
        assert not errors, f"unexpected exceptions: {errors}"

    def test_event_listener_calling_close_during_migrate_is_refused(self, tmp_path):
        """A listener must not be able to tear down the connection mid-operation.

        Before the reentrancy guard on close()/__exit__: the RLock's
        same-thread reentrancy let a listener's client.close() through, the
        provider silently auto-reconnected underneath on the next call, and
        the *outer* migrate() kept running and reported success=True as if
        nothing had happened -- exactly the "outer operation's view goes
        stale" failure this whole guard exists to prevent, arriving through
        close() instead of a second migrate(). On a session-scoped
        database-level lock (PostgreSQL advisory lock, MySQL GET_LOCK) this
        would silently drop that lock mid-run.
        """
        client = _client_with_migration(tmp_path)
        nested_error = {}

        def on_started(event):
            try:
                client.close()
            except RuntimeError as e:
                nested_error["error"] = e

        client.events.on(EventType.MIGRATION_STARTED, on_started)

        outer = client.migrate()

        assert "error" in nested_error, "listener's client.close() did not raise"
        assert "close" in str(nested_error["error"])
        # The connection was never actually torn down mid-operation, so the
        # outer call's own result is accurate.
        assert outer.success
        assert outer.migrations_applied == ["1"]
        client.close()

    def test_ordinary_with_block_still_closes_cleanly(self, tmp_path):
        """No regression: the normal context-manager pattern is unaffected.

        By the time __exit__ runs at the end of the `with` block, the
        migrate() call inside it has already returned and this thread's
        depth is back to 0 -- the reentrancy guard does not fire.
        """
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "V1__init.sql").write_text(
            "CREATE TABLE app_users (id INTEGER PRIMARY KEY, name TEXT NOT NULL);"
        )
        engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}")

        with DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations_dir) as client:
            result = client.migrate()
            assert result.success
        # __exit__ ran without raising; the provider connection is closed.

    def test_single_threaded_migrate_still_works(self, tmp_path):
        """No regression: a single-threaded caller sees ordinary behavior."""
        client = _client_with_migration(tmp_path)
        result = client.migrate()
        assert result.success
        assert result.migrations_applied
        client.close()
