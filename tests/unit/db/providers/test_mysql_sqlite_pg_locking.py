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
