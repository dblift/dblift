"""Unit tests for ? placeholder substitution in CosmosDB query executor."""

import logging
from unittest.mock import MagicMock

import pytest


def _make_executor():
    from db.plugins.cosmosdb.cosmosdb.query_executor import CosmosDbQueryExecutor

    executor = CosmosDbQueryExecutor.__new__(CosmosDbQueryExecutor)
    executor.log = logging.getLogger("test")
    executor.connection_manager = MagicMock()
    return executor


@pytest.mark.unit
class TestExecuteQueryParamSubstitution:
    def test_question_mark_params_substituted_before_query(self):
        """? placeholders must be inlined before the SQL reaches CosmosDB."""
        executor = _make_executor()

        captured_sql = []
        mock_container = MagicMock()
        mock_container.query_items.side_effect = (
            lambda query, **kw: captured_sql.append(query) or []
        )
        executor.connection_manager.get_container_client.return_value = mock_container

        executor.execute_query(
            connection=None,
            sql="SELECT c.snapshot_id FROM dblift_schema_snapshots c WHERE c.snapshot_id = ?",
            params=["abc-123"],
        )

        assert captured_sql, "query_items was not called"
        assert "?" not in captured_sql[0], f"? still present in query: {captured_sql[0]}"
        assert "'abc-123'" in captured_sql[0], f"param not inlined: {captured_sql[0]}"

    def test_no_params_passes_sql_unchanged(self):
        """When params=None, SQL must reach CosmosDB without modification."""
        executor = _make_executor()

        captured_sql = []
        mock_container = MagicMock()
        mock_container.query_items.side_effect = (
            lambda query, **kw: captured_sql.append(query) or []
        )
        executor.connection_manager.get_container_client.return_value = mock_container

        executor.execute_query(
            connection=None,
            sql="SELECT c.snapshot_id FROM dblift_schema_snapshots c",
            params=None,
        )

        assert captured_sql
        assert "?" not in captured_sql[0]

    def test_empty_params_list_with_no_placeholders_passes_through(self):
        executor = _make_executor()
        captured_sql = []
        mock_container = MagicMock()
        mock_container.query_items.side_effect = (
            lambda query, **kw: captured_sql.append(query) or []
        )
        executor.connection_manager.get_container_client.return_value = mock_container

        executor.execute_query(
            connection=None,
            sql="SELECT c.snapshot_id FROM dblift_schema_snapshots c",
            params=[],
        )
        assert captured_sql
        assert "?" not in captured_sql[0]

    def test_multiple_params_all_substituted(self):
        executor = _make_executor()
        captured_sql = []
        mock_container = MagicMock()
        mock_container.query_items.side_effect = (
            lambda query, **kw: captured_sql.append(query) or []
        )
        executor.connection_manager.get_container_client.return_value = mock_container

        executor.execute_query(
            connection=None,
            sql="SELECT c.id FROM tbl c WHERE c.a = ? AND c.b = ?",
            params=["foo", "bar"],
        )
        assert captured_sql
        assert "?" not in captured_sql[0]
        assert "'foo'" in captured_sql[0]
        assert "'bar'" in captured_sql[0]

    def test_integer_param_inlined_without_quotes(self):
        executor = _make_executor()
        captured_sql = []
        mock_container = MagicMock()
        mock_container.query_items.side_effect = (
            lambda query, **kw: captured_sql.append(query) or []
        )
        executor.connection_manager.get_container_client.return_value = mock_container

        executor.execute_query(
            connection=None,
            sql="SELECT c.id FROM tbl c WHERE c.count = ?",
            params=[42],
        )
        assert captured_sql
        assert "42" in captured_sql[0]
        assert "?" not in captured_sql[0]


