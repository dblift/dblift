"""BUG-04 regression: scalar ``SELECT`` without ``FROM`` must not hit a container.

Callers probe CosmosDB with ``SELECT 1`` (check_connection, migration
smoke-tests). CosmosDB has no server-side ``SELECT <expr>`` without a
container. Before the fix ``execute_statement``/``execute_query`` fell
through to ``_extract_container_from_query`` → defaulted to ``"default"``
→ the client raised "container not found" even though the connection was
perfectly healthy.

The fix short-circuits ``SELECT`` statements that have no ``FROM`` clause:
``execute_statement`` returns 0, ``execute_query`` returns ``[]``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from dblift.db.plugins.cosmosdb.cosmosdb.query_executor import CosmosDbQueryExecutor


@pytest.mark.unit
class TestCosmosDbScalarSelectShortCircuit:
    def _executor(self) -> CosmosDbQueryExecutor:
        exec_ = CosmosDbQueryExecutor.__new__(CosmosDbQueryExecutor)
        exec_.connection_manager = MagicMock()
        exec_.log = MagicMock()
        exec_.container_client = None
        return exec_

    def test_execute_statement_select_1_is_no_op(self):
        exec_ = self._executor()
        result = exec_.execute_statement(connection=None, sql="SELECT 1")
        assert result == 0
        exec_.connection_manager.get_container_client.assert_not_called()

    def test_execute_statement_select_1_with_trailing_semicolon(self):
        exec_ = self._executor()
        assert exec_.execute_statement(connection=None, sql="SELECT 1;") == 0
        exec_.connection_manager.get_container_client.assert_not_called()

    def test_execute_query_select_1_returns_empty(self):
        exec_ = self._executor()
        rows = exec_.execute_query(connection=None, sql="SELECT 1")
        assert rows == []
        exec_.connection_manager.get_container_client.assert_not_called()

    def test_execute_query_select_current_timestamp_no_from(self):
        exec_ = self._executor()
        assert exec_.execute_query(connection=None, sql="SELECT CURRENT_TIMESTAMP") == []
        exec_.connection_manager.get_container_client.assert_not_called()

    def test_real_select_still_goes_through(self):
        """``SELECT * FROM c`` must still hit the container path."""
        exec_ = self._executor()
        container = MagicMock()
        container.query_items.return_value = iter([{"id": "x"}])
        exec_.connection_manager.get_container_client.return_value = container
        exec_._extract_container_from_query = MagicMock(return_value="users")  # type: ignore[assignment]
        exec_._normalize_cosmos_sql = MagicMock(return_value="SELECT * FROM c")  # type: ignore[assignment]

        rows = exec_.execute_query(connection=None, sql="SELECT * FROM users")
        assert rows == [{"id": "x"}]
        exec_.connection_manager.get_container_client.assert_called_once_with("users")
