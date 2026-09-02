"""Unit tests for callback placeholder replacement functionality.

This module tests that callbacks work correctly with placeholder replacement
without requiring database containers.
"""

import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from dblift.core.logger import DbliftLogger
from dblift.core.migration.executor.execution_engine import ExecutionEngine
from dblift.core.migration.migration import Migration, MigrationType
from dblift.core.migration.placeholders.placeholder_service import PlaceholderService
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer

pytestmark = [pytest.mark.unit]


class TestCallbackPlaceholderReplacement:
    """Test callback placeholder replacement functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = Path(tempfile.mkdtemp())

        # Create mock logger
        self.log = Mock(spec=DbliftLogger)

        # Create mock provider
        self.mock_provider = Mock()
        self.mock_provider.execute_statement.return_value = 1

        # Create SQL analyzer
        self.sql_analyzer = SqlAnalyzer(dialect="postgresql", logger=self.log)

        # Create placeholder service with test placeholders
        self.placeholders = {
            "dblift_schema": "TEST_SCHEMA",
            "dblift_database": "testdb",
            "dblift_username": "testuser",
        }
        self.placeholder_service = PlaceholderService(self.placeholders, self.log)

        # Create execution engine
        self.execution_engine = ExecutionEngine(
            provider=self.mock_provider,
            sql_analyzer=self.sql_analyzer,
            log=self.log,
            placeholder_service=self.placeholder_service,
            config=Mock(),
        )

    def teardown_method(self):
        """Clean up test fixtures."""
        import shutil

        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def create_callback_migration(self, filename: str, content: str) -> Migration:
        """Helper to create a callback migration file."""
        file_path = self.temp_dir / filename
        file_path.write_text(content)
        migration = Migration(file_path, logger=self.log)
        return migration

    def test_callback_placeholder_replacement(self):
        """Test that placeholders are replaced in callback SQL."""
        # Create a callback with placeholders
        callback_content = """
            CREATE TABLE "${dblift_schema}".callback_test (
                id SERIAL PRIMARY KEY,
                schema_name VARCHAR(100),
                database_name VARCHAR(100),
                username VARCHAR(100)
            );
            
            INSERT INTO "${dblift_schema}".callback_test 
            (schema_name, database_name, username) 
            VALUES ('${dblift_schema}', '${dblift_database}', '${dblift_username}');
        """

        callback = self.create_callback_migration(
            "beforemigrate__test_callback.sql", callback_content
        )

        # Execute the callback
        self.execution_engine.execute_callback(callback)

        # Verify that execute_statement was called with replaced placeholders
        calls = self.mock_provider.execute_statement.call_args_list

        # First call should be CREATE TABLE with replaced schema
        create_call = calls[0][0][0]  # First argument of first call
        assert '"TEST_SCHEMA".callback_test' in create_call
        assert "${dblift_schema}" not in create_call

        # Second call should be INSERT with all placeholders replaced
        insert_call = calls[1][0][0]  # First argument of second call
        assert "TEST_SCHEMA" in insert_call
        assert "testdb" in insert_call
        assert "testuser" in insert_call
        assert "${dblift_schema}" not in insert_call
        assert "${dblift_database}" not in insert_call
        assert "${dblift_username}" not in insert_call

    def test_callback_with_complex_placeholders(self):
        """Test callbacks with complex placeholder scenarios."""
        callback_content = """
            -- Test various placeholder scenarios
            CREATE SCHEMA IF NOT EXISTS "${dblift_schema}";
            
            CREATE TABLE "${dblift_schema}".complex_test (
                id SERIAL PRIMARY KEY,
                schema_name VARCHAR(100) DEFAULT '${dblift_schema}',
                database_name VARCHAR(100) DEFAULT '${dblift_database}',
                created_by VARCHAR(100) DEFAULT '${dblift_username}',
                description TEXT DEFAULT 'Created by ${dblift_username} in ${dblift_schema}'
            );
            
            COMMENT ON TABLE "${dblift_schema}".complex_test IS 'Test table created by ${dblift_username}';
        """

        callback = self.create_callback_migration(
            "beforeeach__complex_callback.sql", callback_content
        )

        # Execute the callback
        self.execution_engine.execute_callback(callback)

        # Verify all statements were executed with placeholders replaced
        calls = self.mock_provider.execute_statement.call_args_list
        assert len(calls) == 3

        for i, call in enumerate(calls):
            statement = call[0][0]
            # All placeholders should be replaced
            assert "${dblift_schema}" not in statement
            assert "${dblift_database}" not in statement
            assert "${dblift_username}" not in statement

            # Values should be present
            assert "TEST_SCHEMA" in statement

            # Only the CREATE TABLE statement should have database values
            if i == 1:  # CREATE TABLE statement
                assert "testdb" in statement
                assert "testuser" in statement
            # COMMENT statement only has username
            elif i == 2:  # COMMENT statement
                assert "testuser" in statement

    def test_callback_without_placeholder_service(self):
        """Test callback execution when no placeholder service is available."""
        # Create execution engine without placeholder service
        execution_engine_no_service = ExecutionEngine(
            provider=self.mock_provider,
            sql_analyzer=self.sql_analyzer,
            log=self.log,
            placeholder_service=None,
            config=Mock(),
        )

        callback_content = """
            CREATE TABLE "${dblift_schema}".no_service_test (id INT);
        """

        callback = self.create_callback_migration("beforemigrate__no_service.sql", callback_content)

        # Execute the callback
        execution_engine_no_service.execute_callback(callback)

        # Verify statement was executed without placeholder replacement
        calls = self.mock_provider.execute_statement.call_args_list
        statement = calls[0][0][0]
        assert "${dblift_schema}" in statement  # Placeholder should remain

    def test_callback_execution_order_with_placeholders(self):
        """Test that multiple callbacks execute in correct order with placeholder replacement."""
        callbacks = [
            (
                "beforemigrate__setup.sql",
                'CREATE TABLE "${dblift_schema}".execution_log (id SERIAL PRIMARY KEY, step VARCHAR(50));',
            ),
            (
                "beforeeach__log.sql",
                "INSERT INTO \"${dblift_schema}\".execution_log (step) VALUES ('beforeeach');",
            ),
            (
                "aftereach__log.sql",
                "INSERT INTO \"${dblift_schema}\".execution_log (step) VALUES ('aftereach');",
            ),
            (
                "aftermigrate__cleanup.sql",
                "INSERT INTO \"${dblift_schema}\".execution_log (step) VALUES ('aftermigrate');",
            ),
        ]

        created_callbacks = []
        for filename, content in callbacks:
            created_callbacks.append(self.create_callback_migration(filename, content))

        # Execute callbacks in order
        for callback in created_callbacks:
            self.execution_engine.execute_callback(callback)

        # Verify all statements were executed with placeholders replaced
        calls = self.mock_provider.execute_statement.call_args_list
        assert len(calls) == 4

        for i, call in enumerate(calls):
            statement = call[0][0]
            assert "${dblift_schema}" not in statement
            assert "TEST_SCHEMA" in statement

    def test_callback_error_handling_with_placeholders(self):
        """Test error handling in callbacks with placeholder replacement."""
        callback_content = """
            CREATE TABLE "${dblift_schema}".error_test (id INT);
            -- This will cause an error due to invalid SQL
            INVALID SQL STATEMENT;
        """

        callback = self.create_callback_migration(
            "beforemigrate__error_callback.sql", callback_content
        )

        # Mock provider to raise exception on second statement
        def mock_execute(statement):
            if "INVALID SQL" in statement:
                raise Exception("Invalid SQL syntax")
            return 1

        self.mock_provider.execute_statement.side_effect = mock_execute

        # Execute callback - should raise exception
        with pytest.raises(Exception, match="Invalid SQL syntax"):
            self.execution_engine.execute_callback(callback)

        # Verify first statement was executed with placeholders replaced
        calls = self.mock_provider.execute_statement.call_args_list
        assert len(calls) == 2  # Both statements were executed before error occurred
        first_statement = calls[0][0][0]
        assert "${dblift_schema}" not in first_statement
        assert "TEST_SCHEMA" in first_statement

        # Verify second statement was also executed (and failed)
        second_statement = calls[1][0][0]
        assert "INVALID SQL STATEMENT" in second_statement
