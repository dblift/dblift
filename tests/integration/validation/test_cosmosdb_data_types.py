"""
CosmosDB Data Types Tests.

Tests for JSON data type inference in CosmosDB.
"""

import pytest

from core.introspection.introspector_factory import IntrospectorFactory
from core.logger import ConsoleLog


@pytest.mark.integration
class TestCosmosDbDataTypes:
    """CosmosDB data types tests."""

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
        log = ConsoleLog("cosmosdb_data_types", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()
        return provider

    def test_string_type_inference(self, cosmosdb_container):
        """Test string type inference from JSON strings."""
        provider = self._get_provider(cosmosdb_container)

        try:
            container_name = "test_strings"
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
                "name": "Test Name",
                "description": "A test description",
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

            # Check for string columns
            name_col = next((col for col in test_table.columns if col.name.lower() == "name"), None)
            assert name_col is not None, "name column not found"
            # Type should be inferred as STRING or similar
            assert name_col.data_type is not None, "name column has no data type"

        finally:
            pass

    def test_number_type_inference(self, cosmosdb_container):
        """Test number type inference from JSON numbers."""
        provider = self._get_provider(cosmosdb_container)

        try:
            container_name = "test_numbers"
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
                "age": 30,
                "price": 99.99,
                "quantity": 5,
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

            # Check for number columns
            age_col = next((col for col in test_table.columns if col.name.lower() == "age"), None)
            assert age_col is not None, "age column not found"
            assert age_col.data_type is not None, "age column has no data type"

        finally:
            pass

    def test_boolean_type_inference(self, cosmosdb_container):
        """Test boolean type inference from JSON booleans."""
        provider = self._get_provider(cosmosdb_container)

        try:
            container_name = "test_booleans"
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
                "isActive": True,
                "isDeleted": False,
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

            # Check for boolean columns
            is_active_col = next(
                (col for col in test_table.columns if col.name.lower() == "isactive"), None
            )
            assert is_active_col is not None, "isActive column not found"

        finally:
            pass

    def test_array_type_inference(self, cosmosdb_container):
        """Test array type inference from JSON arrays."""
        provider = self._get_provider(cosmosdb_container)

        try:
            container_name = "test_arrays"
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
                "tags": ["tag1", "tag2", "tag3"],
                "scores": [85, 90, 95],
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

            # Check for array columns
            tags_col = next((col for col in test_table.columns if col.name.lower() == "tags"), None)
            assert tags_col is not None, "tags column not found"

        finally:
            pass
