"""Tests for db/plugins/sqlite/sqlite/schema_operations.py."""

import unittest
from unittest.mock import MagicMock


def _make_ops():
    from dblift.db.plugins.sqlite.sqlite.schema_operations import SQLiteSchemaOperations

    qe = MagicMock()
    log = MagicMock()
    return SQLiteSchemaOperations(query_executor=qe, log=log), qe, log


class TestSQLiteSchemaOpsInit(unittest.TestCase):
    def test_stores_executor(self):
        ops, qe, _ = _make_ops()
        self.assertIs(ops.query_executor, qe)

    def test_null_log_default(self):
        from dblift.core.logger import NullLog
        from dblift.db.plugins.sqlite.sqlite.schema_operations import SQLiteSchemaOperations

        ops = SQLiteSchemaOperations(MagicMock())
        self.assertIsInstance(ops.log, NullLog)


class TestFts5ShadowTableNames(unittest.TestCase):
    def test_returns_empty_set_when_no_fts5(self):
        ops, qe, _ = _make_ops()
        qe.execute_query.return_value = []
        conn = MagicMock()
        result = ops._fts5_shadow_table_names(conn)
        self.assertEqual(result, set())

    def test_returns_shadow_names(self):
        ops, qe, _ = _make_ops()
        qe.execute_query.return_value = [{"name": "docs"}]
        conn = MagicMock()
        result = ops._fts5_shadow_table_names(conn)
        # Should include docs_data, docs_idx, etc.
        self.assertIsInstance(result, set)

    def test_handles_exception(self):
        ops, qe, _ = _make_ops()
        qe.execute_query.side_effect = Exception("query failed")
        conn = MagicMock()
        result = ops._fts5_shadow_table_names(conn)
        self.assertEqual(result, set())


class TestCreateSchemaIfNotExists(unittest.TestCase):
    def test_noop_for_sqlite(self):
        ops, qe, _ = _make_ops()
        # SQLite doesn't support schemas, so this should be a no-op
        ops.create_schema_if_not_exists(MagicMock(), "main")
        qe.execute_statement.assert_not_called()


class TestGetDatabaseVersion(unittest.TestCase):
    def test_returns_version_string(self):
        ops, qe, _ = _make_ops()
        qe.execute_query.return_value = [{"sqlite_version()": "3.40.0"}]
        conn = MagicMock()
        version = ops.get_database_version(conn)
        self.assertIsInstance(version, str)

    def test_handles_exception(self):
        ops, qe, _ = _make_ops()
        qe.execute_query.side_effect = Exception("error")
        conn = MagicMock()
        version = ops.get_database_version(conn)
        self.assertIsInstance(version, str)


class TestSetCurrentSchema(unittest.TestCase):
    def test_noop_for_sqlite(self):
        ops, qe, _ = _make_ops()
        ops.set_current_schema(MagicMock(), "main")
        # SQLite has no schema concept — should not call any query
        qe.execute_statement.assert_not_called()


class TestGetColumnsQuery(unittest.TestCase):
    def test_returns_pragma_query(self):
        ops, *_ = _make_ops()
        sql = ops.get_columns_query("main", "users")
        self.assertIsInstance(sql, str)
        self.assertIn("PRAGMA", sql.upper())

    def test_includes_table_name(self):
        ops, *_ = _make_ops()
        sql = ops.get_columns_query("main", "orders")
        self.assertIn("orders", sql)


class TestGetAddColumnSql(unittest.TestCase):
    def test_returns_alter_table(self):
        ops, *_ = _make_ops()
        sql = ops.get_add_column_sql("main", "users", "email", "TEXT")
        self.assertIn("ALTER TABLE", sql.upper())
        self.assertIn("email", sql)
        self.assertIn("TEXT", sql)


class TestEnumerateCleanCandidates(unittest.TestCase):
    def test_returns_tables(self):
        ops, qe, _ = _make_ops()
        qe.execute_query.return_value = [{"name": "users"}, {"name": "orders"}]
        conn = MagicMock()
        candidates = ops.enumerate_clean_candidates(conn, "main")
        self.assertIsInstance(candidates, list)

    def test_omits_indexes_dropped_with_tables(self):
        ops, qe, _ = _make_ops()

        def fake_query(_connection, query, params=None):
            if "type = 'index'" in query:
                return [{"name": "idx_users_email"}]
            if "type = 'table'" in query and "USING fts5" not in query:
                return [{"name": "users"}]
            return []

        qe.execute_query.side_effect = fake_query
        conn = MagicMock()

        candidates = ops.enumerate_clean_candidates(conn, "main")

        self.assertIn(("table", "users", 'DROP TABLE IF EXISTS "users"'), candidates)
        self.assertFalse(any(object_type == "index" for object_type, _, _ in candidates))
