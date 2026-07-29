"""BUG-COSMOS-01 regression: missing history container must log DEBUG, not ERROR.

A 404 / "not found" exception from get_applied_migrations is a normal state
(first run, post-clean). It must be downgraded to DEBUG so it doesn't leak
error lines to stdout on every command invocation.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from db.plugins.cosmosdb.cosmosdb.history_manager import CosmosDbHistoryManager


@pytest.mark.unit
class TestGetAppliedMigrationsLogging:
    def _manager(self) -> CosmosDbHistoryManager:
        mgr = CosmosDbHistoryManager.__new__(CosmosDbHistoryManager)
        mgr.log = MagicMock()
        mgr.connection_manager = MagicMock()
        mgr._history_containers = {"dblift_schema_history": MagicMock()}
        mgr.HISTORY_CONTAINER_NAME = "dblift_schema_history"
        return mgr

    def test_404_not_found_logs_debug_not_error(self):
        mgr = self._manager()
        mgr._history_containers["dblift_schema_history"].query_items.side_effect = Exception(
            "Collection 'dblift_schema_history' not found in database 'dblift_test'"
        )
        result = mgr.get_applied_migrations(connection=None, schema="dblift_test")
        assert result == []
        mgr.log.debug.assert_called_once()
        mgr.log.error.assert_not_called()
        assert "not found" in mgr.log.debug.call_args[0][0].lower()

    def test_404_numeric_string_logs_debug_not_error(self):
        mgr = self._manager()
        mgr._history_containers["dblift_schema_history"].query_items.side_effect = Exception(
            "Error code: 404"
        )
        result = mgr.get_applied_migrations(connection=None, schema="dblift_test")
        assert result == []
        mgr.log.debug.assert_called_once()
        mgr.log.error.assert_not_called()

    def test_non_404_error_logs_error(self):
        mgr = self._manager()
        mgr._history_containers["dblift_schema_history"].query_items.side_effect = Exception(
            "Connection timeout"
        )
        result = mgr.get_applied_migrations(connection=None, schema="dblift_test")
        assert result == []
        mgr.log.error.assert_called_once()
        mgr.log.debug.assert_not_called()

    def test_success_returns_migration_list(self):
        mgr = self._manager()
        mgr._history_containers["dblift_schema_history"].query_items.return_value = [
            {
                "script": "V1__init.sql",
                "installed_rank": 1,
                "version": "1",
                "description": "init",
                "type": "SQL",
                "checksum": "abc",
                "installed_by": "user",
                "installed_on": "2026-01-01",
                "execution_time": 100,
                "success": True,
            }
        ]
        result = mgr.get_applied_migrations(connection=None, schema="dblift_test")
        assert len(result) == 1
        assert result[0]["script"] == "V1__init.sql"
        mgr.log.error.assert_not_called()


@pytest.mark.unit
class TestRepairMigrationHistory:
    """CosmosDB repair_migration_history must update an existing document."""

    def _manager(self) -> CosmosDbHistoryManager:
        mgr = CosmosDbHistoryManager.__new__(CosmosDbHistoryManager)
        mgr.log = MagicMock()
        mgr.connection_manager = MagicMock()
        mgr._history_containers = {"dblift_schema_history": MagicMock()}
        mgr.HISTORY_CONTAINER_NAME = "dblift_schema_history"
        return mgr

    def test_updates_checksum_and_returns_true(self):
        mgr = self._manager()
        existing_doc = {
            "id": "V1__create_containers.sql",
            "script": "V1__create_containers.sql",
            "checksum": 111111,
            "success": True,
        }
        mgr._history_containers["dblift_schema_history"].read_item.return_value = existing_doc
        result = mgr.repair_migration_history(
            connection=None,
            schema="dblift_test",
            script_name="V1__create_containers.sql",
            checksum=999999,
        )
        assert result is True
        mgr._history_containers["dblift_schema_history"].read_item.assert_called_once_with(
            item="V1__create_containers.sql", partition_key="V1__create_containers.sql"
        )
        upserted = mgr._history_containers["dblift_schema_history"].upsert_item.call_args[1]["body"]
        assert upserted["checksum"] == 999999

    def test_updates_success_flag_when_provided(self):
        mgr = self._manager()
        existing_doc = {"id": "V1__init.sql", "checksum": 0, "success": False}
        mgr._history_containers["dblift_schema_history"].read_item.return_value = existing_doc
        mgr.repair_migration_history(
            connection=None,
            schema="dblift_test",
            script_name="V1__init.sql",
            checksum=42,
            success_value=True,
        )
        upserted = mgr._history_containers["dblift_schema_history"].upsert_item.call_args[1]["body"]
        assert upserted["success"] is True

    def test_returns_false_when_document_not_found(self):
        mgr = self._manager()
        mgr._history_containers["dblift_schema_history"].read_item.side_effect = Exception(
            "404 Not Found"
        )
        result = mgr.repair_migration_history(
            connection=None,
            schema="dblift_test",
            script_name="V1__missing.sql",
            checksum=42,
        )
        assert result is False
        mgr._history_containers["dblift_schema_history"].upsert_item.assert_not_called()
