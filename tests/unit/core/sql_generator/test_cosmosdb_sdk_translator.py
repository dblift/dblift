"""Unit tests for CosmosDB SDK Translator.

This module tests the CosmosDB pseudo-SQL to Azure SDK translation functionality.
"""

import json
from unittest.mock import MagicMock, Mock, patch

import pytest

from core.sql_generator.sql_statement import SqlStatement
from db.plugins.cosmosdb.sdk_translator import CosmosDbSdkTranslator

pytestmark = [pytest.mark.unit]


@pytest.fixture
def mock_connection_manager():
    """Create a mock connection manager."""
    manager = MagicMock()
    manager.database = MagicMock()
    manager.database.get_container_client = MagicMock(return_value=MagicMock())
    manager.create_connection = MagicMock()
    return manager


@pytest.fixture
def mock_logger():
    """Create a mock logger."""
    logger = MagicMock()
    logger.debug = MagicMock()
    logger.warning = MagicMock()
    logger.error = MagicMock()
    return logger


@pytest.fixture
def translator(mock_connection_manager, mock_logger):
    """Create a CosmosDbSdkTranslator instance for testing."""
    return CosmosDbSdkTranslator(connection_manager=mock_connection_manager, log=mock_logger)


class TestCosmosDbSdkTranslatorCanTranslate:
    """Test the can_translate method."""

    def test_can_translate_drop_container(self, translator):
        """Test that DROP CONTAINER statements can be translated."""
        statement = SqlStatement(
            sql="DROP CONTAINER my_container;",
            statement_type="DROP",
            object_type="TABLE",
            object_name="my_container",
            dialect="cosmosdb",
        )
        assert translator.can_translate(statement) is True

    def test_can_translate_alter_container(self, translator):
        """Test that ALTER CONTAINER statements can be translated."""
        statement = SqlStatement(
            sql="ALTER CONTAINER my_container SET (throughput=400);",
            statement_type="ALTER",
            object_type="TABLE",
            object_name="my_container",
            dialect="cosmosdb",
        )
        assert translator.can_translate(statement) is True

    def test_can_translate_update_container(self, translator):
        """Test that UPDATE CONTAINER statements can be translated."""
        statement = SqlStatement(
            sql="UPDATE CONTAINER my_container SET (throughput=400);",
            statement_type="UPDATE",
            object_type="TABLE",
            object_name="my_container",
            dialect="cosmosdb",
        )
        assert translator.can_translate(statement) is True

    def test_can_translate_set_container(self, translator):
        """Test that SET CONTAINER statements can be translated."""
        statement = SqlStatement(
            sql="SET CONTAINER my_container (throughput=400);",
            statement_type="SET",
            object_type="TABLE",
            object_name="my_container",
            dialect="cosmosdb",
        )
        assert translator.can_translate(statement) is True

    def test_cannot_translate_non_cosmosdb_dialect(self, translator):
        """Test that non-CosmosDB statements cannot be translated."""
        statement = SqlStatement(
            sql="DROP TABLE my_table;",
            statement_type="DROP",
            object_type="TABLE",
            object_name="my_table",
            dialect="postgresql",
        )
        assert translator.can_translate(statement) is False

    def test_cannot_translate_regular_sql(self, translator):
        """Test that regular SQL statements cannot be translated."""
        statement = SqlStatement(
            sql="SELECT * FROM my_container;",
            statement_type="SELECT",
            object_type="TABLE",
            object_name="my_container",
            dialect="cosmosdb",
        )
        assert translator.can_translate(statement) is False


class TestCosmosDbSdkTranslatorTranslateDropContainer:
    """Test DROP CONTAINER translation."""

    def test_translate_drop_container_simple(self, translator):
        """Test translating a simple DROP CONTAINER statement."""
        statement = SqlStatement(
            sql="DROP CONTAINER my_container;",
            statement_type="DROP",
            object_type="TABLE",
            object_name="my_container",
            dialect="cosmosdb",
        )
        result = translator.translate_to_sdk_operation(statement)
        assert result is not None
        assert result["operation"] == "delete_container"
        assert result["container_name"] == "my_container"
        assert "python_code" in result
        assert "database.delete_container" in result["python_code"]

    def test_translate_drop_container_with_quotes(self, translator):
        """Test translating DROP CONTAINER with quoted container name."""
        statement = SqlStatement(
            sql='DROP CONTAINER "my-container";',
            statement_type="DROP",
            object_type="TABLE",
            object_name="my-container",
            dialect="cosmosdb",
        )
        result = translator.translate_to_sdk_operation(statement)
        assert result is not None
        assert result["operation"] == "delete_container"
        assert result["container_name"] == "my-container"

    def test_translate_drop_container_from_comment(self, translator):
        """Test translating DROP CONTAINER from a comment-based pseudo-SQL."""
        # The translator should fall back to object_name when SQL is just a comment
        statement = SqlStatement(
            sql="-- Cosmos DB is schema-less. DROP CONTAINER operations for 'my_container' require Azure SDK.",
            statement_type="DROP",
            object_type="TABLE",
            object_name="my_container",
            dialect="cosmosdb",
        )
        result = translator.translate_to_sdk_operation(statement)
        # Since the SQL is just a comment, can_translate will return False
        # So translate_to_sdk_operation will return None
        # This is expected behavior - comments alone aren't translatable
        assert result is None


