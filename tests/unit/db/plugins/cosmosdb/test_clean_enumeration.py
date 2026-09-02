"""CosmosDB clean candidate enumeration."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from dblift.db.provider_interfaces import DroppableObject


@pytest.fixture
def _cosmos_provider():
    from dblift.db.plugins.cosmosdb.provider import CosmosDbProvider

    provider = CosmosDbProvider.__new__(CosmosDbProvider)
    provider.schema_operations = MagicMock()
    return provider


@pytest.mark.unit
class TestCosmosDbDroppableObjectEnumeration:
    def test_lists_containers_in_clean_order(self, _cosmos_provider):
        _cosmos_provider.schema_operations.list_containers.return_value = [
            "users",
            "orders",
            "dblift_schema_history",
            "dblift_migration_lock",
        ]

        objects = _cosmos_provider.list_droppable_objects("ignored")

        assert objects == [
            DroppableObject(
                name="users",
                object_type="CONTAINER",
                drop_sql="database.delete_container('users')",
            ),
            DroppableObject(
                name="orders",
                object_type="CONTAINER",
                drop_sql="database.delete_container('orders')",
            ),
            DroppableObject(
                name="dblift_schema_history",
                object_type="CONTAINER",
                drop_sql="database.delete_container('dblift_schema_history')",
            ),
            DroppableObject(
                name="dblift_migration_lock",
                object_type="CONTAINER",
                drop_sql="database.delete_container('dblift_migration_lock')",
            ),
        ]
        _cosmos_provider.schema_operations.list_containers.assert_called_once_with()
        _cosmos_provider.schema_operations.delete_container.assert_not_called()

    def test_empty_database_returns_no_objects(self, _cosmos_provider):
        _cosmos_provider.schema_operations.list_containers.return_value = []

        assert _cosmos_provider.list_droppable_objects("ignored") == []
        _cosmos_provider.schema_operations.delete_container.assert_not_called()
