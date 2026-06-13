"""Extended tests for JsonFormatter to improve coverage.

This module tests additional scenarios for JsonFormatter, focusing on
uncovered areas like version detection, database connection info, performance
statistics, diff details, multi-command mode, and error handling.
"""

import json
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, Mock, mock_open, patch

import pytest

from core.comparison.diff_models import (
    ColumnDiff,
    ConstraintDiff,
    SchemaDiff,
    TableDiff,
    UserDefinedTypeDiff,
)
from core.logger.formatters.jsonformatter import JsonFormatter
from core.logger.results import (
    CleanResult,
    DiffResult,
    MigrateResult,
    MigrationInfo,
    OperationResult,
)


@pytest.mark.unit
class TestJsonFormatterExtended:
    """Extended tests for JsonFormatter."""

    def test_format_event_with_context(self):
        """Test format_event with context."""
        formatter = JsonFormatter()
        event = Mock()
        event.level.value = "INFO"
        event.component = "test"
        event.message = "test message"
        event.timestamp = datetime(2023, 1, 1, 12, 0, 0)
        event.context = {"key": "value", "number": 123}

        result = formatter.format_event(event)
        parsed = json.loads(result)

        assert "context" in parsed
        assert parsed["context"]["key"] == "value"
        assert parsed["context"]["number"] == 123

    def test_format_event_without_context(self):
        """Test format_event without context."""
        formatter = JsonFormatter()
        event = Mock()
        event.level.value = "INFO"
        event.component = "test"
        event.message = "test message"
        event.timestamp = datetime(2023, 1, 1, 12, 0, 0)
        # Explicitly remove context attribute
        if hasattr(event, "context"):
            delattr(event, "context")

        result = formatter.format_event(event)
        parsed = json.loads(result)

        assert "context" not in parsed

    def test_format_result_with_db_version(self):
        """Test format_result with db_version."""
        formatter = JsonFormatter()
        result = OperationResult(success=True)
        result.db_version = "PostgreSQL 14.0"
        result.complete()

        json_output = formatter.format_result(
            result=result, schema="test", database_name="test_db", command_type="INFO"
        )
        parsed = json.loads(json_output)

        assert parsed["db_version"] == "PostgreSQL 14.0"

    def test_format_result_with_native_driver(self):
        """Test format_result with native_driver."""
        formatter = JsonFormatter()
        result = OperationResult(success=True)
        result.native_driver = "postgresql-42.7.5.jar"
        result.complete()

        json_output = formatter.format_result(
            result=result, schema="test", database_name="test_db", command_type="INFO"
        )
        parsed = json.loads(json_output)

        assert parsed["native_driver"] == "postgresql-42.7.5.jar"

    def test_format_result_with_database_url_masked(self):
        """Test format_result with database_url_masked."""
        formatter = JsonFormatter()
        result = OperationResult(success=True)
        result.database_url_masked = "postgresql+psycopg://***:***@localhost/test"
        result.complete()

        json_output = formatter.format_result(
            result=result, schema="test", database_name="test_db", command_type="INFO"
        )
        parsed = json.loads(json_output)

        assert parsed["database_url_masked"] == "postgresql+psycopg://***:***@localhost/test"

    def test_format_result_with_server_name(self):
        """Test format_result with server_name."""
        formatter = JsonFormatter()
        result = OperationResult(success=True)
        result.server_name = "test-server"
        result.complete()

        json_output = formatter.format_result(
            result=result, schema="test", database_name="test_db", command_type="INFO"
        )
        parsed = json.loads(json_output)

        assert parsed["server_name"] == "test-server"

    def test_format_result_clean_without_get_objects_by_type(self):
        """Test format_result for CLEAN without get_objects_by_type method."""
        formatter = JsonFormatter()
        result = CleanResult()
        result.success = True
        # Don't add get_objects_by_type method
        result.complete()

        json_output = formatter.format_result(
            result=result, schema="test", database_name="test_db", command_type="CLEAN"
        )
        parsed = json.loads(json_output)

        assert parsed["objects_dropped"] == {}

    def test_format_result_with_performance_summary(self):
        """Test format_result with performance summary from journal."""
        formatter = JsonFormatter()
        result = MigrateResult()
        result.success = True

        # Mock journal with performance summary
        journal = Mock()
        perf_summary = {
            "total_statements": 10,
            "total_execution_time": 5000,
            "avg_statement_time": 500,
            "min_statement_time": 100,
            "max_statement_time": 1000,
            "slowest_statement": "CREATE TABLE users",
        }
        journal.get_migration_performance_summary = Mock(return_value=perf_summary)
        journal.get_performance_stats_by_object_type = Mock(return_value={})
        result.journal = journal

        # Add migration - the code checks for script_name attribute, but MigrationInfo uses script
        # So we need to add script_name attribute manually or use script
        migration = MigrationInfo(script="V1__Test.sql", version="1.0.0", description="Test")
        # Add script_name attribute for the formatter to find
        migration.script_name = "V1__Test.sql"
        result.migrations = [migration]
        result.complete()

        json_output = formatter.format_result(
            result=result, schema="test", database_name="test_db", command_type="MIGRATE"
        )
        parsed = json.loads(json_output)

        assert "performance_summary" in parsed
        assert parsed["performance_summary"]["total_statements"] == 10
        assert parsed["performance_summary"]["total_execution_time"] == 5000

    def test_format_result_with_performance_by_object_type(self):
        """Test format_result with performance by object type."""
        formatter = JsonFormatter()
        result = MigrateResult()
        result.success = True

        # Mock journal with object type stats
        journal = Mock()
        journal.get_migration_performance_summary = Mock(return_value=None)
        obj_stats = {
            "table": {"count": 5, "total_time": 2000, "avg_time": 400},
            "index": {"count": 3, "total_time": 500, "avg_time": 166.67},
        }
        journal.get_performance_stats_by_object_type = Mock(return_value=obj_stats)
        result.journal = journal

        migration = MigrationInfo(script="V1__Test.sql", version="1.0.0", description="Test")
        # Add script_name attribute for the formatter to find
        migration.script_name = "V1__Test.sql"
        result.migrations = [migration]
        result.complete()

        json_output = formatter.format_result(
            result=result, schema="test", database_name="test_db", command_type="MIGRATE"
        )
        parsed = json.loads(json_output)

        assert "performance_by_object_type" in parsed
        assert len(parsed["performance_by_object_type"]) == 2
        assert parsed["performance_by_object_type"][0]["object_type"] == "table"

    def test_format_result_diff_with_modified_tables(self):
        """Test format_result for DIFF with modified tables."""
        formatter = JsonFormatter()
        result = DiffResult()
        result.success = True
        result.source_type = "postgresql"
        result.target_type = "mysql"
        result.total_differences = 5
        result.error_count = 1
        result.warning_count = 2
        result.info_count = 2
        result.missing_tables = ["table1"]
        result.extra_tables = ["table2"]
        result.modified_tables = []

        # Create schema diff with modified table
        schema_diff = SchemaDiff(object_name="public", schema_name="public")

        # Create table diff with column and constraint changes
        col_diff = ColumnDiff(
            object_name="id",
            column_name="id",
            data_type_diff=("INTEGER", "VARCHAR"),
            nullable_diff=(False, True),
            default_diff=("0", "1"),
            identity_diff=(True, False),
            computed_diff=(True, False),
        )
        col_diff._calculate_diffs()

        const_diff = ConstraintDiff(
            object_name="pk_users",
            constraint_name="pk_users",
            columns_diff=(["id"], ["id", "version"]),
            references_diff=("users", "orders"),
            check_clause_diff=("age > 0", "age >= 0"),
        )

        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            missing_columns=["email"],
            extra_columns=["phone"],
            modified_columns=[col_diff],
            missing_constraints=["pk_users"],
            extra_constraints=["fk_orders"],
            modified_constraints=[const_diff],
        )
        table_diff._calculate_diffs()

        schema_diff.modified_tables = [table_diff]
        result.set_schema_diff(schema_diff)
        result.complete()

        json_output = formatter.format_result(
            result=result, schema="test", database_name="test_db", command_type="DIFF"
        )
        parsed = json.loads(json_output)

        assert "modified_tables" in parsed
        assert len(parsed["modified_tables"]) == 1
        mod_table = parsed["modified_tables"][0]
        assert mod_table["table_name"] == "users"
        assert len(mod_table["modified_columns"]) == 1
        assert len(mod_table["modified_constraints"]) == 1
        assert "data_type" in mod_table["modified_columns"][0]["changes"]
        assert "columns" in mod_table["modified_constraints"][0]["changes"]

    def test_format_result_diff_with_modified_user_defined_types(self):
        """Test format_result for DIFF with modified user-defined types."""
        formatter = JsonFormatter()
        result = DiffResult()
        result.success = True
        result.source_type = "postgresql"
        result.target_type = "postgresql"
        result.total_differences = 3
        result.error_count = 1
        result.warning_count = 1
        result.info_count = 1
        result.missing_tables = []
        result.extra_tables = []
        result.modified_tables = []
        result.missing_user_defined_types = ["type1"]
        result.extra_user_defined_types = ["type2"]

        schema_diff = SchemaDiff(object_name="public", schema_name="public")

        udt_diff = UserDefinedTypeDiff(
            object_name="status_type",
            type_name="status_type",
            type_category_changed=("ENUM", "DOMAIN"),
            base_type_changed=("VARCHAR(10)", "INTEGER"),
            attributes_changed=True,
            expected_attributes={"field1": "VARCHAR"},
            actual_attributes={"field1": "TEXT"},
            enum_values_changed=True,
            expected_enum_values=["active", "inactive"],
            actual_enum_values=["active", "inactive", "pending"],
            definition_changed=True,
        )
        udt_diff._calculate_diffs()

        schema_diff.modified_user_defined_types = [udt_diff]
        result.set_schema_diff(schema_diff)
        result.complete()

        json_output = formatter.format_result(
            result=result, schema="test", database_name="test_db", command_type="DIFF"
        )
        parsed = json.loads(json_output)

        assert "modified_user_defined_types" in parsed
        assert len(parsed["modified_user_defined_types"]) == 1
        mod_udt = parsed["modified_user_defined_types"][0]
        assert mod_udt["type_name"] == "status_type"
        assert "type_category" in mod_udt["changes"]
        assert "base_type" in mod_udt["changes"]
        assert "attributes" in mod_udt["changes"]
        assert "enum_values" in mod_udt["changes"]
        assert mod_udt["changes"]["definition"] is True

    def test_format_result_multi_command_mode(self):
        """Test format_result with multi-command mode."""
        formatter = JsonFormatter()
        formatter.set_multi_command_mode(True)

        # Add first command result
        result1 = MigrateResult()
        result1.success = True
        result1.start_time = datetime(2023, 1, 1, 10, 0, 0)
        result1.end_time = datetime(2023, 1, 1, 10, 5, 0)
        result1.complete()
        formatter.add_command_result("MIGRATE", result1)

        # Add second command result
        result2 = CleanResult()
        result2.success = True
        result2.start_time = datetime(2023, 1, 1, 10, 5, 0)
        result2.end_time = datetime(2023, 1, 1, 10, 6, 0)
        result2.complete()
        formatter.add_command_result("CLEAN", result2)

        # Format with last result
        json_output = formatter.format_result(
            result=result2, schema="test", database_name="test_db", command_type="CLEAN"
        )
        parsed = json.loads(json_output)

        assert parsed["multi_command"] is True
        assert "commands" in parsed
        assert len(parsed["commands"]) == 2
        assert parsed["commands"][0]["command"] == "MIGRATE"
        assert parsed["commands"][1]["command"] == "CLEAN"
        # Times are formatted from datetime objects
        assert parsed["start_time"] is not None
        assert parsed["end_time"] is not None

    def test_format_result_multi_command_with_failure(self):
        """Test format_result with multi-command mode where one fails."""
        formatter = JsonFormatter()
        formatter.set_multi_command_mode(True)

        result1 = MigrateResult()
        result1.success = True
        result1.complete()
        formatter.add_command_result("MIGRATE", result1)

        result2 = CleanResult()
        result2.success = False
        result2.error_message = "Clean failed"
        result2.complete()
        formatter.add_command_result("CLEAN", result2)

        json_output = formatter.format_result(
            result=result2, schema="test", database_name="test_db", command_type="CLEAN"
        )
        parsed = json.loads(json_output)

        assert parsed["status"] == "FAILED"
        assert parsed["commands"][1]["status"] == "FAILED"

    def test_format_result_json_serialization_error(self):
        """Test format_result handles JSON serialization errors."""
        formatter = JsonFormatter()
        result = OperationResult(success=True)
        result.complete()

        # Mock json.dumps to raise TypeError on first call (the actual serialization)
        original_dumps = json.dumps
        call_count = [0]

        def mock_dumps(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:  # First call (the actual serialization)
                raise TypeError("Cannot serialize")
            return original_dumps(*args, **kwargs)

        with patch("core.logger.formatters.jsonformatter.json.dumps", side_effect=mock_dumps):
            json_output = formatter.format_result(
                result=result, schema="test", database_name="test_db", command_type="INFO"
            )
            parsed = json.loads(json_output)

            assert parsed["status"] == "FAILED"
            assert "error" in parsed
            assert "Failed to serialize JSON log" in parsed["error"]

    def test_format_result_file_write_error(self):
        """Test format_result handles file write errors."""
        formatter = JsonFormatter()
        result = OperationResult(success=True)
        result.complete()

        # Use a path that will cause write error (e.g., directory doesn't exist)
        output_file = Path("/nonexistent/dir/file.json")

        json_output = formatter.format_result(
            result=result,
            schema="test",
            database_name="test_db",
            command_type="INFO",
            output_file=output_file,
        )

        # Should still return JSON string even if file write fails
        parsed = json.loads(json_output)
        assert parsed["status"] == "SUCCESS"

    def test_set_current_command(self):
        """Test set_current_command."""
        formatter = JsonFormatter()
        formatter.set_current_command("MIGRATE")

        assert formatter.current_command == "MIGRATE"
        assert formatter.using_multi_command is True

    def test_add_command_result(self):
        """Test add_command_result."""
        formatter = JsonFormatter()
        result = OperationResult(success=True)
        result.complete()

        formatter.add_command_result("MIGRATE", result)

        assert len(formatter.command_results) == 1
        assert formatter.command_results[0]["command_type"] == "MIGRATE"
        assert formatter.command_results[0]["result"] == result

    def test_format_command_result_data_with_warnings(self):
        """Test _format_command_result_data with warnings."""
        formatter = JsonFormatter()
        result = MigrateResult()
        result.success = True
        result.warnings = ["Warning 1", "Warning 2"]
        result.complete()

        cmd_data = formatter._format_command_result_data(result, "test", "test_db", "MIGRATE")

        assert cmd_data["warnings"] == ["Warning 1", "Warning 2"]

    def test_format_command_result_data_without_warnings(self):
        """Test _format_command_result_data without warnings."""
        formatter = JsonFormatter()
        result = OperationResult(success=True)
        result.complete()

        cmd_data = formatter._format_command_result_data(result, "test", "test_db", "INFO")

        assert cmd_data["warnings"] == []

    def test_format_command_result_data_with_non_migrationinfo_migrations(self):
        """Test _format_command_result_data with non-MigrationInfo migrations."""
        formatter = JsonFormatter()
        result = MigrateResult()
        result.success = True

        # Create a simple object instead of MigrationInfo
        class SimpleMigration:
            def __init__(self):
                self.script = "V1__Test.sql"
                self.version = "1.0.0"
                self.description = "Test"
                self.type = "SQL"
                self.status = "SUCCESS"
                self.execution_time = 1000
                self.installed_on = datetime(2023, 1, 1, 12, 0, 0)
                self.installed_by = "user"
                self.checksum = "abc123"
                self.error = None

        result.migrations = [SimpleMigration()]
        result.complete()

        cmd_data = formatter._format_command_result_data(result, "test", "test_db", "MIGRATE")

        assert len(cmd_data["migrations"]) == 1
        assert cmd_data["migrations"][0]["script"] == "V1__Test.sql"
        assert cmd_data["migrations"][0]["version"] == "1.0.0"

    def test_format_command_result_data_baseline(self):
        """Test _format_command_result_data for baseline command."""
        formatter = JsonFormatter()
        from core.logger.results import BaselineResult

        result = BaselineResult()
        result.success = True
        result.init_version = "1.0.0"
        result.description = "Custom baseline"
        result.complete()

        cmd_data = formatter._format_command_result_data(result, "test", "test_db", "BASELINE")

        assert cmd_data["version"] == "1.0.0"
        assert cmd_data["baseline_description"] == "Custom baseline"

    def test_format_command_result_data_baseline_default_description(self):
        """Test _format_command_result_data for baseline without description."""
        formatter = JsonFormatter()
        from core.logger.results import BaselineResult

        result = BaselineResult()
        result.success = True
        result.init_version = "1.0.0"
        result.complete()

        cmd_data = formatter._format_command_result_data(result, "test", "test_db", "BASELINE")

        assert cmd_data["version"] == "1.0.0"
        assert cmd_data["baseline_description"] == "Initial baseline"

    def test_format_command_result_data_migrate_version_range(self):
        """Test _format_command_result_data for migrate with version range."""
        formatter = JsonFormatter()
        result = MigrateResult()
        result.success = True
        result.from_version = "1.0.0"
        result.to_version = "2.0.0"
        result.complete()

        cmd_data = formatter._format_command_result_data(result, "test", "test_db", "MIGRATE")

        assert cmd_data["from_version"] == "1.0.0"
        assert cmd_data["to_version"] == "2.0.0"

    def test_format_command_result_data_clean(self):
        """Test _format_command_result_data for clean command."""
        formatter = JsonFormatter()
        result = CleanResult()
        result.success = True
        result.add_schema_dropped("schema1")
        result.add_table_dropped("table1")
        result.complete()

        cmd_data = formatter._format_command_result_data(result, "test", "test_db", "CLEAN")

        assert "objects_dropped" in cmd_data
        assert "schema" in cmd_data["objects_dropped"]
        assert "table" in cmd_data["objects_dropped"]

    def test_format_command_result_data_clean_without_get_objects_by_type(self):
        """Test _format_command_result_data for clean without get_objects_by_type."""
        formatter = JsonFormatter()
        result = CleanResult()
        result.success = True
        # Don't add get_objects_by_type method
        result.complete()

        cmd_data = formatter._format_command_result_data(result, "test", "test_db", "CLEAN")

        assert cmd_data["objects_dropped"] == {}

    def test_format_command_result_data_diff(self):
        """Test _format_command_result_data for diff command."""
        formatter = JsonFormatter()
        result = DiffResult()
        result.success = True
        result.source_type = "postgresql"
        result.target_type = "mysql"
        result.total_differences = 5
        result.error_count = 1
        result.warning_count = 2
        result.info_count = 2
        result.missing_tables = ["table1"]
        result.extra_tables = ["table2"]
        result.modified_tables = []
        result.missing_user_defined_types = ["type1"]
        result.extra_user_defined_types = ["type2"]

        schema_diff = SchemaDiff(object_name="public", schema_name="public")
        result.set_schema_diff(schema_diff)
        result.complete()

        cmd_data = formatter._format_command_result_data(result, "test", "test_db", "DIFF")

        assert "comparison" in cmd_data
        assert cmd_data["comparison"]["source_type"] == "postgresql"
        assert "summary" in cmd_data
        assert cmd_data["summary"]["missing_tables"] == len(result.missing_tables)
        assert cmd_data["missing_tables"] == result.missing_tables

    def test_migration_to_dict_with_string_installed_on(self):
        """Test _migration_to_dict with string installed_on."""
        formatter = JsonFormatter()
        migration = MigrationInfo(
            script="V1__Test.sql",
            version="1.0.0",
            description="Test",
            installed_on="2023-01-01T12:00:00",  # String format
        )

        result_dict = formatter._migration_to_dict(migration)

        assert result_dict["installed_on"] == "2023-01-01T12:00:00"

    def test_migration_to_dict_with_datetime_installed_on(self):
        """Test _migration_to_dict with datetime installed_on."""
        formatter = JsonFormatter()
        migration = MigrationInfo(
            script="V1__Test.sql",
            version="1.0.0",
            description="Test",
            installed_on=datetime(2023, 1, 1, 12, 0, 0),
        )

        result_dict = formatter._migration_to_dict(migration)

        assert "2023-01-01T12:00:00" in result_dict["installed_on"]

    def test_migration_to_dict_with_other_installed_on(self):
        """Test _migration_to_dict with other installed_on type."""
        formatter = JsonFormatter()
        migration = MigrationInfo(script="V1__Test.sql", version="1.0.0", description="Test")
        # Set installed_on to something else
        migration.installed_on = 12345

        result_dict = formatter._migration_to_dict(migration)

        assert result_dict["installed_on"] == "12345"

    def test_sanitize_message_non_string(self):
        """Test _sanitize_message with non-string input."""
        formatter = JsonFormatter()
        result = formatter._sanitize_message(123)
        assert result == "123"

        result = formatter._sanitize_message(None)
        assert result == "None"

    def test_sanitize_for_json_dict(self):
        """Test _sanitize_for_json with dict."""
        formatter = JsonFormatter()
        result = formatter._sanitize_for_json({"key": "value", "num": 123})
        assert result == {"key": "value", "num": 123}

    def test_sanitize_for_json_list(self):
        """Test _sanitize_for_json with list."""
        formatter = JsonFormatter()
        result = formatter._sanitize_for_json(["item1", "item2", 123])
        assert result == ["item1", "item2", 123]

    def test_sanitize_for_json_datetime(self):
        """Test _sanitize_for_json with datetime."""
        formatter = JsonFormatter()
        dt = datetime(2023, 1, 1, 12, 0, 0)
        result = formatter._sanitize_for_json(dt)
        assert result == "2023-01-01 12:00:00"

    def test_sanitize_for_json_other_types(self):
        """Test _sanitize_for_json with other types."""
        formatter = JsonFormatter()
        result = formatter._sanitize_for_json(123)
        assert result == 123

        result = formatter._sanitize_for_json(True)
        assert result is True

        result = formatter._sanitize_for_json(None)
        assert result is None

        # Custom object
        class CustomObj:
            def __str__(self):
                return "custom"

        result = formatter._sanitize_for_json(CustomObj())
        assert result == "custom"

    def test_json_default_datetime(self):
        """Test _json_default with datetime."""
        formatter = JsonFormatter()
        dt = datetime(2023, 1, 1, 12, 0, 0)
        result = formatter._json_default(dt)
        assert result == "2023-01-01 12:00:00"

    def test_json_default_with_dict(self):
        """Test _json_default with object having __dict__."""
        formatter = JsonFormatter()

        class TestObj:
            def __init__(self):
                self.attr1 = "value1"
                self.attr2 = 123

        obj = TestObj()
        result = formatter._json_default(obj)
        assert result == {"attr1": "value1", "attr2": 123}

    def test_json_default_fallback(self):
        """Test _json_default fallback to str."""
        formatter = JsonFormatter()
        result = formatter._json_default(12345)
        assert result == "12345"

    def test_count_log_levels(self):
        """Test _count_log_levels."""
        formatter = JsonFormatter()
        formatter.add_log_entry("INFO", "test", "message1")
        formatter.add_log_entry("ERROR", "test", "message2")
        formatter.add_log_entry("INFO", "test", "message3")
        formatter.add_log_entry("WARN", "test", "message4")

        counts = formatter._count_log_levels()

        assert counts["INFO"] == 2
        assert counts["ERROR"] == 1
        assert counts["WARN"] == 1

    def test_count_log_levels_empty(self):
        """Test _count_log_levels with no entries."""
        formatter = JsonFormatter()
        counts = formatter._count_log_levels()
        assert counts == {}

    def test_format_result_version_detection(self):
        """Test format_result version detection (may be None if not available)."""
        formatter = JsonFormatter()
        result = OperationResult(success=True)
        result.complete()

        json_output = formatter.format_result(
            result=result, schema="test", database_name="test_db", command_type="INFO"
        )
        parsed = json.loads(json_output)
        # Version may or may not be detected depending on environment
        assert "dblift_version" in parsed
