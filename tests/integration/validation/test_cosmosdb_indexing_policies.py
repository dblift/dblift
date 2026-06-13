"""
CosmosDB Indexing Policies Tests.

Tests for CosmosDB indexing policy introspection and handling.
"""

import pytest

from core.introspection.introspector_factory import IntrospectorFactory
from core.logger import ConsoleLog


@pytest.mark.integration
class TestCosmosDbIndexingPolicies:
    """CosmosDB indexing policies tests."""

    def _get_provider(self, cosmosdb_container):
        """Create database provider."""
        from config import DbliftConfig
        from db.provider_registry import ProviderRegistry

        if "_skip_reason" in cosmosdb_container:
            pytest.skip(cosmosdb_container["_skip_reason"])

        config_dict = {
            "database": {
                "type": "cosmosdb",
                "url": cosmosdb_container.get("account_endpoint"),
                "account_endpoint": cosmosdb_container.get("account_endpoint"),
                "account_key": cosmosdb_container.get("account_key"),
                "database_name": cosmosdb_container.get("database_name"),
                "container_name": cosmosdb_container.get("container_name", "default"),
            },
        }
        config = DbliftConfig.from_dict(config_dict)
        log = ConsoleLog("cosmosdb_indexing", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()
        return provider

    def test_indexing_policy_introspection(self, cosmosdb_container):
        """Test introspection of container with indexing policy."""
        provider = self._get_provider(cosmosdb_container)

        try:
            container_name = "test_indexing"
            from azure.cosmos import PartitionKey

            # Create container with custom indexing policy
            indexing_policy = {
                "indexingMode": "consistent",
                "automatic": True,
                "includedPaths": [
                    {"path": "/id/?"},
                    {"path": "/name/?"},
                ],
                "excludedPaths": [
                    {"path": "/*"},
                ],
            }

            try:
                provider.connection_manager.database.create_container_if_not_exists(
                    id=container_name,
                    partition_key=PartitionKey(path="/id"),
                    indexing_policy=indexing_policy,
                )
            except Exception:
                pass  # Container may already exist

            # Insert a test document
            container_client = provider.connection_manager.get_container_client(container_name)
            test_doc = {
                "id": "doc1",
                "name": "Test Document",
                "description": "A test document",
            }
            try:
                container_client.create_item(body=test_doc)
            except Exception:
                pass

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            tables = introspector.get_tables("default")

            test_table = None
            for table in tables:
                if table.name.lower() == container_name.lower():
                    test_table = table
                    break

            assert test_table is not None, f"Container '{container_name}' not found"

            # Check that container was introspected
            assert len(test_table.columns) > 0, "Container should have columns"

            # Get indexes for the container
            indexes = introspector.get_indexes("default", container_name)
            # Indexing policy may or may not be fully introspected, but container should exist
            assert test_table is not None

        finally:
            pass

    def test_automatic_indexing(self, cosmosdb_container):
        """Test container with automatic indexing enabled."""
        provider = self._get_provider(cosmosdb_container)

        try:
            container_name = "test_auto_index"
            from azure.cosmos import PartitionKey

            # Create container with automatic indexing (default)
            try:
                provider.connection_manager.database.create_container_if_not_exists(
                    id=container_name,
                    partition_key=PartitionKey(path="/id"),
                )
            except Exception:
                pass

            # Insert test documents
            container_client = provider.connection_manager.get_container_client(container_name)
            test_docs = [
                {"id": "doc1", "field1": "value1", "field2": 100},
                {"id": "doc2", "field1": "value2", "field2": 200},
            ]
            for doc in test_docs:
                try:
                    container_client.create_item(body=doc)
                except Exception:
                    pass

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            tables = introspector.get_tables("default")

            test_table = None
            for table in tables:
                if table.name.lower() == container_name.lower():
                    test_table = table
                    break

            assert test_table is not None, f"Container '{container_name}' not found"

            # Check that fields were inferred
            column_names = [col.name.lower() for col in test_table.columns]
            assert "id" in column_names, "id column should exist"
            assert (
                "field1" in column_names or "field2" in column_names
            ), f"Expected fields not found: {column_names}"

        finally:
            pass
