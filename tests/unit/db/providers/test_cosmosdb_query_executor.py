"""Unit tests for CosmosDbQueryExecutor.

Focus: uncovered paths that don't require a live Azure endpoint.
- execute_statement (read-only contract: scalar SELECT probe, SELECT
  delegation, NoSqlWriteNotSupportedError for writes)
- execute_query routing (scalar SELECT short-circuit, container extraction, params)
- _substitute_params (various value types, error on mismatch)
- _extract_container_from_query
- _normalize_cosmos_sql
"""

import unittest
from unittest.mock import MagicMock

from core.exceptions import NoSqlWriteNotSupportedError


def _make_executor(log=None):
    """Build a CosmosDbQueryExecutor without touching any real Azure SDK."""
    from db.plugins.cosmosdb.cosmosdb.query_executor import CosmosDbQueryExecutor

    conn_mgr = MagicMock()
    conn_mgr.get_container_client.return_value = MagicMock()
    executor = CosmosDbQueryExecutor(conn_mgr, log or MagicMock())
    return executor


def _make_container_mock(items=None, pk_path="/id"):
    """Return a mock container client."""
    mock = MagicMock()
    mock.read.return_value = {"partitionKey": {"paths": [pk_path]}}
    mock.query_items.return_value = iter(items or [])
    return mock


# ---------------------------------------------------------------------------
# _substitute_params
# ---------------------------------------------------------------------------


class TestSubstituteParams(unittest.TestCase):

    def _sub(self, sql, params):
        from db.plugins.cosmosdb.cosmosdb.query_executor import CosmosDbQueryExecutor

        return CosmosDbQueryExecutor._substitute_params(sql, params)

    def test_string_param_quoted(self):
        result = self._sub("WHERE c.id = ?", ["abc-123"])
        self.assertEqual("WHERE c.id = 'abc-123'", result)

    def test_int_param_not_quoted(self):
        result = self._sub("WHERE c.count = ?", [42])
        self.assertEqual("WHERE c.count = 42", result)

    def test_float_param_not_quoted(self):
        result = self._sub("WHERE c.score = ?", [3.14])
        self.assertIn("3.14", result)

    def test_none_param_becomes_null(self):
        result = self._sub("WHERE c.val = ?", [None])
        self.assertEqual("WHERE c.val = null", result)

    def test_bool_true_becomes_true(self):
        result = self._sub("WHERE c.active = ?", [True])
        self.assertEqual("WHERE c.active = true", result)

    def test_bool_false_becomes_false(self):
        result = self._sub("WHERE c.active = ?", [False])
        self.assertEqual("WHERE c.active = false", result)

    def test_string_with_single_quote_is_escaped(self):
        result = self._sub("WHERE c.name = ?", ["O'Brien"])
        self.assertIn("O''Brien", result)

    def test_mismatch_raises_value_error(self):
        with self.assertRaises(ValueError):
            self._sub("WHERE c.id = ? AND c.val = ?", ["only-one"])

    def test_no_placeholders_returns_unchanged(self):
        sql = "SELECT c.id FROM c WHERE c.id = 'known'"
        result = self._sub(sql, [])
        self.assertEqual(sql, result)

    def test_multiple_params_all_inlined(self):
        result = self._sub("? AND ?", ["foo", "bar"])
        self.assertIn("'foo'", result)
        self.assertIn("'bar'", result)
        self.assertNotIn("?", result)


# ---------------------------------------------------------------------------
# _extract_container_from_query
# ---------------------------------------------------------------------------


class TestExtractContainerFromQuery(unittest.TestCase):

    def _ext(self, sql):
        return _make_executor()._extract_container_from_query(sql)

    def test_select_from(self):
        self.assertEqual("orders", self._ext("SELECT * FROM orders WHERE id = 1"))

    def test_insert_into(self):
        self.assertEqual("history", self._ext("INSERT INTO history (id, val) VALUES (1, 2)"))

    def test_update_container(self):
        self.assertEqual("users", self._ext("UPDATE users SET name = 'x'"))

    def test_delete_from(self):
        self.assertEqual("log", self._ext("DELETE FROM log WHERE id = 1"))

    def test_returns_none_for_unrecognized(self):
        # EXEC has neither FROM nor INTO
        result = self._ext("EXEC myproc")
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# execute_statement routing
# ---------------------------------------------------------------------------


