"""
CosmosDB Schema Inference Tests.

Tests for advanced schema inference from documents (nested objects, arrays, etc.).
"""

import pytest

from core.introspection.introspector_factory import IntrospectorFactory
from core.logger import ConsoleLog


@pytest.mark.integration
class TestCosmosDbSchemaInference:
    """CosmosDB schema inference tests."""

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
        log = ConsoleLog("cosmosdb_schema_inference", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()
        return provider

    def test_nested_object_inference(self, cosmosdb_container):
        """Test schema inference from documents with nested objects."""
        provider = self._get_provider(cosmosdb_container)

        try:
            container_name = "test_nested"
            from azure.cosmos import PartitionKey

            try:
                provider.connection_manager.database.create_container_if_not_exists(
                    id=container_name,
                    partition_key=PartitionKey(path="/id"),
                )
            except Exception:
                pass

            container_client = provider.connection_manager.get_container_client(container_name)
            test_doc = {
                "id": "doc1",
                "user": {
                    "name": "John Doe",
                    "email": "john@example.com",
                    "address": {
                        "street": "123 Main St",
                        "city": "New York",
                    },
                },
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

            # Check that schema was inferred (nested objects may be flattened or kept as objects)
            column_names = [col.name.lower() for col in test_table.columns]
            assert "id" in column_names, "id column not found"
            # User field should be present (may be flattened or as object)
            assert "user" in column_names or any(
                "user" in name for name in column_names
            ), f"user field not found in columns: {column_names}"

        finally:
            pass

    def test_mixed_type_inference(self, cosmosdb_container):
        """Test schema inference from documents with mixed types."""
        provider = self._get_provider(cosmosdb_container)

        try:
            container_name = "test_mixed"
            from azure.cosmos import PartitionKey

            try:
                provider.connection_manager.database.create_container_if_not_exists(
                    id=container_name,
                    partition_key=PartitionKey(path="/id"),
                )
            except Exception:
                pass

            container_client = provider.connection_manager.get_container_client(container_name)
            test_docs = [
                {
                    "id": "doc1",
                    "value": "string_value",
                },
                {
                    "id": "doc2",
                    "value": 123,
                },
                {
                    "id": "doc3",
                    "value": True,
                },
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

            # Check that value column exists (type may be inferred as most common or as mixed)
            value_col = next(
                (col for col in test_table.columns if col.name.lower() == "value"), None
            )
            assert value_col is not None, "value column not found"

        finally:
            pass

    def test_empty_container_handling(self, cosmosdb_container):
        """Test handling of empty containers (no documents)."""
        provider = self._get_provider(cosmosdb_container)

        try:
            container_name = "test_empty"
            from azure.cosmos import PartitionKey

            try:
                provider.connection_manager.database.create_container_if_not_exists(
                    id=container_name,
                    partition_key=PartitionKey(path="/id"),
                )
            except Exception:
                pass

            # Don't insert any documents - container is empty

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            tables = introspector.get_tables("default")

            test_table = None
            for table in tables:
                if table.name.lower() == container_name.lower():
                    test_table = table
                    break

            assert test_table is not None, f"Container '{container_name}' not found"

            # Empty container should still have at least the id column
            column_names = [col.name.lower() for col in test_table.columns]
            assert "id" in column_names, "Empty container should have id column"

        finally:
            pass
