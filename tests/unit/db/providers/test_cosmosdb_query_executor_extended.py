"""Extended tests for db/plugins/cosmosdb/cosmosdb/query_executor.py."""

import unittest
from unittest.mock import MagicMock


def _make_executor():
    from db.plugins.cosmosdb.cosmosdb.query_executor import CosmosDbQueryExecutor

    cm = MagicMock()
    cm.database = MagicMock()
    cm.config = MagicMock()
    cm.config.database.database_name = "mydb"
    cm.config.database.database = "mydb"
    log = MagicMock()
    return CosmosDbQueryExecutor(connection_manager=cm, log=log), cm, log


class TestExecuteStatementBranches(unittest.TestCase):
    def _make(self):
        return _make_executor()

    def test_scalar_select_no_from_returns_zero(self):
        exec_, cm, _ = self._make()
        conn = MagicMock()
        result = exec_.execute_statement(conn, "SELECT 1")
        self.assertEqual(result, 0)

    def test_select_count_no_from(self):
        exec_, cm, _ = self._make()
        conn = MagicMock()
        result = exec_.execute_statement(conn, "SELECT COUNT(*)")
        self.assertEqual(result, 0)


class TestExecuteQueryBranches(unittest.TestCase):
    def _make(self):
        return _make_executor()

    def test_select_from_executes_query(self):
        exec_, cm, _ = self._make()
        conn = MagicMock()
        exec_.execute_query = MagicMock(return_value=[{"id": 1}])
        result = exec_.execute_statement(conn, "SELECT * FROM users WHERE id = 1")
        # Should dispatch to execute_query for SELECT FROM
        self.assertIsNotNone(result)
