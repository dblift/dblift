"""
CosmosDB SDK Translator Tests.

Tests for the CosmosDB SDK translator that converts pseudo-SQL to Azure SDK operations.
"""

import pytest

from core.logger import ConsoleLog
from core.sql_generator.sql_statement import SqlStatement
from db.plugins.cosmosdb.sdk_translator import CosmosDbSdkTranslator


@pytest.mark.integration
class TestCosmosDbSdkTranslator:
    """CosmosDB SDK translator tests."""

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
        log = ConsoleLog("cosmosdb_sdk_translator", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()
        return provider

    def test_translator_detection_drop_container(self, cosmosdb_container):
        """Test that DROP CONTAINER is detected as requiring SDK translation."""
        provider = self._get_provider(cosmosdb_container)

        translator = CosmosDbSdkTranslator(provider.connection_manager, None)

        statement = SqlStatement(
            sql="DROP CONTAINER test_container",
            statement_type="DROP",
            object_type="CONTAINER",
            object_name="test_container",
            dialect="cosmosdb",
        )

        assert translator.can_translate(statement) is True, "DROP CONTAINER should be translatable"

    def test_translator_detection_alter_container(self, cosmosdb_container):
        """Test that ALTER CONTAINER is detected as requiring SDK translation."""
        provider = self._get_provider(cosmosdb_container)

        translator = CosmosDbSdkTranslator(provider.connection_manager, None)

        statement = SqlStatement(
            sql="ALTER CONTAINER test_container SET (throughput=400)",
            statement_type="ALTER",
            object_type="CONTAINER",
            object_name="test_container",
            dialect="cosmosdb",
        )

        assert translator.can_translate(statement) is True, "ALTER CONTAINER should be translatable"

    def test_translator_detection_set_throughput(self, cosmosdb_container):
        """Test that SET THROUGHPUT is detected as requiring SDK translation."""
        provider = self._get_provider(cosmosdb_container)

        translator = CosmosDbSdkTranslator(provider.connection_manager, None)

        statement = SqlStatement(
            sql="SET THROUGHPUT ON CONTAINER test_container TO 400",
            statement_type="SET",
            object_type="CONTAINER",
            object_name="test_container",
            dialect="cosmosdb",
        )

        assert translator.can_translate(statement) is True, "SET THROUGHPUT should be translatable"

    def test_translator_translation_drop_container(self, cosmosdb_container):
        """Test translation of DROP CONTAINER to SDK operation."""
        provider = self._get_provider(cosmosdb_container)

        translator = CosmosDbSdkTranslator(provider.connection_manager, None)

        statement = SqlStatement(
            sql="DROP CONTAINER test_container",
            statement_type="DROP",
            object_type="CONTAINER",
            object_name="test_container",
            dialect="cosmosdb",
        )

        operation = translator.translate_to_sdk_operation(statement)

        assert operation is not None, "Translation should return an operation"
        assert (
            operation.get("operation") == "delete_container"
        ), f"Expected 'delete_container', got {operation.get('operation')}"
        assert (
            operation.get("container_name") == "test_container"
        ), f"Expected 'test_container', got {operation.get('container_name')}"
        assert "warning" in operation, "Destructive operation should have a warning"

    def test_translator_translation_alter_container_throughput(self, cosmosdb_container):
        """Test translation of ALTER CONTAINER SET throughput to SDK operation."""
        provider = self._get_provider(cosmosdb_container)

        translator = CosmosDbSdkTranslator(provider.connection_manager, None)

        statement = SqlStatement(
            sql="ALTER CONTAINER test_container SET (throughput=400)",
            statement_type="ALTER",
            object_type="CONTAINER",
            object_name="test_container",
            dialect="cosmosdb",
        )

        operation = translator.translate_to_sdk_operation(statement)

        assert operation is not None, "Translation should return an operation"
        assert (
            operation.get("operation") == "replace_container"
        ), f"Expected 'replace_container', got {operation.get('operation')}"
        assert "parameters" in operation, "Operation should have parameters"
        # SDK uses offer_throughput, not throughput
        assert (
            operation["parameters"].get("offer_throughput") == 400
        ), f"Expected offer_throughput=400, got {operation['parameters'].get('offer_throughput')}"

    def test_translator_execution_drop_container(self, cosmosdb_container):
        """Test execution of DROP CONTAINER via SDK translator."""
        provider = self._get_provider(cosmosdb_container)

        # Create a test container first
        container_name = "test_drop_container"
        from azure.cosmos import PartitionKey

        try:
            provider.connection_manager.database.create_container_if_not_exists(
                id=container_name,
                partition_key=PartitionKey(path="/id"),
            )
        except Exception:
            pass  # Container may already exist

        # Verify container exists
        container_client = provider.connection_manager.get_container_client(container_name)
        try:
            container_client.read()
        except Exception:
            pytest.skip("Container creation failed, cannot test drop")

        # Translate and execute DROP CONTAINER
        translator = CosmosDbSdkTranslator(provider.connection_manager, None)

        statement = SqlStatement(
            sql=f"DROP CONTAINER {container_name}",
            statement_type="DROP",
            object_type="CONTAINER",
            object_name=container_name,
            dialect="cosmosdb",
        )

        operation = translator.translate_to_sdk_operation(statement)
        assert operation is not None, "Translation should succeed"

        # Execute the operation
        success, error = translator.execute_sdk_operation(operation)
        assert success is True, f"SDK operation should succeed, got error: {error}"

        # Verify container is deleted
        try:
            container_client.read()
            pytest.fail("Container should be deleted")
        except Exception:
            pass  # Expected - container should not exist

    def test_query_executor_sdk_operation(self, cosmosdb_container):
        """Test that query executor can execute SDK operations via translator."""
        provider = self._get_provider(cosmosdb_container)

        # Create a test container
        container_name = "test_executor_sdk"
        from azure.cosmos import PartitionKey

        try:
            provider.connection_manager.database.create_container_if_not_exists(
                id=container_name,
                partition_key=PartitionKey(path="/id"),
            )
        except Exception:
            pass

        # Execute DROP CONTAINER via query executor (which uses SDK translator)
        try:
            result = provider.execute_statement(f"DROP CONTAINER {container_name}")
            assert result >= 0, "DROP CONTAINER should succeed"
        except Exception as e:
            # If container doesn't exist, that's okay
            if "not found" not in str(e).lower() and "does not exist" not in str(e).lower():
                raise

    def test_translator_non_translatable_statement(self, cosmosdb_container):
        """Test that regular SQL statements are not translated."""
        provider = self._get_provider(cosmosdb_container)

        translator = CosmosDbSdkTranslator(provider.connection_manager, None)

        # Regular SELECT statement should not be translatable
        statement = SqlStatement(
            sql="SELECT * FROM c",
            statement_type="SELECT",
            object_type="QUERY",
            object_name="",
            dialect="cosmosdb",
        )

        assert (
            translator.can_translate(statement) is False
        ), "Regular SELECT should not be translatable"

        operation = translator.translate_to_sdk_operation(statement)
        assert operation is None, "Non-translatable statement should return None"
