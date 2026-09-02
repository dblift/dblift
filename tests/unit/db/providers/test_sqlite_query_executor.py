"""Tests for db/plugins/sqlite/sqlite/query_executor.py."""

import sqlite3
import unittest
from unittest.mock import MagicMock


def _make_executor():
    from dblift.db.plugins.sqlite.sqlite.query_executor import SQLiteQueryExecutor

    cm = MagicMock()
    log = MagicMock()
    return SQLiteQueryExecutor(connection_manager=cm, log=log), cm, log


def _make_real_conn():
    """Create an in-memory SQLite connection for testing."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO test VALUES (1, 'alice')")
    conn.execute("INSERT INTO test VALUES (2, 'bob')")
    conn.commit()
    return conn


class TestSQLiteQueryExecutorInit(unittest.TestCase):
    def test_stores_connection_manager(self):
        exec_, cm, _ = _make_executor()
        self.assertIs(exec_.connection_manager, cm)

    def test_null_log_default(self):
        from dblift.core.logger import NullLog
        from dblift.db.plugins.sqlite.sqlite.query_executor import SQLiteQueryExecutor

        exec_ = SQLiteQueryExecutor(MagicMock())
        self.assertIsInstance(exec_.log, NullLog)


class TestValidateConnection(unittest.TestCase):
    def test_none_raises(self):
        exec_, *_ = _make_executor()
        with self.assertRaises(RuntimeError):
            exec_._validate_connection(None)

    def test_valid_passes(self):
        exec_, *_ = _make_executor()
        conn = _make_real_conn()
        try:
            exec_._validate_connection(conn)
        finally:
            conn.close()


class TestExecuteStatement(unittest.TestCase):
    def test_insert_returns_rowcount(self):
        exec_, *_ = _make_executor()
        conn = _make_real_conn()
        try:
            rows = exec_.execute_statement(conn, "INSERT INTO test VALUES (3, 'charlie')")
            self.assertGreaterEqual(rows, 0)
        finally:
            conn.close()

    def test_with_params(self):
        exec_, *_ = _make_executor()
        conn = _make_real_conn()
        try:
            rows = exec_.execute_statement(
                conn, "INSERT INTO test VALUES (?, ?)", params=[4, "dave"]
            )
            self.assertGreaterEqual(rows, 0)
        finally:
            conn.close()

    def test_none_connection_raises(self):
        exec_, *_ = _make_executor()
        with self.assertRaises(RuntimeError):
            exec_.execute_statement(None, "SELECT 1")


class TestExecuteQuery(unittest.TestCase):
    def test_returns_list_of_dicts(self):
        exec_, *_ = _make_executor()
        conn = _make_real_conn()
        try:
            results = exec_.execute_query(conn, "SELECT * FROM test ORDER BY id")
            self.assertIsInstance(results, list)
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0]["name"], "alice")
        finally:
            conn.close()

    def test_with_params(self):
        exec_, *_ = _make_executor()
        conn = _make_real_conn()
        try:
            results = exec_.execute_query(conn, "SELECT * FROM test WHERE id = ?", params=[1])
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["name"], "alice")
        finally:
            conn.close()

    def test_empty_result(self):
        exec_, *_ = _make_executor()
        conn = _make_real_conn()
        try:
            results = exec_.execute_query(conn, "SELECT * FROM test WHERE id = ?", params=[999])
            self.assertEqual(results, [])
        finally:
            conn.close()


class TestTableExists(unittest.TestCase):
    def test_existing_table(self):
        exec_, *_ = _make_executor()
        conn = _make_real_conn()
        try:
            self.assertTrue(exec_.table_exists(conn, "main", "test"))
        finally:
            conn.close()

    def test_nonexistent_table(self):
        exec_, *_ = _make_executor()
        conn = _make_real_conn()
        try:
            self.assertFalse(exec_.table_exists(conn, "main", "nonexistent"))
        finally:
            conn.close()


class TestGetColumnNames(unittest.TestCase):
    def test_returns_column_names(self):
        exec_, *_ = _make_executor()
        conn = _make_real_conn()
        try:
            cols = exec_.get_column_names(conn, "main", "test")
            self.assertIn("id", cols)
            self.assertIn("name", cols)
        finally:
            conn.close()


class TestGetSchemaQualifiedName(unittest.TestCase):
    def test_returns_qualified_name(self):
        exec_, *_ = _make_executor()
        name = exec_.get_schema_qualified_name("main", "users")
        self.assertIn("users", name)
