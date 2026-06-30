"""Unit tests for CosmosDbQueryExecutor.

Focus: uncovered paths that don't require a live Azure endpoint.
- execute_statement routing (scalar SELECT short-circuit, CREATE CONTAINER, INSERT, DELETE, UPDATE)
- execute_query routing (scalar SELECT short-circuit, container extraction, params)
- _substitute_params (various value types, error on mismatch)
- _normalize_where_clause
- _extract_container_from_query
- _normalize_cosmos_sql
- _parse_container_name, _parse_container_options
"""

import unittest
from unittest.mock import MagicMock, patch


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
# _normalize_where_clause
# ---------------------------------------------------------------------------


class TestNormalizeWhereClause(unittest.TestCase):

    def _norm(self, clause):
        return _make_executor()._normalize_where_clause(clause)

    def test_already_aliased_c_prefix_unchanged(self):
        clause = "c.id = '123'"
        result = self._norm(clause)
        self.assertEqual(clause, result)

    def test_adds_c_prefix_to_simple_equality(self):
        result = self._norm("id = '123'")
        self.assertIn("c.id", result)

    def test_adds_c_prefix_to_in_clause(self):
        result = self._norm("type IN ('a', 'b')")
        self.assertIn("c.type", result)


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

    def test_sdk_pattern_drop_container_routes_to_sdk_operation(self):
        ex = self._make()
        # Patch _execute_sdk_operation to avoid real SDK
        ex._execute_sdk_operation = MagicMock(return_value=1)
        result = ex.execute_statement(None, "DROP CONTAINER mycontainer")
        ex._execute_sdk_operation.assert_called_once()
        self.assertEqual(1, result)

    def test_sdk_pattern_create_index_routes_to_sdk_operation(self):
        ex = self._make()
        ex._execute_sdk_operation = MagicMock(return_value=1)
        result = ex.execute_statement(None, "CREATE INDEX idx ON container (path)")
        ex._execute_sdk_operation.assert_called_once()

    def test_insert_routes_to_execute_insert(self):
        ex = self._make()
        ex._execute_insert = MagicMock(return_value=1)
        result = ex.execute_statement(None, "INSERT INTO tbl (id) VALUES (1)")
        ex._execute_insert.assert_called_once()
        self.assertEqual(1, result)

    def test_delete_routes_to_execute_delete(self):
        ex = self._make()
        ex._execute_delete = MagicMock(return_value=2)
        result = ex.execute_statement(None, "DELETE FROM tbl WHERE id = 1")
        ex._execute_delete.assert_called_once()
        self.assertEqual(2, result)

    def test_update_routes_to_execute_update(self):
        ex = self._make()
        ex._execute_update = MagicMock(return_value=3)
        result = ex.execute_statement(None, "UPDATE tbl SET name = 'x' WHERE id = 1")
        ex._execute_update.assert_called_once()
        self.assertEqual(3, result)

    def test_exception_is_reraised(self):
        ex = self._make()
        ex._execute_insert = MagicMock(side_effect=RuntimeError("insert failed"))
        with self.assertRaises(RuntimeError):
            ex.execute_statement(None, "INSERT INTO tbl (id) VALUES (1)")


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
# _execute_delete
# ---------------------------------------------------------------------------


class TestExecuteDelete(unittest.TestCase):

    def test_deletes_matching_documents(self):
        ex = _make_executor()
        container = MagicMock()
        container.read.return_value = {"partitionKey": {"paths": ["/id"]}}
        container.query_items.return_value = iter([{"id": "doc-1"}, {"id": "doc-2"}])
        ex.connection_manager.get_container_client.return_value = container

        count = ex._execute_delete("DELETE FROM tbl WHERE id = 'doc-1'")

        self.assertEqual(2, count)
        self.assertEqual(2, container.delete_item.call_count)

    def test_continues_on_404_not_found(self):
        ex = _make_executor()
        container = MagicMock()
        container.read.return_value = {"partitionKey": {"paths": ["/id"]}}
        container.query_items.return_value = iter([{"id": "doc-1"}])
        container.delete_item.side_effect = Exception("404 Not Found")
        ex.connection_manager.get_container_client.return_value = container

        # Should not raise
        count = ex._execute_delete("DELETE FROM tbl WHERE id = 'doc-1'")
        self.assertEqual(0, count)  # delete was skipped due to 404

    def test_substitute_params_called_for_delete_with_params(self):
        ex = _make_executor()
        container = MagicMock()
        container.read.return_value = {"partitionKey": {"paths": ["/id"]}}
        container.query_items.return_value = iter([])
        ex.connection_manager.get_container_client.return_value = container

        captured = []
        original_query_items = container.query_items
        container.query_items.side_effect = lambda query, **kw: captured.append(query) or []

        ex._execute_delete("DELETE FROM tbl WHERE script = ?", params=["V1.sql"])

        self.assertTrue(len(captured) > 0)
        self.assertNotIn("?", captured[0])
        self.assertIn("V1.sql", captured[0])

    def test_raises_on_invalid_sql(self):
        ex = _make_executor()
        with self.assertRaises(ValueError):
            ex._execute_delete("DELETE tbl WHERE id = 1")  # no FROM

    def test_no_where_clause_deletes_all(self):
        ex = _make_executor()
        container = MagicMock()
        container.read.return_value = {"partitionKey": {"paths": ["/id"]}}
        container.query_items.return_value = iter([{"id": "a"}, {"id": "b"}, {"id": "c"}])
        ex.connection_manager.get_container_client.return_value = container

        count = ex._execute_delete("DELETE FROM tbl")
        self.assertEqual(3, count)


