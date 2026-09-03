"""Tests for db/plugins/base_query_executor.py."""

import unittest
from unittest.mock import MagicMock


def _make_concrete():
    from dblift.db.plugins.base_query_executor import BaseQueryExecutor

    class Concrete(BaseQueryExecutor):
        def execute_statement(self, conn, sql, params=None, return_generated_keys=False):
            return 0

        def execute_query(self, conn, sql, params=None):
            return []

        def table_exists(self, conn, schema, table):
            return False

        def get_column_names(self, conn, schema, table):
            return []

    cm = MagicMock()
    log = MagicMock()
    return Concrete(connection_manager=cm, log=log), cm, log


class TestBaseQueryExecutorInit(unittest.TestCase):
    def test_stores_connection_manager(self):
        exec_, cm, _ = _make_concrete()
        self.assertIs(exec_.connection_manager, cm)

    def test_null_log_default(self):
        from dblift.core.logger import NullLog
        from dblift.db.plugins.base_query_executor import BaseQueryExecutor

        class Minimal(BaseQueryExecutor):
            def execute_statement(self, c, s, p=None, r=False):
                return 0

            def execute_query(self, c, s, p=None):
                return []

            def table_exists(self, c, s, t):
                return False

            def get_column_names(self, c, s, t):
                return []

        e = Minimal(MagicMock(), None)
        self.assertIsInstance(e.log, NullLog)


class TestValidateConnection(unittest.TestCase):
    def test_none_raises(self):
        exec_, *_ = _make_concrete()
        with self.assertRaises(RuntimeError):
            exec_._validate_connection(None)

    def test_closed_raises(self):
        exec_, *_ = _make_concrete()
        conn = MagicMock()
        conn.isClosed.return_value = True
        with self.assertRaises(RuntimeError):
            exec_._validate_connection(conn)

    def test_open_passes(self):
        exec_, *_ = _make_concrete()
        conn = MagicMock()
        conn.isClosed.return_value = False
        exec_._validate_connection(conn)  # no raise


class TestIdentifierQuoting(unittest.TestCase):
    def test_default_double_quotes(self):
        exec_, *_ = _make_concrete()
        open_q, close_q, esc = exec_._identifier_quote_chars()
        self.assertEqual(open_q, '"')
        self.assertEqual(close_q, '"')

    def test_get_quoted_schema_name(self):
        exec_, *_ = _make_concrete()
        result = exec_.get_quoted_schema_name("public")
        self.assertEqual(result, '"public"')

    def test_get_schema_qualified_name(self):
        exec_, *_ = _make_concrete()
        result = exec_.get_schema_qualified_name("public", "users")
        self.assertEqual(result, '"public"."users"')

    def test_quoted_schema_escapes_existing_quotes(self):
        exec_, *_ = _make_concrete()
        # A schema name with a double-quote should be escaped
        result = exec_.get_quoted_schema_name('my"schema')
        self.assertIn('"my', result)
