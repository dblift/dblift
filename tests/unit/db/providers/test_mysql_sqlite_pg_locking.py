"""Tests for MySQL, SQLite, and PostgreSQL locking managers."""

import sqlite3
import unittest
from unittest.mock import MagicMock


class TestSQLiteLockingManagerInit(unittest.TestCase):
    def _make(self):
        from dblift.db.plugins.sqlite.sqlite.locking_manager import SQLiteLockingManager

        qe = MagicMock()
        return SQLiteLockingManager(qe, MagicMock()), qe

    def test_stores_query_executor(self):
        mgr, qe = self._make()
        self.assertIs(mgr.query_executor, qe)

    def test_null_log_default(self):
        from dblift.core.logger import NullLog
        from dblift.db.plugins.sqlite.sqlite.locking_manager import SQLiteLockingManager

        mgr = SQLiteLockingManager(MagicMock())
        self.assertIsInstance(mgr.log, NullLog)


class TestSQLiteLockingManagerCreateTable(unittest.TestCase):
    def _make(self):
        from dblift.db.plugins.sqlite.sqlite.locking_manager import SQLiteLockingManager

        qe = MagicMock()
        return SQLiteLockingManager(qe, MagicMock()), qe

    def test_create_table_executes_statement(self):
        mgr, qe = self._make()
        conn = MagicMock()
        mgr.create_migration_lock_table_if_not_exists(conn, "main")
        qe.execute_statement.assert_called_once()

    def test_raises_on_error(self):
        mgr, qe = self._make()
        qe.execute_statement.side_effect = Exception("disk full")
        with self.assertRaises(Exception):
            mgr.create_migration_lock_table_if_not_exists(MagicMock(), "main")


class TestSQLiteLockingManagerAcquireRelease(unittest.TestCase):
    def _make(self):
        from dblift.db.plugins.sqlite.sqlite.locking_manager import SQLiteLockingManager

        qe = MagicMock()
        return SQLiteLockingManager(qe, MagicMock()), qe

    def test_acquire_returns_bool(self):
        mgr, qe = self._make()
        qe.execute_statement.return_value = None
        result = mgr.acquire_migration_lock(MagicMock(), "main")
        self.assertIsInstance(result, bool)

    def test_release_returns_bool(self):
        mgr, qe = self._make()
        qe.execute_statement.return_value = None
        result = mgr.release_migration_lock(MagicMock(), "main")
        self.assertIsInstance(result, bool)


class TestSQLiteLockingManagerLostRaceLogging(unittest.TestCase):
    """Losing the lock row race is the expected outcome for a waiter, not a
    failure -- it must not be logged like one.

    ``query_executor.execute_statement`` logs the SQL text and bound
    parameters at ERROR level on *any* exception (it has no way to know a
    given statement's failure is routine). The lock-row INSERT must
    therefore not go through it -- it needs to execute directly on the
    connection so a lost race can be handled quietly instead.
    """

    def test_lost_race_insert_bypasses_the_logging_query_executor(self):
        from dblift.db.plugins.sqlite.sqlite.locking_manager import SQLiteLockingManager

        qe = MagicMock()
        mgr = SQLiteLockingManager(qe, MagicMock())
        conn = MagicMock()
        conn.execute.side_effect = sqlite3.IntegrityError(
            "UNIQUE constraint failed: dblift_migration_lock.lock_name"
        )

        # wait_timeout_seconds=1 with a losing attempt every time: one real
        # `time.sleep(1)` inside the loop, then the elapsed-time check ends
        # it. Short enough to keep the test fast without mocking away the
        # loop's own timing (which would need a fake clock to stay correct).
        result = mgr.acquire_migration_lock(conn, "main", wait_timeout_seconds=1)

        self.assertFalse(result)
        insert_calls = [
            call for call in qe.execute_statement.call_args_list if "INSERT INTO" in call.args[1]
        ]
        self.assertEqual(
            insert_calls,
            [],
            "lock-row INSERT must not go through query_executor.execute_statement",
        )