# ---------------------------------------------------------------------------
# _execute_update
# ---------------------------------------------------------------------------


class TestExecuteUpdate(unittest.TestCase):

    def test_updates_matching_documents(self):
        ex = _make_executor()
        container = MagicMock()
        doc = {"id": "1", "name": "Alice"}
        container.query_items.return_value = iter([doc])
        ex.connection_manager.get_container_client.return_value = container

        count = ex._execute_update("UPDATE users SET name = 'Bob' WHERE id = '1'")

        self.assertEqual(1, count)
        container.replace_item.assert_called_once()

    def test_raises_on_missing_container_name(self):
        ex = _make_executor()
        with self.assertRaises(ValueError):
            ex._execute_update("SET name = 'x'")  # no UPDATE clause

    def test_raises_on_missing_set_clause(self):
        ex = _make_executor()
        with self.assertRaises(ValueError):
            ex._execute_update("UPDATE users WHERE id = 1")  # no SET

    def test_raises_on_empty_set_clause(self):
        ex = _make_executor()
        with self.assertRaises(ValueError):
            # No SET clause at all triggers the regex mismatch
            ex._execute_update("UPDATE users WHERE id = 1")

    def test_params_substituted_in_where(self):
        ex = _make_executor()
        container = MagicMock()
        captured = []
        container.query_items.side_effect = lambda query, **kw: captured.append(query) or []
        ex.connection_manager.get_container_client.return_value = container

        ex._execute_update("UPDATE users SET name = 'x' WHERE id = ?", params=["user-1"])

        self.assertTrue(len(captured) > 0)
        self.assertNotIn("?", captured[0])
        self.assertIn("user-1", captured[0])


# ---------------------------------------------------------------------------
# _parse_container_name, _parse_partition_key, _parse_container_options
# ---------------------------------------------------------------------------


class TestParseContainerName(unittest.TestCase):

    def test_extracts_name(self):
        ex = _make_executor()
        name = ex._parse_container_name(
            "CREATE CONTAINER my_table (id STRING) WITH (partitionKey='/id')"
        )
        self.assertEqual("my_table", name)

    def test_raises_when_no_name(self):
        ex = _make_executor()
        with self.assertRaises(ValueError):
            ex._parse_container_name("CREATE CONTAINER")


# TestParsePartitionKey removed in Z-4: _parse_partition_key had no
# production callers. Partition-key parsing is exercised via
# TestParseContainerOptions below (which is what production actually uses).


class TestParseContainerOptions(unittest.TestCase):

    def test_returns_default_when_no_with_clause(self):
        ex = _make_executor()
        opts = ex._parse_container_options("CREATE CONTAINER tbl (id STRING)")
        self.assertEqual("/id", opts["partitionKey"])

    def test_parses_partition_key_from_with_clause(self):
        ex = _make_executor()
        sql = "CREATE CONTAINER tbl (id STRING) WITH (partitionKey='/pk', throughput=400)"
        opts = ex._parse_container_options(sql)
        self.assertEqual("/pk", opts.get("partitionKey"))


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


# ---------------------------------------------------------------------------
# SDK_PATTERNS membership
# ---------------------------------------------------------------------------


class TestSdkPatterns(unittest.TestCase):

    def test_all_expected_patterns_present(self):
        from db.plugins.cosmosdb.cosmosdb.query_executor import CosmosDbQueryExecutor

        patterns = CosmosDbQueryExecutor.SDK_PATTERNS
        for expected in [
            "DROP CONTAINER",
            "ALTER CONTAINER",
            "SET THROUGHPUT",
            "CREATE INDEX",
            "DROP INDEX",
            "SET TTL",
        ]:
            self.assertIn(expected, patterns, f"Missing SDK pattern: {expected}")


if __name__ == "__main__":
    unittest.main()