class TestExecuteStatementRouting(unittest.TestCase):

    def _make(self):
        return _make_executor()

    def test_scalar_select_without_from_returns_zero(self):
        ex = self._make()
        result = ex.execute_statement(None, "SELECT 1")
        self.assertEqual(0, result)

    def test_scalar_select_with_semicolon_stripped_returns_zero(self):
        ex = self._make()
        result = ex.execute_statement(None, "SELECT CURRENT_TIMESTAMP;")
        self.assertEqual(0, result)

    def test_scalar_select_with_comments_stripped(self):
        ex = self._make()
        # comment precedes the SELECT
        result = ex.execute_statement(None, "-- health check\nSELECT 1")
        self.assertEqual(0, result)


# ---------------------------------------------------------------------------
# execute_statement read-only contract
# ---------------------------------------------------------------------------


class TestExecuteStatementReadOnlyContract(unittest.TestCase):
    """execute_statement reads only; writes go through the Azure SDK."""

    def _make(self):
        return _make_executor()

    def test_scalar_select_is_liveness_probe_returning_zero(self):
        ex = self._make()
        ex.execute_query = MagicMock()
        self.assertEqual(0, ex.execute_statement(None, "SELECT 1"))
        # A probe must not bind to any container.
        ex.execute_query.assert_not_called()

    def test_select_from_delegates_to_execute_query_and_returns_row_count(self):
        ex = self._make()
        ex.execute_query = MagicMock(return_value=[{"id": "a"}, {"id": "b"}, {"id": "c"}])

        result = ex.execute_statement(None, "SELECT * FROM c")

        self.assertEqual(3, result)
        ex.execute_query.assert_called_once_with(None, "SELECT * FROM c", None)

    def test_select_from_with_no_rows_returns_zero(self):
        ex = self._make()
        ex.execute_query = MagicMock(return_value=[])
        self.assertEqual(0, ex.execute_statement(None, "SELECT * FROM users"))

    def test_select_from_passes_params_through(self):
        ex = self._make()
        ex.execute_query = MagicMock(return_value=[{"id": "a"}])

        result = ex.execute_statement(None, "SELECT * FROM c WHERE c.id = ?", params=["a"])

        self.assertEqual(1, result)
        ex.execute_query.assert_called_once_with(None, "SELECT * FROM c WHERE c.id = ?", ["a"])

    def test_insert_raises_nosql_write_not_supported(self):
        self._assert_write_rejected("INSERT INTO users (id) VALUES ('1')")

    def test_update_raises_nosql_write_not_supported(self):
        self._assert_write_rejected("UPDATE users SET name = 'x' WHERE id = '1'")

    def test_delete_raises_nosql_write_not_supported(self):
        self._assert_write_rejected("DELETE FROM users WHERE id = '1'")

    def test_create_raises_nosql_write_not_supported(self):
        self._assert_write_rejected("CREATE TABLE users (id VARCHAR(255) PRIMARY KEY)")

    def test_write_is_not_delegated_to_execute_query(self):
        ex = self._make()
        ex.execute_query = MagicMock()
        with self.assertRaises(NoSqlWriteNotSupportedError):
            ex.execute_statement(None, "INSERT INTO users (id) VALUES ('1')")
        ex.execute_query.assert_not_called()

    def _assert_write_rejected(self, sql):
        ex = self._make()
        with self.assertRaises(NoSqlWriteNotSupportedError) as ctx:
            ex.execute_statement(None, sql)
        # The error must point the user at the Azure SDK migration path.
        self.assertIn("azure sdk", str(ctx.exception).lower())


# ---------------------------------------------------------------------------
# execute_query routing
# ---------------------------------------------------------------------------


