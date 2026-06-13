"""CosmosDB clean drops every container exactly once."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def _cosmos_provider():
    """Instantiate CosmosDbProvider bypassing __init__ to avoid SDK imports.

    The import of ``CosmosDbProvider`` itself pulls in the Azure SDK only at
    call time (module-level is safe), so we use ``__new__`` to skip the
    real constructor and inject stubs for the attributes ``clean_schema``
    actually touches.
    """
    from db.plugins.cosmosdb.provider import CosmosDbProvider

    provider = CosmosDbProvider.__new__(CosmosDbProvider)
    provider.log = MagicMock()
    return provider


def _install_cleanup_stubs(provider, container_names: list[str]):
    """Wire up just enough of the CosmosDB side for ``clean_schema`` to run."""
    delete_calls: list[str] = []

    def _delete_container(name: str) -> bool:
        delete_calls.append(name)
        return True

    provider.schema_operations = MagicMock()
    provider.schema_operations.list_containers.return_value = container_names
    provider.schema_operations.delete_container.side_effect = _delete_container

    provider.connection_manager = MagicMock()

    return delete_calls


@pytest.mark.unit
class TestCosmosDbCleanDropsAllContainers:
    def test_internal_containers_are_dropped(self, _cosmos_provider):
        """``clean`` must remove dblift-managed containers too."""
        delete_calls = _install_cleanup_stubs(
            _cosmos_provider,
            container_names=[
                "users",
                "orders",
                "products",
                "audit",
                "dblift_schema_history",
                "dblift_schema_snapshots",
                "dblift_migration_lock",
            ],
        )

        summary = _cosmos_provider.clean_schema("ignored")

        expected = [
            "users",
            "orders",
            "products",
            "audit",
            "dblift_schema_history",
            "dblift_schema_snapshots",
            "dblift_migration_lock",
        ]
        assert sorted(delete_calls) == sorted(expected)
        assert sorted(obj.name for obj in summary.objects) == sorted(expected)
        assert all(obj.object_type == "CONTAINER" for obj in summary.objects)

    def test_summary_records_internal_containers_as_containers(self, _cosmos_provider):
        """Internal containers are not represented as row-level HISTORY deletes."""
        _install_cleanup_stubs(
            _cosmos_provider,
            container_names=[
                "users",
                "dblift_schema_history",
                "dblift_schema_snapshots",
                "dblift_migration_lock",
            ],
        )

        summary = _cosmos_provider.clean_schema("ignored")

        assert not any(obj.object_type == "HISTORY" for obj in summary.objects)
        assert sorted((obj.object_type, obj.name) for obj in summary.objects) == [
            ("CONTAINER", "dblift_migration_lock"),
            ("CONTAINER", "dblift_schema_history"),
            ("CONTAINER", "dblift_schema_snapshots"),
            ("CONTAINER", "users"),
        ]

    def test_empty_database_records_no_objects(self, _cosmos_provider):
        """An empty Cosmos database produces an empty clean summary."""
        delete_calls = _install_cleanup_stubs(
            _cosmos_provider,
            container_names=[],
        )

        summary = _cosmos_provider.clean_schema("ignored")
        assert delete_calls == []
        assert summary.objects == []


@pytest.mark.unit
class TestCosmosDbCleanPreview:
    def test_provider_preview_delegates_to_schema_operations(self, _cosmos_provider):
        expected = MagicMock()
        _cosmos_provider.schema_operations = MagicMock()
        _cosmos_provider.schema_operations.get_clean_preview.return_value = expected

        assert _cosmos_provider.get_clean_preview("ignored") is expected
        _cosmos_provider.schema_operations.get_clean_preview.assert_called_once_with("ignored")

    def test_preview_uses_container_listing_without_deleting(self):
        from db.plugins.cosmosdb.cosmosdb.schema_operations import CosmosDbSchemaOperations

        operations = CosmosDbSchemaOperations.__new__(CosmosDbSchemaOperations)
        containers = ["users", "orders", "dblift_schema_history", "dblift_migration_lock"]
        operations.list_containers = MagicMock(return_value=containers)

        summary = operations.get_clean_preview("ignored")

        operations.list_containers.assert_called_once_with()
        assert sorted((obj.object_type, obj.name) for obj in summary.objects) == [
            ("CONTAINER", "dblift_migration_lock"),
            ("CONTAINER", "dblift_schema_history"),
            ("CONTAINER", "orders"),
            ("CONTAINER", "users"),
        ]
        assert "DROP CONTAINER users" in summary.statements
        assert "DROP CONTAINER dblift_schema_history" in summary.statements
        assert "DROP CONTAINER dblift_migration_lock" in summary.statements

    def test_preview_includes_only_internal_containers_when_they_are_all_that_exists(self):
        from db.plugins.cosmosdb.cosmosdb.schema_operations import CosmosDbSchemaOperations

        operations = CosmosDbSchemaOperations.__new__(CosmosDbSchemaOperations)
        operations.list_containers = MagicMock(
            return_value=[
                "dblift_schema_history",
                "dblift_schema_snapshots",
                "dblift_migration_lock",
            ]
        )

        summary = operations.get_clean_preview("ignored")

        assert sorted(obj.name for obj in summary.objects) == [
            "dblift_migration_lock",
            "dblift_schema_history",
            "dblift_schema_snapshots",
        ]
        assert all(obj.object_type == "CONTAINER" for obj in summary.objects)
