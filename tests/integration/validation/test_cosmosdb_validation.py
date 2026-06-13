"""
CosmosDB Basic Validation Tests.

Tests for basic CosmosDB container introspection and schema inference.
"""

import pytest

from core.introspection.introspector_factory import IntrospectorFactory
from core.logger import ConsoleLog


@pytest.mark.integration
class TestCosmosDbValidation:
    """CosmosDB basic validation tests."""

    def _get_provider(self, cosmosdb_container):
        """Create database provider."""
        from config import DbliftConfig
        from db.provider_registry import ProviderRegistry

        # Check if CosmosDB is available
        if "_skip_reason" in cosmosdb_container:
            pytest.skip(cosmosdb_container["_skip_reason"])

        # Build config dict (same pattern as test_cosmosdb_integration.py)
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
        log = ConsoleLog("cosmosdb_validation", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()
        return provider

    def test_container_introspection(self, cosmosdb_container):
        """Test basic container introspection."""
        provider = self._get_provider(cosmosdb_container)
        database_name = cosmosdb_container.get("database_name", "testdb")

        try:
            # Create a test container if it doesn't exist
            container_name = "test_users"
            container_client = provider.connection_manager.get_container_client(container_name)

            # Try to create container (will fail if it exists, that's okay)
            try:
                from azure.cosmos import PartitionKey

                provider.connection_manager.database.create_container_if_not_exists(
                    id=container_name,
                    partition_key=PartitionKey(path="/id"),
                )
            except Exception:
                pass  # Container may already exist

            # Insert a test document
            test_doc = {
                "id": "user1",
                "name": "John Doe",
                "email": "john@example.com",
                "age": 30,
            }
            try:
                container_client.create_item(body=test_doc)
            except Exception:
                pass  # Document may already exist

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            tables = introspector.get_tables("default")  # Schema not used in CosmosDB

            # Find our container
            test_table = None
            for table in tables:
                if table.name.lower() == container_name.lower():
                    test_table = table
                    break

            assert test_table is not None, f"Container '{container_name}' not found"
            assert len(test_table.columns) > 0, "Container has no columns"

            # Check for id column (required in CosmosDB)
            id_columns = [col for col in test_table.columns if col.name.lower() == "id"]
            assert len(id_columns) >= 1, "Container missing 'id' column"

        finally:
            # Cleanup is optional - containers can persist for reuse
            pass

    def test_partition_key_extraction(self, cosmosdb_container):
        """Test partition key extraction from container."""
        provider = self._get_provider(cosmosdb_container)

        try:
            # Create a test container with custom partition key
            container_name = "test_orders"
            from azure.cosmos import PartitionKey

            try:
                provider.connection_manager.database.create_container_if_not_exists(
                    id=container_name,
                    partition_key=PartitionKey(path="/customerId"),
                )
            except Exception:
                pass  # Container may already exist

            # Insert a test document
            container_client = provider.connection_manager.get_container_client(container_name)
            test_doc = {
                "id": "order1",
                "customerId": "customer1",
                "orderDate": "2024-01-01",
                "total": 100.50,
            }
            try:
                container_client.create_item(body=test_doc)
            except Exception:
                pass  # Document may already exist

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            tables = introspector.get_tables("default")

            # Find our container
            test_table = None
            for table in tables:
                if table.name.lower() == container_name.lower():
                    test_table = table
                    break

            assert test_table is not None, f"Container '{container_name}' not found"

            # Check comment for partition key info
            if test_table.comment:
                assert (
                    "partition" in test_table.comment.lower()
                    or "customerId" in test_table.comment.lower()
                ), f"Partition key not found in comment: {test_table.comment}"

        finally:
            pass

    def test_schema_inference_simple(self, cosmosdb_container):
        """Test schema inference from simple documents."""
        provider = self._get_provider(cosmosdb_container)

        try:
            # Create a test container
            container_name = "test_products"
            from azure.cosmos import PartitionKey

            try:
                provider.connection_manager.database.create_container_if_not_exists(
                    id=container_name,
                    partition_key=PartitionKey(path="/id"),
                )
            except Exception:
                pass

            # Insert test documents with consistent schema
            container_client = provider.connection_manager.get_container_client(container_name)
            test_docs = [
                {
                    "id": "product1",
                    "name": "Laptop",
                    "price": 999.99,
                    "inStock": True,
                    "category": "Electronics",
                },
                {
                    "id": "product2",
                    "name": "Mouse",
                    "price": 29.99,
                    "inStock": True,
                    "category": "Electronics",
                },
            ]
            for doc in test_docs:
                try:
                    container_client.create_item(body=doc)
                except Exception:
                    pass  # Document may already exist

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            tables = introspector.get_tables("default")

            # Find our container
            test_table = None
            for table in tables:
                if table.name.lower() == container_name.lower():
                    test_table = table
                    break

            assert test_table is not None, f"Container '{container_name}' not found"

            # Check that schema was inferred
            column_names = [col.name.lower() for col in test_table.columns]
            assert "id" in column_names, "id column not found"
            assert (
                "name" in column_names or "price" in column_names
            ), f"Expected columns not found: {column_names}"

        finally:
            pass
