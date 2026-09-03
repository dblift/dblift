"""Tests for db/plugins/sqlite/sqlite/history_manager.py."""

import unittest
from unittest.mock import MagicMock


def _make_mgr():
    from dblift.db.plugins.sqlite.sqlite.history_manager import SQLiteHistoryManager

    qe = MagicMock()
    so = MagicMock()
    config = MagicMock()
    log = MagicMock()
    return SQLiteHistoryManager(qe, so, config, log), qe, so, config


class TestSQLiteHistoryManagerInit(unittest.TestCase):
    def test_stores_components(self):
        mgr, qe, so, config = _make_mgr()
        self.assertIs(mgr.query_executor, qe)

    def test_null_log_default(self):
        from dblift.core.logger import NullLog
        from dblift.db.plugins.sqlite.sqlite.history_manager import SQLiteHistoryManager

        mgr = SQLiteHistoryManager(MagicMock(), MagicMock(), MagicMock(), None)
        self.assertIsInstance(mgr.log, NullLog)


class TestGetTableName(unittest.TestCase):
    def test_returns_default_table_name(self):
        mgr, *_ = _make_mgr()
        name = mgr._get_table_name()
        self.assertIsNotNone(name)

    def test_returns_custom_table_name(self):
        mgr, *_ = _make_mgr()
        name = mgr._get_table_name("custom_history")
        self.assertIn("custom_history", name)


class TestCreateHistoryTableIfNotExists(unittest.TestCase):
    def test_creates_table_when_not_exists(self):
        mgr, qe, so, _ = _make_mgr()
        conn = MagicMock()
        qe.table_exists.return_value = False
        mgr.create_migration_history_table_if_not_exists(conn, "main")
        qe.execute_statement.assert_called()

    def test_skips_when_table_exists(self):
        mgr, qe, *_ = _make_mgr()
        conn = MagicMock()
        qe.table_exists.return_value = True
        mgr.create_migration_history_table_if_not_exists(conn, "main")
        qe.execute_statement.assert_not_called()

    def test_creates_schema_when_flag_set(self):
        mgr, qe, so, _ = _make_mgr()
        conn = MagicMock()
        qe.table_exists.return_value = False
        mgr.create_migration_history_table_if_not_exists(conn, "main", create_schema=True)
        # SQLite doesn't have schemas but this should not raise


class TestCreateHistoryTable(unittest.TestCase):
    def test_returns_create_sql(self):
        mgr, *_ = _make_mgr()
        sql = mgr.create_history_table("main", "dblift_schema_history")
        self.assertIn("CREATE TABLE", sql.upper())


class TestRecordMigration(unittest.TestCase):
    def test_record_migration_calls_execute(self):
        mgr, qe, *_ = _make_mgr()
        conn = MagicMock()
        qe.table_exists.return_value = True
        info = {
            "script": "V1__test.sql",
            "version": "1",
            "description": "test",
            "type": "SQL",
            "checksum": 123,
            "installed_by": "user",
            "execution_time": 100,
            "success": True,
        }
        mgr.record_migration(conn, "main", info)
        qe.execute_statement.assert_called()

    def test_record_migration_creates_table_if_missing(self):
        mgr, qe, *_ = _make_mgr()
        conn = MagicMock()
        qe.table_exists.return_value = False
        info = {
            "script": "V1.sql",
            "version": "1",
            "description": "d",
            "type": "SQL",
            "checksum": 0,
            "installed_by": "u",
            "execution_time": 0,
            "success": True,
        }
        mgr.record_migration(conn, "main", info)
        # Should create table first, then execute
        self.assertTrue(qe.execute_statement.called)


class TestGetAppliedMigrations(unittest.TestCase):
    def test_returns_empty_when_no_table(self):
        mgr, qe, *_ = _make_mgr()
        qe.table_exists.return_value = False
        result = mgr.get_applied_migrations(MagicMock(), "main")
        self.assertEqual(result, [])

    def test_returns_normalized_results(self):
        mgr, qe, *_ = _make_mgr()
        qe.table_exists.return_value = True
        qe.execute_query.return_value = [
            {
                "script": "V1.sql",
                "version": "1",
                "success": 1,
                "installed_rank": 1,
                "type": "SQL",
                "description": "t",
                "checksum": "abc",
                "installed_by": "u",
                "installed_on": None,
                "execution_time": 100,
            }
        ]
        results = mgr.get_applied_migrations(MagicMock(), "main")
        self.assertEqual(len(results), 1)