class TestCosmosDbSdkTranslatorTranslateAlterContainer:
    """Test ALTER CONTAINER translation."""

    def test_translate_alter_container_throughput(self, translator):
        """Test translating ALTER CONTAINER with throughput."""
        statement = SqlStatement(
            sql="ALTER CONTAINER my_container SET (throughput=400);",
            statement_type="ALTER",
            object_type="TABLE",
            object_name="my_container",
            dialect="cosmosdb",
        )
        result = translator.translate_to_sdk_operation(statement)
        assert result is not None
        assert result["operation"] == "replace_container"
        assert result["container_name"] == "my_container"
        assert result["parameters"]["offer_throughput"] == 400

    def test_translate_alter_container_indexing_policy(self, translator):
        """Test translating ALTER CONTAINER with indexing policy."""
        indexing_policy = {"indexingMode": "consistent", "automatic": True}
        statement = SqlStatement(
            sql=f"ALTER CONTAINER my_container SET (indexingPolicy='{json.dumps(indexing_policy)}');",
            statement_type="ALTER",
            object_type="TABLE",
            object_name="my_container",
            dialect="cosmosdb",
        )
        result = translator.translate_to_sdk_operation(statement)
        assert result is not None
        assert result["operation"] == "replace_container"
        assert "indexing_policy" in result["parameters"]
        assert result["parameters"]["indexing_policy"] == indexing_policy

    def test_translate_alter_container_multiple_properties(self, translator):
        """Test translating ALTER CONTAINER with multiple properties."""
        statement = SqlStatement(
            sql="ALTER CONTAINER my_container SET (throughput=400, defaultTtl=3600);",
            statement_type="ALTER",
            object_type="TABLE",
            object_name="my_container",
            dialect="cosmosdb",
        )
        result = translator.translate_to_sdk_operation(statement)
        assert result is not None
        assert result["operation"] == "replace_container"
        assert result["parameters"]["offer_throughput"] == 400
        assert result["parameters"]["default_ttl"] == 3600


class TestCosmosDbSdkTranslatorExecuteSdkOperation:
    """Test SDK operation execution."""

    def test_execute_delete_container_success(self, translator, mock_connection_manager):
        """Test successfully executing delete_container operation."""
        # The delete_container is called on database, not container_client
        mock_connection_manager.database.delete_container = MagicMock()

        operation = {
            "operation": "delete_container",
            "container_name": "my_container",
        }
        success, error = translator.execute_sdk_operation(operation)
        assert success is True
        assert error is None
        mock_connection_manager.database.delete_container.assert_called_once_with(
            container="my_container"
        )

    def test_execute_delete_container_failure(self, translator, mock_connection_manager):
        """Test delete_container operation failure."""
        # The delete_container is called on database, not container_client
        mock_connection_manager.database.delete_container = MagicMock(
            side_effect=Exception("Container not found")
        )

        operation = {
            "operation": "delete_container",
            "container_name": "my_container",
        }
        success, error = translator.execute_sdk_operation(operation)
        assert success is False
        assert error is not None
        assert "Container not found" in error

    def test_execute_replace_container_success(self, translator, mock_connection_manager):
        """Test successfully executing replace_container operation."""
        container_client = MagicMock()
        container_client.read = MagicMock(return_value={"id": "my_container"})
        container_client.replace_container = MagicMock()
        container_client.replace_throughput = MagicMock()
        mock_connection_manager.database.get_container_client.return_value = container_client

        operation = {
            "operation": "replace_container",
            "container_name": "my_container",
            "parameters": {"offer_throughput": 400},
        }
        success, error = translator.execute_sdk_operation(operation)
        assert success is True
        assert error is None

    def test_execute_operation_no_connection_manager(self):
        """Test executing operation without connection manager."""
        translator = CosmosDbSdkTranslator(connection_manager=None)
        operation = {
            "operation": "delete_container",
            "container_name": "my_container",
        }
        success, error = translator.execute_sdk_operation(operation)
        assert success is False
        assert "Connection manager not initialized" in error

    def test_execute_operation_database_not_initialized(self, translator, mock_connection_manager):
        """Test executing operation when database is not initialized."""
        mock_connection_manager.database = None
        mock_connection_manager.create_connection = MagicMock()
        mock_connection_manager.database = None  # Still None after create_connection

        operation = {
            "operation": "delete_container",
            "container_name": "my_container",
        }
        success, error = translator.execute_sdk_operation(operation)
        assert success is False
        assert "Database not initialized" in error