class TestSQLiteLockWaiterTransaction(unittest.TestCase):
    """A waiter must not keep a transaction open between lock attempts.

    Uses real connections in sqlite3's legacy mode (implicit BEGIN before
    DML), which is what SQLAlchemy's pysqlite dialect hands over.
    """

    LOCK_DDL = (
        'CREATE TABLE "dblift_migration_lock" (lock_name TEXT PRIMARY KEY, '
        "acquired_at TEXT, acquired_by TEXT, process_id TEXT, lock_mode INTEGER)"
    )

    def setUp(self):
        import os
        import tempfile

        from dblift.db.plugins.sqlite.sqlite.locking_manager import SQLiteLockingManager

        self.path = os.path.join(tempfile.mkdtemp(), "lock.db")
        self.holder = sqlite3.connect(self.path, isolation_level=None)
        self.holder.execute(self.LOCK_DDL)
        self.mgr = SQLiteLockingManager(MagicMock(), MagicMock())
        self.addCleanup(self.holder.close)

    def _hold_lock_row(self):
        self.holder.execute(
            'INSERT INTO "dblift_migration_lock" VALUES '
            "('dblift_migration_lock_main', datetime('now'), 'other', '1', 1)"
        )

    def test_lost_race_does_not_leave_a_transaction_open(self):
        self._hold_lock_row()
        waiter = sqlite3.connect(self.path)
        self.addCleanup(waiter.close)

        self.assertFalse(self.mgr.acquire_migration_lock(waiter, "main", wait_timeout_seconds=1))
        self.assertFalse(waiter.in_transaction)

    def test_lost_race_leaves_the_callers_own_transaction_alone(self):
        self._hold_lock_row()
        self.holder.execute("CREATE TABLE mine (x INTEGER)")
        caller = sqlite3.connect(self.path)
        self.addCleanup(caller.close)
        caller.execute("INSERT INTO mine VALUES (1)")

        self.assertFalse(self.mgr.acquire_migration_lock(caller, "main", wait_timeout_seconds=1))
        self.assertTrue(caller.in_transaction)
        caller.commit()
        self.assertEqual(caller.execute("SELECT count(*) FROM mine").fetchone()[0], 1)

    def test_busy_database_does_not_leave_a_transaction_open(self):
        # IMMEDIATE, not EXCLUSIVE: the waiter can still begin, then fails on the write.
        self.holder.execute("BEGIN IMMEDIATE")
        self.addCleanup(self.holder.execute, "ROLLBACK")
        waiter = sqlite3.connect(self.path, timeout=0)
        self.addCleanup(waiter.close)

        self.assertFalse(self.mgr.acquire_migration_lock(waiter, "main", wait_timeout_seconds=1))
        self.assertFalse(waiter.in_transaction)


class TestSQLiteProviderWidenBusyTimeout(unittest.TestCase):
    def _provider(self, busy_timeout_ms):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
        provider = MagicMock()
        provider._get_connection.return_value = conn
        return provider

    def test_widens_a_shorter_timeout_and_returns_the_undo(self):
        from dblift.db.plugins.sqlite.provider import SQLiteProvider

        provider = self._provider(5000)
        undo = SQLiteProvider.widen_busy_timeout(provider, 60)

        provider.set_busy_timeout.assert_called_once_with(60)
        undo()
        provider.set_busy_timeout.assert_called_with(5.0)

    def test_leaves_an_already_wider_timeout_alone(self):
        from dblift.db.plugins.sqlite.provider import SQLiteProvider

        provider = self._provider(90000)

        self.assertIsNone(SQLiteProvider.widen_busy_timeout(provider, 60))
        provider.set_busy_timeout.assert_not_called()


class TestPostgreSQLAdvisoryLockKey(unittest.TestCase):
    def test_get_advisory_lock_key_deterministic(self):
        from dblift.db.plugins.postgresql.postgresql._lock_key import _get_advisory_lock_key

        k1 = _get_advisory_lock_key("public")
        k2 = _get_advisory_lock_key("public")
        self.assertEqual(k1, k2)

    def test_different_schemas_different_keys(self):
        from dblift.db.plugins.postgresql.postgresql._lock_key import _get_advisory_lock_key

        self.assertNotEqual(
            _get_advisory_lock_key("public"),
            _get_advisory_lock_key("private"),
        )

    def test_returns_integer(self):
        from dblift.db.plugins.postgresql.postgresql._lock_key import _get_advisory_lock_key

        self.assertIsInstance(_get_advisory_lock_key("test"), int)
