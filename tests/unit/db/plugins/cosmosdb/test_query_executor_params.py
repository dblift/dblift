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
            sql="SELECT c.event_id FROM app_events c WHERE c.event_id = ?",
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
            sql="SELECT c.event_id FROM app_events c",
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
            sql="SELECT c.event_id FROM app_events c",
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
class TestCosmosParameterPlaceholderContract:
    def test_provider_uses_question_mark_placeholders(self):
        from db.plugins.cosmosdb.provider import CosmosDbProvider

        provider = CosmosDbProvider.__new__(CosmosDbProvider)

        assert provider.get_parameter_placeholders(3) == "?, ?, ?"

    def test_schema_operations_uses_question_mark_placeholders(self):
        from db.plugins.cosmosdb.cosmosdb.schema_operations import CosmosDbSchemaOperations

        operations = CosmosDbSchemaOperations.__new__(CosmosDbSchemaOperations)

        assert operations.get_parameter_placeholders(2) == "?, ?"
