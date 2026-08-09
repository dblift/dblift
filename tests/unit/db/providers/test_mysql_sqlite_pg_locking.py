"""Tests for MySQL, SQLite, and PostgreSQL locking managers."""

import unittest
from unittest.mock import MagicMock


class TestSQLiteLockingManagerInit(unittest.TestCase):
    def _make(self):
        from db.plugins.sqlite.sqlite.locking_manager import SQLiteLockingManager

        qe = MagicMock()
        return SQLiteLockingManager(qe, MagicMock()), qe

    def test_stores_query_executor(self):
        mgr, qe = self._make()
        self.assertIs(mgr.query_executor, qe)

    def test_null_log_default(self):
        from core.logger import NullLog
        from db.plugins.sqlite.sqlite.locking_manager import SQLiteLockingManager

        mgr = SQLiteLockingManager(MagicMock())
        self.assertIsInstance(mgr.log, NullLog)


class TestSQLiteLockingManagerCreateTable(unittest.TestCase):
    def _make(self):
        from db.plugins.sqlite.sqlite.locking_manager import SQLiteLockingManager

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
        from db.plugins.sqlite.sqlite.locking_manager import SQLiteLockingManager

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


class TestPostgreSQLAdvisoryLockKey(unittest.TestCase):
    def test_get_advisory_lock_key_deterministic(self):
        from db.plugins.postgresql.postgresql._lock_key import _get_advisory_lock_key

        k1 = _get_advisory_lock_key("public")
        k2 = _get_advisory_lock_key("public")
        self.assertEqual(k1, k2)

    def test_different_schemas_different_keys(self):
        from db.plugins.postgresql.postgresql._lock_key import _get_advisory_lock_key

        self.assertNotEqual(
            _get_advisory_lock_key("public"),
            _get_advisory_lock_key("private"),
        )

    def test_returns_integer(self):
        from db.plugins.postgresql.postgresql._lock_key import _get_advisory_lock_key

        self.assertIsInstance(_get_advisory_lock_key("test"), int)