class TestExecuteQueryRouting(unittest.TestCase):

    def _make(self):
        return _make_executor()

    def test_scalar_select_without_from_returns_empty_list(self):
        ex = self._make()
        result = ex.execute_query(None, "SELECT 1")
        self.assertEqual([], result)

    def test_select_with_from_uses_container_client(self):
        ex = self._make()
        container = _make_container_mock(items=[{"id": "1", "name": "Alice"}])
        ex.connection_manager.get_container_client.return_value = container
        result = ex.execute_query(None, "SELECT c.id, c.name FROM users c")
        self.assertIsInstance(result, list)
        # container_client.query_items should be called
        container.query_items.assert_called()

    def test_result_converted_to_dicts(self):
        ex = self._make()
        container = _make_container_mock(items=[{"id": "abc", "value": 42}])
        ex.connection_manager.get_container_client.return_value = container
        result = ex.execute_query(None, "SELECT c.id FROM tbl c")
        self.assertTrue(all(isinstance(r, dict) for r in result))

    def test_params_substituted_into_sql(self):
        ex = self._make()
        captured = []
        container = MagicMock()
        container.query_items.side_effect = lambda query, **kw: captured.append(query) or []
        ex.connection_manager.get_container_client.return_value = container
        ex.execute_query(None, "SELECT c.id FROM tbl c WHERE c.id = ?", params=["x"])
        self.assertTrue(len(captured) > 0)
        self.assertNotIn("?", captured[0])
        self.assertIn("'x'", captured[0])

    def test_exception_reraised_on_query_error(self):
        ex = self._make()
        container = MagicMock()
        container.query_items.side_effect = RuntimeError("query failed")
        ex.connection_manager.get_container_client.return_value = container
        with self.assertRaises(RuntimeError):
            ex.execute_query(None, "SELECT c.id FROM tbl c")

    def test_no_container_uses_default_from_config(self):
        from unittest.mock import MagicMock as MM

        ex = self._make()
        # Config provides a container name
        from db.plugins.cosmosdb.config import CosmosDbConfig

        mock_db_config = MagicMock(spec=CosmosDbConfig)
        mock_db_config.container_name = "fallback_container"
        ex.connection_manager.config.database = mock_db_config
        container = _make_container_mock(items=[])
        ex.connection_manager.get_container_client.return_value = container
        # SQL without FROM won't trigger this path; use a query that has no FROM but we override
        # Actually test the fallback: a query without FROM for container extraction
        # The easiest path: use a SQL with no FROM and non-scalar (e.g. has subquery comment)
        # Better: test via a mock that strips FROM from an otherwise valid query
        # Let's test a SELECT * from an empty result without FROM → already tested above.
        # Instead: directly test extraction fallback in execute_query by patching
        ex._extract_container_from_query = MagicMock(return_value=None)
        result = ex.execute_query(None, "SELECT * FROM fallback_container c")
        # Should use the config container name
        ex.connection_manager.get_container_client.assert_called_with("fallback_container")


# ---------------------------------------------------------------------------
# _normalize_cosmos_sql
# ---------------------------------------------------------------------------


class TestNormalizeCosmosSql(unittest.TestCase):

    def test_already_aliased_query_returned_as_is(self):
        ex = _make_executor()
        sql = "SELECT c.id, c.name FROM orders c WHERE c.id = '1'"
        result = ex._normalize_cosmos_sql(sql, "orders")
        # Should not double-prefix
        self.assertNotIn("c.c.", result)

    def test_adds_c_alias_to_from_clause(self):
        ex = _make_executor()
        sql = "SELECT * FROM orders"
        result = ex._normalize_cosmos_sql(sql, "orders")
        self.assertIn("FROM orders c", result)

    def test_select_star_stays_as_star(self):
        ex = _make_executor()
        sql = "SELECT * FROM tbl"
        result = ex._normalize_cosmos_sql(sql, "tbl")
        # * should not be prefixed with c.
        self.assertIn("*", result)
        self.assertNotIn("c.*", result)

    def test_non_select_query_returned_as_is(self):
        ex = _make_executor()
        sql = "DELETE FROM c WHERE c.id = '1'"
        result = ex._normalize_cosmos_sql(sql, "c")
        # Non-SELECT passthrough
        self.assertEqual(sql, result)


if __name__ == "__main__":
    unittest.main()