class TestCosmosDbSdkTranslatorGeneratePythonScript:
    """Test Python script generation."""

    def test_generate_script_delete_container(self, translator):
        """Test generating Python script for delete_container."""
        statements = [
            SqlStatement(
                sql="DROP CONTAINER my_container;",
                statement_type="DROP",
                object_type="TABLE",
                object_name="my_container",
                dialect="cosmosdb",
                requires_sdk=True,
                sdk_operation={
                    "operation": "delete_container",
                    "container_name": "my_container",
                },
            )
        ]
        script = translator.generate_python_script(statements)
        assert "Delete container 'my_container'" in script
        assert "container_client.delete_container()" in script
        assert "database.get_container_client('my_container')" in script

    def test_generate_script_replace_container(self, translator):
        """Test generating Python script for replace_container."""
        statements = [
            SqlStatement(
                sql="ALTER CONTAINER my_container SET (throughput=400);",
                statement_type="ALTER",
                object_type="TABLE",
                object_name="my_container",
                dialect="cosmosdb",
                requires_sdk=True,
                sdk_operation={
                    "operation": "replace_container",
                    "container_name": "my_container",
                    "parameters": {"offer_throughput": 400},
                },
            )
        ]
        script = translator.generate_python_script(statements)
        assert "Update container 'my_container'" in script
        assert "container_client.replace_throughput(400)" in script
        assert "container_client.replace_container" in script

    def test_generate_script_multiple_operations(self, translator):
        """Test generating Python script for multiple operations."""
        statements = [
            SqlStatement(
                sql="DROP CONTAINER container1;",
                statement_type="DROP",
                object_type="TABLE",
                object_name="container1",
                dialect="cosmosdb",
                requires_sdk=True,
                sdk_operation={
                    "operation": "delete_container",
                    "container_name": "container1",
                },
            ),
            SqlStatement(
                sql="ALTER CONTAINER container2 SET (throughput=800);",
                statement_type="ALTER",
                object_type="TABLE",
                object_name="container2",
                dialect="cosmosdb",
                requires_sdk=True,
                sdk_operation={
                    "operation": "replace_container",
                    "container_name": "container2",
                    "parameters": {"offer_throughput": 800},
                },
            ),
        ]
        script = translator.generate_python_script(statements)
        assert "container1" in script
        assert "container2" in script
        # Check that container_client is created for each operation (2 operations = 2 assignments)
        assert script.count("container_client = database.get_container_client") == 2

    def test_generate_script_filters_non_sdk_statements(self, translator):
        """Test that non-SDK statements are filtered out."""
        statements = [
            SqlStatement(
                sql="DROP CONTAINER my_container;",
                statement_type="DROP",
                object_type="TABLE",
                object_name="my_container",
                dialect="cosmosdb",
                requires_sdk=True,
                sdk_operation={
                    "operation": "delete_container",
                    "container_name": "my_container",
                },
            ),
            SqlStatement(
                sql="SELECT * FROM my_container;",
                statement_type="SELECT",
                object_type="TABLE",
                object_name="my_container",
                dialect="cosmosdb",
                requires_sdk=False,
            ),
        ]
        script = translator.generate_python_script(statements)
        assert "my_container" in script
        assert "SELECT" not in script  # Non-SDK statement should not appear


class TestCosmosDbSdkTranslatorEdgeCases:
    """Test edge cases and error handling."""

    def test_translate_invalid_json_in_indexing_policy(self, translator, mock_logger):
        """Test handling invalid JSON in indexing policy."""
        statement = SqlStatement(
            sql="ALTER CONTAINER my_container SET (indexingPolicy='invalid json');",
            statement_type="ALTER",
            object_type="TABLE",
            object_name="my_container",
            dialect="cosmosdb",
        )
        result = translator.translate_to_sdk_operation(statement)
        # Should still return a result, but without indexing_policy
        assert result is not None
        mock_logger.warning.assert_called()

    def test_translate_empty_statement(self, translator):
        """Test translating an empty statement."""
        statement = SqlStatement(
            sql="",
            statement_type="DROP",
            object_type="TABLE",
            object_name="",
            dialect="cosmosdb",
        )
        result = translator.translate_to_sdk_operation(statement)
        assert result is None

    def test_translate_unknown_operation(self, translator):
        """Test translating an unknown operation."""
        statement = SqlStatement(
            sql="UNKNOWN CONTAINER my_container;",
            statement_type="UNKNOWN",
            object_type="TABLE",
            object_name="my_container",
            dialect="cosmosdb",
        )
        result = translator.translate_to_sdk_operation(statement)
        assert result is None
