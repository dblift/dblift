"""Unit tests for CosmosDbQueryExecutor.

Focus: uncovered paths that don't require a live Azure endpoint.
- execute_statement (read-only contract: scalar SELECT probe, SELECT
  delegation, NoSqlWriteNotSupportedError for writes)
- execute_query routing (scalar SELECT short-circuit, container extraction, params)
- _substitute_params (various value types, error on mismatch)
- _extract_container_from_query
- _normalize_cosmos_sql
- upsert_native_item (the native document-write path callers use instead of
  routing DML through execute_statement, which only ever reads)
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

    def test_select_from_with_alias(self):
        self.assertEqual("orders", self._ext("SELECT c.id FROM orders c WHERE c.id = 1"))

    def test_returns_none_without_a_from_clause(self):
        self.assertIsNone(self._ext("SELECT VALUE 1"))

    def test_write_forms_are_not_recognised(self):
        """Only reads reach this executor; INTO/UPDATE are not container hints."""
        self.assertIsNone(self._ext("INSERT INTO history (id, val) VALUES (1, 2)"))
        self.assertIsNone(self._ext("UPDATE users SET name = 'x'"))


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


# ---------------------------------------------------------------------------
# upsert_native_item
# ---------------------------------------------------------------------------
#
# execute_statement's docstring tells callers that writes go through the
# Azure SDK, not SQL -- but the only SDK escape hatch it names is a
# user-written Python migration's context.db/context.raw_client. An internal
# caller outside a migration (e.g. a snapshot-persistence extension) has no
# such context and, before this method existed, had no native path either: it
# built a plain SQL INSERT and routed it through execute_statement, which
# raises NoSqlWriteNotSupportedError for anything but a SELECT. That silently
# broke CosmosDB snapshot persistence (migrate succeeds, the snapshot write
# never lands, and the failure is swallowed by the best-effort event listener
# that calls it) -- see the ADR-0032 pseudo-SQL removal, which ported the
# container-create seam (create_snapshot_table_if_not_exists) to a native
# SDK call but missed the row-write seam.


class TestUpsertNativeItem(unittest.TestCase):

    def _make(self):
        return _make_executor()

    def test_calls_upsert_item_on_the_correct_container(self):
        ex = self._make()
        container_client = MagicMock()
        ex.connection_manager.get_container_client.return_value = container_client

        document = {"snapshot_id": "abc-123", "captured_at": "2026-07-28T00:00:00Z"}
        ex.upsert_native_item("dblift_schema_snapshots", document)

        ex.connection_manager.get_container_client.assert_called_once_with(
            "dblift_schema_snapshots"
        )
        container_client.upsert_item.assert_called_once_with(body=document)

    def test_returns_the_upserted_item_from_the_sdk(self):
        ex = self._make()
        container_client = MagicMock()
        sdk_echo = {"snapshot_id": "abc-123", "_etag": '"0000-abcd"'}
        container_client.upsert_item.return_value = sdk_echo
        ex.connection_manager.get_container_client.return_value = container_client

        result = ex.upsert_native_item("dblift_schema_snapshots", {"snapshot_id": "abc-123"})

        self.assertEqual(sdk_echo, result)

    def test_does_not_go_through_execute_statement_or_sql(self):
        """Regression guard: this must be a direct SDK call, not a
        rendered-SQL path that would hit the same NoSqlWriteNotSupportedError
        this method exists to avoid."""
        ex = self._make()
        container_client = MagicMock()
        ex.connection_manager.get_container_client.return_value = container_client

        ex.upsert_native_item("dblift_schema_snapshots", {"snapshot_id": "x"})

        container_client.query_items.assert_not_called()


# ---------------------------------------------------------------------------
# delete_native_item
# ---------------------------------------------------------------------------
#
# upsert_native_item closed the write half of the schema-snapshot gap; the
# sibling monorepo's SchemaSnapshotRepository also prunes old snapshots
# (delete_old_snapshots / _delete_all_snapshots) by rendering a plain SQL
# DELETE and routing it through execute_statement -- which raises the
# identical NoSqlWriteNotSupportedError for CosmosDB, since a delete is a
# write like any other. This is the matching native, non-SQL escape hatch for
# removing a single document by id, so the monorepo's pruning path can be
# wired the same way the single-document write was.


class TestDeleteNativeItem(unittest.TestCase):

    def _make(self):
        return _make_executor()

    def test_calls_delete_item_on_the_correct_container(self):
        ex = self._make()
        container_client = MagicMock()
        ex.connection_manager.get_container_client.return_value = container_client

        ex.delete_native_item("dblift_schema_snapshots", "abc-123", partition_key="abc-123")

        ex.connection_manager.get_container_client.assert_called_once_with(
            "dblift_schema_snapshots"
        )
        container_client.delete_item.assert_called_once_with(
            item="abc-123", partition_key="abc-123"
        )

    def test_partition_key_need_not_match_item_id(self):
        """The partition key path is a property of the container, not
        necessarily the same value as the document's own id -- callers must
        be able to pass whatever the container's actual partition key value
        is, not have this method assume it always equals item_id."""
        ex = self._make()
        container_client = MagicMock()
        ex.connection_manager.get_container_client.return_value = container_client

        ex.delete_native_item("dblift_schema_snapshots", "abc-123", partition_key="tenant-42")

        container_client.delete_item.assert_called_once_with(
            item="abc-123", partition_key="tenant-42"
        )

    def test_does_not_go_through_execute_statement_or_sql(self):
        """Regression guard: this must be a direct SDK call, not a
        rendered-SQL path that would hit the same NoSqlWriteNotSupportedError
        this method exists to avoid."""
        ex = self._make()
        container_client = MagicMock()
        ex.connection_manager.get_container_client.return_value = container_client

        ex.delete_native_item("dblift_schema_snapshots", "abc-123", partition_key="abc-123")

        container_client.query_items.assert_not_called()


# ---------------------------------------------------------------------------
# list_native_items
# ---------------------------------------------------------------------------
#
# DocumentStoreProvider.list_native_items declares "return every document in
# *collection*"; CosmosDbProvider implemented upsert_native_item and
# delete_native_item but not this one, so isinstance(provider,
# DocumentStoreProvider) answered False for CosmosDB. This issues a native
# SELECT * FROM c through the same container-client access pattern as
# upsert_native_item / delete_native_item above, guarded by table_exists
# first: the SDK's query_items iterator can hang indefinitely against a
# container that does not exist, so this checks existence before ever
# calling query_items rather than relying on catching whatever query_items
# eventually does.


class TestListNativeItems(unittest.TestCase):

    def _make(self):
        return _make_executor()

    def test_returns_every_document_in_the_container(self):
        ex = self._make()
        ex.table_exists = MagicMock(return_value=True)
        container = _make_container_mock(items=[{"id": "a"}, {"id": "b"}, {"id": "c"}])
        ex.connection_manager.get_container_client.return_value = container

        result = ex.list_native_items("dblift_schema_snapshots")

        self.assertEqual([{"id": "a"}, {"id": "b"}, {"id": "c"}], result)

    def test_uses_the_correct_container(self):
        ex = self._make()
        ex.table_exists = MagicMock(return_value=True)
        container = _make_container_mock(items=[])
        ex.connection_manager.get_container_client.return_value = container

        ex.list_native_items("dblift_schema_snapshots")

        ex.connection_manager.get_container_client.assert_called_once_with(
            "dblift_schema_snapshots"
        )

    def test_empty_container_returns_empty_list(self):
        ex = self._make()
        ex.table_exists = MagicMock(return_value=True)
        container = _make_container_mock(items=[])
        ex.connection_manager.get_container_client.return_value = container

        result = ex.list_native_items("dblift_schema_snapshots")

        self.assertEqual([], result)

    def test_missing_container_returns_empty_list_without_querying(self):
        """A container that does not exist yields no documents -- matching
        MongoDB's find() on a missing collection -- rather than issuing
        query_items, which can hang indefinitely against a container that
        isn't there."""
        ex = self._make()
        ex.table_exists = MagicMock(return_value=False)
        container = MagicMock()
        ex.connection_manager.get_container_client.return_value = container

        result = ex.list_native_items("does_not_exist")

        self.assertEqual([], result)
        container.query_items.assert_not_called()

    def test_checks_existence_before_binding_to_a_container_client(self):
        ex = self._make()
        ex.table_exists = MagicMock(return_value=True)
        container = _make_container_mock(items=[{"id": "a"}])
        ex.connection_manager.get_container_client.return_value = container

        ex.list_native_items("dblift_schema_snapshots")

        ex.table_exists.assert_called_once_with(None, "", "dblift_schema_snapshots")

    def test_does_not_go_through_execute_statement_or_execute_query(self):
        """Regression guard: this must be a direct SDK call, not a
        rendered-SQL path routed through execute_statement/execute_query."""
        ex = self._make()
        ex.table_exists = MagicMock(return_value=True)
        container = _make_container_mock(items=[{"id": "a"}])
        ex.connection_manager.get_container_client.return_value = container
        ex.execute_statement = MagicMock()
        ex.execute_query = MagicMock()

        ex.list_native_items("dblift_schema_snapshots")

        ex.execute_statement.assert_not_called()
        ex.execute_query.assert_not_called()

    def test_no_order_by_is_added(self):
        """Ordering is not part of the contract -- the protocol says callers
        that need an order impose it themselves, so this must not sneak in
        an ORDER BY the protocol never promised."""
        ex = self._make()
        ex.table_exists = MagicMock(return_value=True)
        captured = []
        container = MagicMock()
        container.query_items.side_effect = lambda query, **kw: captured.append(query) or iter([])
        ex.connection_manager.get_container_client.return_value = container

        ex.list_native_items("dblift_schema_snapshots")

        self.assertTrue(len(captured) > 0)
        self.assertNotIn("ORDER BY", captured[0].upper())


if __name__ == "__main__":
    unittest.main()
