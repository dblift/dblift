"""Tests for JSON formatter."""

import json
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from core.logger.formatters.jsonformatter import JsonFormatter
from core.logger.results import (
    BaselineResult,
    CleanResult,
    InfoResult,
    MigrateResult,
    MigrationInfo,
    MigrationSqlInfo,
    OperationResult,
    RepairResult,
    ValidateResult,
)


@pytest.mark.unit
class TestJsonFormatter:
    """Test JSON formatter functionality."""

    def test_formatter_initialization(self):
        """Test formatter initialization."""
        formatter = JsonFormatter()

        assert formatter.log_entries == []

    def test_format_event(self):
        """Test formatting of individual log events."""
        formatter = JsonFormatter()

        # Create a mock log event
        mock_event = Mock()
        mock_event.level.value = "INFO"
        mock_event.component = "test_component"
        mock_event.message = "Test message"
        mock_event.timestamp = datetime(2023, 1, 1, 12, 0, 0)

        result = formatter.format_event(mock_event)

        # Should return JSON string
        parsed = json.loads(result)
        assert parsed["timestamp"] == "2023-01-01 12:00:00"
        assert parsed["level"] == "INFO"
        assert parsed["name"] == "test_component"
        assert parsed["message"] == "Test message"

        # Should add entry to log_entries
        assert len(formatter.log_entries) == 1
        assert formatter.log_entries[0] == parsed

    def test_format_header(self):
        """Test formatting of header (should be empty for JSON)."""
        formatter = JsonFormatter()

        result = formatter.format_header(schema="test_schema", database_name="test_db")

        assert result == ""

    def test_format_footer(self):
        """Test formatting of footer (should be empty for JSON)."""
        formatter = JsonFormatter()

        result = formatter.format_footer()

        assert result == ""

    def test_format_result_includes_sql_only_when_show_sql_enabled(self):
        formatter = JsonFormatter()
        result = MigrateResult()
        result.show_sql = True
        result.add_sql_migration(
            MigrationSqlInfo("V1__init.sql", version="1", statements=["CREATE TABLE users"])
        )

        output = json.loads(formatter.format_result(result, "public", "test", "MIGRATE"))

        assert output["show_sql"] is True
        assert output["sql"][0]["script"] == "V1__init.sql"
        assert output["sql"][0]["statements"] == ["CREATE TABLE users"]

    def test_format_result_hides_sql_when_show_sql_disabled(self):
        formatter = JsonFormatter()
        result = MigrateResult()
        result.show_sql = False
        result.add_sql_migration(
            MigrationSqlInfo("V1__init.sql", version="1", statements=["CREATE TABLE users"])
        )

        output = json.loads(formatter.format_result(result, "public", "test", "MIGRATE"))

        assert "show_sql" not in output
        assert "sql" not in output

    def test_add_log_entry(self):
        """Test adding log entries."""
        formatter = JsonFormatter()

        with patch("core.logger.formatters.jsonformatter.datetime") as mock_datetime:
            mock_datetime.now.return_value.strftime.return_value = "2023-01-01 12:00:00"

            formatter.add_log_entry("ERROR", "migration", "Test error message")

            assert len(formatter.log_entries) == 1
            entry = formatter.log_entries[0]
            assert entry["timestamp"] == "2023-01-01 12:00:00"
            assert entry["level"] == "ERROR"
            assert entry["name"] == "migration"
            assert entry["message"] == "Test error message"

    def test_format_result_basic_success(self):
        """Test basic format_result with successful operation."""
        formatter = JsonFormatter()

        result = OperationResult(success=True)
        result.complete()

        with patch("core.logger.formatters.jsonformatter.datetime") as mock_datetime:
            mock_datetime.now.return_value.strftime.return_value = "2023-01-01 12:00:00"

            json_output = formatter.format_result(
                result=result, schema="test_schema", database_name="test_db", command_type="MIGRATE"
            )

            parsed = json.loads(json_output)
            assert parsed["timestamp"] == "2023-01-01 12:00:00"
            # Note: "command" field is not in main output - use "commands" array for multi-command scenarios
            assert parsed["schema"] == "test_schema"
            assert parsed["database"] == "test_db"
            assert parsed["status"] == "SUCCESS"
            assert "execution_time_ms" in parsed
            assert parsed["warnings"] == []
            # Note: migrations are not included in JSON output (only structured command data)
            assert "migrations" not in parsed
            # Verify new fields are present
            assert "log_format_version" in parsed
            # Note: log_entries are not included in JSON output (only structured command data)

    def test_format_result_basic_failure(self):
        """Test basic format_result with failed operation."""
        formatter = JsonFormatter()

        result = OperationResult(success=False, error_message="Test error")
        result.complete()

        with patch("core.logger.formatters.jsonformatter.datetime") as mock_datetime:
            mock_datetime.now.return_value.strftime.return_value = "2023-01-01 12:00:00"

            json_output = formatter.format_result(
                result=result,
                schema="test_schema",
                database_name="test_db",
                command_type="VALIDATE",
            )

            parsed = json.loads(json_output)
            assert parsed["status"] == "FAILED"
            assert parsed["error"] == "Test error"

    def test_format_result_with_warnings(self):
        """Test format_result with warnings."""
        formatter = JsonFormatter()

        result = MigrateResult()
        result.success = True
        result.warnings = ["Warning 1", "Warning 2"]
        result.complete()

        json_output = formatter.format_result(
            result=result, schema="test_schema", database_name="test_db", command_type="MIGRATE"
        )

        parsed = json.loads(json_output)
        assert parsed["warnings"] == ["Warning 1", "Warning 2"]

    def test_format_result_with_migrations(self):
        """Test format_result with migration data - migrations should not be in main output but should be in commands array."""
        formatter = JsonFormatter()
        formatter.set_multi_command_mode(True)

        result = MigrateResult()
        migration1 = MigrationInfo(
            script="V1__Initial.sql",
            version="1.0.0",
            description="Initial migration",
            type="SQL",
            status="SUCCESS",
            execution_time=1500,
        )
        migration2 = MigrationInfo(
            script="V2__Add_tables.sql",
            version="2.0.0",
            description="Add tables",
            type="SQL",
            status="PENDING",
            execution_time=0,
        )
        result.add_migration(migration1)
        result.add_migration(migration2)
        result.complete()
        formatter.add_command_result("MIGRATE", result)

        json_output = formatter.format_result(
            result=result, schema="test_schema", database_name="test_db", command_type="MIGRATE"
        )

        parsed = json.loads(json_output)
        # Migrations should not be included in main output
        assert "migrations" not in parsed
        assert "migration_count" not in parsed

        # But should be included in commands array
        assert "commands" in parsed
        assert len(parsed["commands"]) == 1
        cmd = parsed["commands"][0]
        assert "migrations" in cmd
        assert len(cmd["migrations"]) == 2
        assert cmd["migration_count"] == 2

    def test_format_result_with_baseline_version(self):
        """Test format_result with baseline version information."""
        formatter = JsonFormatter()

        result = BaselineResult()
        result.success = True
        result.init_version = "1.0.0"
        result.description = "Custom baseline description"
        result.complete()

        json_output = formatter.format_result(
            result=result, schema="test_schema", database_name="test_db", command_type="BASELINE"
        )

        parsed = json.loads(json_output)
        assert parsed["version"] == "1.0.0"
        assert parsed["baseline_description"] == "Custom baseline description"

    def test_format_result_with_baseline_default_description(self):
        """Test format_result with baseline and default description."""
        formatter = JsonFormatter()

        result = BaselineResult()
        result.success = True
        result.init_version = "1.0.0"
        # No description attribute
        result.complete()

        json_output = formatter.format_result(
            result=result, schema="test_schema", database_name="test_db", command_type="BASELINE"
        )

        parsed = json.loads(json_output)
        assert parsed["version"] == "1.0.0"
        assert parsed["baseline_description"] == "Initial baseline"

    def test_format_result_with_migrate_version_range(self):
        """Test format_result with migrate command version range."""
        formatter = JsonFormatter()

        result = MigrateResult()
        result.success = True
        result.from_version = "1.0.0"
        result.to_version = "2.0.0"
        result.complete()

        json_output = formatter.format_result(
            result=result, schema="test_schema", database_name="test_db", command_type="MIGRATE"
        )

        parsed = json.loads(json_output)
        assert parsed["from_version"] == "1.0.0"
        assert parsed["to_version"] == "2.0.0"

    def test_format_result_with_clean_dropped_items(self):
        """Test format_result with clean command dropped items."""
        formatter = JsonFormatter()

        result = CleanResult()
        result.success = True
        result.add_schema_dropped("schema1")
        result.add_schema_dropped("schema2")
        result.add_table_dropped("table1")
        result.add_table_dropped("table2")
        result.add_table_dropped("table3")
        result.complete()

        json_output = formatter.format_result(
            result=result, schema="test_schema", database_name="test_db", command_type="CLEAN"
        )

        parsed = json.loads(json_output)
        # Check objects_dropped contains all objects grouped by type
        assert "objects_dropped" in parsed
        assert set(parsed["objects_dropped"].get("schema", [])) == {"schema1", "schema2"}
        assert set(parsed["objects_dropped"].get("table", [])) == {"table1", "table2", "table3"}
        # Individual arrays should not be present
        assert "schemas_dropped" not in parsed
        assert "tables_dropped" not in parsed

    def test_format_result_with_clean_no_dropped_items(self):
        """Test format_result with clean command but no dropped items."""
        formatter = JsonFormatter()

        result = CleanResult()
        result.success = True
        result.complete()

        json_output = formatter.format_result(
            result=result, schema="test_schema", database_name="test_db", command_type="CLEAN"
        )

        parsed = json.loads(json_output)
        # Check objects_dropped is present (even if empty)
        assert "objects_dropped" in parsed
        assert parsed["objects_dropped"] == {}
        # Individual arrays should not be present
        assert "schemas_dropped" not in parsed
        assert "tables_dropped" not in parsed

    def test_format_result_with_output_file(self):
        """Test format_result with output file."""
        formatter = JsonFormatter()

        result = OperationResult(success=True)
        result.complete()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp_file:
            output_path = Path(tmp_file.name)

            json_output = formatter.format_result(
                result=result,
                schema="test_schema",
                database_name="test_db",
                command_type="INFO",
                output_file=output_path,
            )

            # Check file was written
            assert output_path.exists()
            with open(output_path, "r") as f:
                file_content = f.read()

            # File content should match returned JSON
            assert file_content == json_output

            # Verify it's valid JSON
            parsed = json.loads(file_content)
            # Note: "command" field is not in main output - use "commands" array for multi-command scenarios
            assert "command" not in parsed

            # Cleanup
            output_path.unlink()

    def test_migration_to_dict(self):
        """Test _migration_to_dict method."""
        formatter = JsonFormatter()

        migration = MigrationInfo(
            script="V1__Test.sql",
            version="1.0.0",
            description="Test migration",
            type="SQL",
            status="SUCCESS",
            installed_on=datetime(2023, 1, 1, 12, 0, 0),
            installed_by="test_user",
            checksum="abc123",
            execution_time=1500,
            error=None,
        )

        result_dict = formatter._migration_to_dict(migration)

        assert result_dict["script"] == "V1__Test.sql"
        assert result_dict["version"] == "1.0.0"
        assert result_dict["description"] == "Test migration"
        assert result_dict["type"] == "SQL"
        assert result_dict["status"] == "SUCCESS"
        assert result_dict["installed_on"] == "2023-01-01T12:00:00"
        assert result_dict["installed_by"] == "test_user"
        assert result_dict["checksum"] == "abc123"
        assert result_dict["execution_time"] == 1500
        assert result_dict["error"] is None

    def test_migration_to_dict_no_installed_on(self):
        """Test _migration_to_dict with no installed_on date."""
        formatter = JsonFormatter()

        migration = MigrationInfo(
            script="V1__Test.sql", version="1.0.0", description="Test migration", installed_on=None
        )

        result_dict = formatter._migration_to_dict(migration)

        assert result_dict["installed_on"] is None

    def test_get_output_filename(self):
        """Test get_output_filename generation."""
        formatter = JsonFormatter()

        with patch("core.logger.formatters.jsonformatter.datetime") as mock_datetime:
            mock_datetime.now.return_value.strftime.return_value = "20230101_120000"

            filename = formatter.get_output_filename("test_schema", "test_db", "migrate")

            assert filename == "Dblift_test_schema_test_db_migrate_20230101_120000.json"

    def test_format_result_migration_without_all_attributes(self):
        """Test format_result with migrations - migrations should not be in JSON output."""
        formatter = JsonFormatter()

        result = MigrateResult()

        # Create a simple object instead of Mock to avoid JSON serialization issues
        class SimpleMigration:
            def __init__(self):
                self.script = "V1__Test.sql"
                self.version = "1.0.0"
                # Missing: description, type, status, execution_time

        migration = SimpleMigration()
        result.migrations = [migration]
        result.complete()

        json_output = formatter.format_result(
            result=result, schema="test_schema", database_name="test_db", command_type="MIGRATE"
        )

        parsed = json.loads(json_output)
        # Migrations should not be included in JSON output
        assert "migrations" not in parsed
        assert "migration_count" not in parsed

    def test_format_result_no_warnings_attribute(self):
        """Test format_result with result that has no warnings attribute."""
        formatter = JsonFormatter()

        result = OperationResult(success=True)
        # Explicitly ensure no warnings attribute
        if hasattr(result, "warnings"):
            delattr(result, "warnings")
        result.complete()

        json_output = formatter.format_result(
            result=result, schema="test_schema", database_name="test_db", command_type="INFO"
        )

        parsed = json.loads(json_output)
        assert parsed["warnings"] == []

    def test_multiple_log_entries(self):
        """Test handling multiple log entries."""
        formatter = JsonFormatter()

        # Add multiple log entries
        formatter.add_log_entry("INFO", "migration", "Starting migration")
        formatter.add_log_entry("DEBUG", "database", "Connecting to database")
        formatter.add_log_entry("ERROR", "migration", "Migration failed")

        assert len(formatter.log_entries) == 3
        assert formatter.log_entries[0]["level"] == "INFO"
        assert formatter.log_entries[1]["level"] == "DEBUG"
        assert formatter.log_entries[2]["level"] == "ERROR"

    def test_format_result_edge_cases(self):
        """Test format_result with edge cases."""
        formatter = JsonFormatter()

        # Test with empty strings
        result = OperationResult(success=True)
        result.complete()

        json_output = formatter.format_result(
            result=result, schema="", database_name="", command_type=""
        )

        parsed = json.loads(json_output)
        assert parsed["schema"] == ""
        assert parsed["database"] == ""
        # Note: "command" field is not in main output - use "commands" array for multi-command scenarios
        assert "command" not in parsed

    def test_format_result_json_serialization(self):
        """Test that format_result produces valid JSON."""
        formatter = JsonFormatter()

        result = MigrateResult()
        result.success = True
        result.warnings = ["Test warning"]

        # Add migration with various data types
        migration = MigrationInfo(
            script="V1__Test.sql",
            version="1.0.0",
            description="Test migration",
            execution_time=1500,
        )
        result.add_migration(migration)
        result.complete()

        json_output = formatter.format_result(
            result=result, schema="test_schema", database_name="test_db", command_type="MIGRATE"
        )

        # Should be valid JSON
        parsed = json.loads(json_output)

        # Should be properly formatted with indentation
        assert json_output.count("\n") > 1  # Multi-line JSON
        assert "  " in json_output  # Has indentation

        # Note: log_entries are not included in JSON output (only structured command data)

    def test_format_event_multiple_calls(self):
        """Test format_event with multiple calls."""
        formatter = JsonFormatter()

        # Create multiple mock events
        events = []
        for i in range(3):
            event = Mock()
            event.level.value = f"LEVEL{i}"
            event.component = f"component{i}"
            event.message = f"message{i}"
            event.timestamp = datetime(2023, 1, 1, 12, i, 0)
            events.append(event)

        # Format all events
        results = []
        for event in events:
            result = formatter.format_event(event)
            results.append(json.loads(result))

        # Check all were added to log_entries
        assert len(formatter.log_entries) == 3

        # Check each result
        for i, result in enumerate(results):
            assert result["level"] == f"LEVEL{i}"
            assert result["name"] == f"component{i}"
            assert result["message"] == f"message{i}"
            assert result["timestamp"] == f"2023-01-01 12:0{i}:00"

    def test_format_result_excludes_log_entries(self):
        """Test that format_result excludes log entries from JSON output."""
        formatter = JsonFormatter()

        # Add some log entries (tracked internally but not in JSON output)
        formatter.add_log_entry("INFO", "test", "First message")
        formatter.add_log_entry("WARN", "test", "Second message")
        formatter.add_log_entry("ERROR", "test", "Third message")

        result = OperationResult(success=True)
        result.complete()

        json_output = formatter.format_result(
            result=result, schema="test_schema", database_name="test_db", command_type="TEST"
        )

        parsed = json.loads(json_output)
        # Log entries should NOT be in JSON output (only structured command data)
        assert "log_entries" not in parsed
        # Summary should not contain log statistics
        if "summary" in parsed:
            assert "total_log_entries" not in parsed["summary"]
            assert "log_level_counts" not in parsed["summary"]

    def test_format_result_valid_json_structure(self):
        """Test that format_result produces a complete, valid JSON structure."""
        formatter = JsonFormatter()

        result = OperationResult(success=True)
        result.complete()

        json_output = formatter.format_result(
            result=result, schema="test_schema", database_name="test_db", command_type="TEST"
        )

        # Verify it's valid JSON
        parsed = json.loads(json_output)

        # Verify required top-level fields
        required_fields = [
            "log_format_version",
            "timestamp",
            "schema",
            "database",
            "status",
            "execution_time_ms",
            "warnings",
        ]
        # Note: "command" field is not in main output - use "commands" array for multi-command scenarios
        # Note: migrations are not included in JSON output
        for field in required_fields:
            assert field in parsed, f"Missing required field: {field}"

        # Note: log_entries, total_log_entries, and log_level_counts are not included
        # JSON logs contain only structured command output, not text log messages