@pytest.mark.unit
class TestExecuteInsertParamSubstitution:
    def test_question_mark_params_substituted_in_insert(self):
        """? placeholders in INSERT VALUES must be inlined before VALUES parsing."""
        executor = _make_executor()

        created_docs = []
        mock_container = MagicMock()
        mock_container.create_item.side_effect = lambda body, **kw: created_docs.append(body)
        # read() must not raise so the container-readiness check passes
        mock_container.read.return_value = {}
        executor.connection_manager.get_container_client.return_value = mock_container

        executor._execute_insert(
            sql=(
                "INSERT INTO dblift_schema_snapshots "
                "(snapshot_id, captured_at, checksum, model_data) "
                "VALUES (?, ?, ?, ?)"
            ),
            params=["snap-uuid", "2026-04-25T00:00:00", "abc123", "bW9kZWw="],
        )

        assert created_docs, "create_item was not called"
        doc = created_docs[0]
        assert doc["snapshot_id"] == "snap-uuid"
        assert doc["captured_at"] == "2026-04-25T00:00:00"
        assert doc["checksum"] == "abc123"
        assert doc["model_data"] == "bW9kZWw="
        assert doc["id"] == "snap-uuid"  # auto-set from first column (snapshot_id)


@pytest.mark.unit
class TestCosmosParameterPlaceholderContract:
    def test_provider_uses_question_mark_placeholders(self):
        from db.plugins.cosmosdb.provider import CosmosDbProvider

        provider = CosmosDbProvider.__new__(CosmosDbProvider)

        assert provider.get_parameter_placeholders(3) == "?, ?, ?"

    def test_schema_operations_uses_question_mark_placeholders(self):
        from db.plugins.cosmosdb.cosmosdb.schema_operations import CosmosDbSchemaOperations

        operations = CosmosDbSchemaOperations.__new__(CosmosDbSchemaOperations)

        assert operations.get_parameter_placeholders(2) == "?, ?"


@pytest.mark.unit
class TestExecuteDeleteParamSubstitution:
    def test_in_clause_params_are_substituted_and_aliased(self):
        """Snapshot pruning DELETE ... IN (?, ?) must reach Cosmos as valid SQL."""
        executor = _make_executor()

        captured_sql = []
        mock_container = MagicMock()
        # dblift_schema_snapshots uses /id as its partition key path
        mock_container.read.return_value = {"partitionKey": {"paths": ["/id"]}}
        mock_container.query_items.side_effect = lambda query, **kw: captured_sql.append(query) or [
            {"id": "snap-1"},
            {"id": "snap-2"},
        ]
        executor.connection_manager.get_container_client.return_value = mock_container

        deleted = executor._execute_delete(
            sql="DELETE FROM dblift_schema_snapshots WHERE snapshot_id IN (?, ?)",
            params=["snap-1", "snap-2"],
        )

        assert deleted == 2
        assert captured_sql
        assert "?" not in captured_sql[0]
        assert "c.snapshot_id IN ('snap-1', 'snap-2')" in captured_sql[0]
        mock_container.delete_item.assert_any_call(item="snap-1", partition_key="snap-1")
        mock_container.delete_item.assert_any_call(item="snap-2", partition_key="snap-2")


@pytest.mark.unit
class TestExecuteDeleteNotFoundHandling:
    def test_404_on_delete_item_logs_debug_not_warning(self):
        """When delete_item raises a 404-like exception (stale read after repair),
        the exception must be logged at DEBUG, not WARNING."""
        import logging
        from unittest.mock import call, patch

        executor = _make_executor()

        mock_log = MagicMock()
        executor.log = mock_log

        mock_container = MagicMock()
        # query_items returns one document
        mock_container.query_items.return_value = [{"id": "d58f1692-stale", "_partitionKey": None}]
        # delete_item raises a 404-style exception
        mock_container.delete_item.side_effect = Exception("(None) Resource Not Found. 404")
        executor.connection_manager.get_container_client.return_value = mock_container

        with patch(
            "db.plugins.cosmosdb.cosmosdb.query_executor.NONE_PARTITION_KEY",
            None,
            create=True,
        ):
            executor._execute_delete("DELETE FROM c WHERE c.type = 'stale'")

        # debug must be called for the 404; warning must NOT be called
        warning_calls = [str(c) for c in mock_log.warning.call_args_list]
        assert mock_log.debug.called, "Expected log.debug for 404 (already-deleted doc)"
        assert not any(
            "Error deleting" in w for w in warning_calls
        ), f"log.warning must not contain 'Error deleting' for a 404 — got: {warning_calls}"
