"""Unit tests for OutputFormatter."""

from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from core.logger.formatters.formatter import OutputFormatter
from core.logger.results import (
    BaselineResult,
    CleanResult,
    InfoResult,
    MigrateResult,
    MigrationQueryResultInfo,
    MigrationSqlInfo,
    OperationResult,
    RepairResult,
    UndoResult,
    ValidateResult,
)

# Migration may still be in legacy location
try:
    from core.migration.migration import Migration, MigrationType
except ImportError:
    from core.migration.migration import Migration, MigrationType


pytestmark = [pytest.mark.unit]


class TestOutputFormatter:
    """Test OutputFormatter functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.formatter = OutputFormatter()

    def test_formatter_initialization(self):
        """Test formatter initialization."""
        formatter = OutputFormatter()
        assert formatter is not None
        # HTML and JSON formatters may or may not be available depending on dependencies

    def test_get_command_type(self):
        """Test _get_command_type method."""
        # Test with different result types
        migrate_result = MigrateResult()
        assert self.formatter._get_command_type(migrate_result) == "migrate"

        undo_result = UndoResult()
        assert self.formatter._get_command_type(undo_result) == "undo"

        clean_result = CleanResult()
        assert self.formatter._get_command_type(clean_result) == "clean"

        info_result = InfoResult()
        assert self.formatter._get_command_type(info_result) == "info"

        validate_result = ValidateResult()
        assert self.formatter._get_command_type(validate_result) == "validate"

        baseline_result = BaselineResult()
        assert self.formatter._get_command_type(baseline_result) == "baseline"

        repair_result = RepairResult()
        assert self.formatter._get_command_type(repair_result) == "repair"

        # Test with generic result
        generic_result = OperationResult()
        assert self.formatter._get_command_type(generic_result) == "operation"

    def test_format_migrate_show_sql_prints_statements(self):
        result = MigrateResult()
        result.show_sql = True
        result.add_sql_migration(
            MigrationSqlInfo("V1__init.sql", version="1", statements=["CREATE TABLE users"])
        )

        output = self.formatter.format_migrate(result)

        assert "CREATE TABLE users" in output

    def test_format_migrate_without_show_sql_hides_statements(self):
        result = MigrateResult()
        result.show_sql = False
        result.add_sql_migration(
            MigrationSqlInfo("V1__init.sql", version="1", statements=["CREATE TABLE users"])
        )

        output = self.formatter.format_migrate(result)

        assert "CREATE TABLE users" not in output

    def test_format_undo_show_sql_prints_statements(self):
        result = UndoResult()
        result.show_sql = True
        result.add_sql_migration(
            MigrationSqlInfo("U1__init.sql", version="1", statements=["DROP TABLE users"])
        )

        output = self.formatter.format_undo(result)

        assert "DROP TABLE users" in output

    def test_format_migrate_show_query_results_prints_table(self):
        result = MigrateResult()
        result.show_query_results = True
        info = MigrationQueryResultInfo("V1__init.sql", version="1")
        info.add_result("SELECT * FROM users", ["id", "name"], [[1, "alice"]])
        result.query_results.append(info)

        output = self.formatter.format_migrate(result)

        assert "Query Results:" in output
        assert "SELECT * FROM users" in output
        assert "alice" in output

    def test_format_migrate_without_show_query_results_hides_table(self):
        result = MigrateResult()
        result.show_query_results = False
        info = MigrationQueryResultInfo("V1__init.sql", version="1")
        info.add_result("SELECT * FROM users", ["id"], [[1]])
        result.query_results.append(info)

        output = self.formatter.format_migrate(result)

        assert "Query Results:" not in output
        assert "SELECT * FROM users" not in output

    def test_format_migrate_query_results_independent_of_show_sql(self):
        """show_sql and show_query_results are independent gates."""
        result = MigrateResult()
        result.show_sql = False
        result.show_query_results = True
        result.add_sql_migration(
            MigrationSqlInfo("V1__init.sql", version="1", statements=["CREATE TABLE users"])
        )
        info = MigrationQueryResultInfo("V1__init.sql", version="1")
        info.add_result("SELECT 1", ["one"], [[1]])
        result.query_results.append(info)

        output = self.formatter.format_migrate(result)

        assert "CREATE TABLE users" not in output
        assert "Query Results:" in output

    def test_format_clean_show_query_results_prints_table(self):
        """CLEAN's --show-query-results panel renders in text output (Bug 3 regression guard)."""
        result = CleanResult()
        result.show_query_results = True
        info = MigrationQueryResultInfo("beforeClean/check.sql", version=None)
        info.add_result("SELECT * FROM users", ["id", "name"], [[1, "alice"]])
        result.query_results.append(info)

        output = self.formatter.format_clean(result)

        assert "Query Results:" in output
        assert "SELECT * FROM users" in output
        assert "alice" in output

    def test_format_clean_without_show_query_results_hides_table(self):
        result = CleanResult()
        result.show_query_results = False
        info = MigrationQueryResultInfo("beforeClean/check.sql", version=None)
        info.add_result("SELECT * FROM users", ["id"], [[1]])
        result.query_results.append(info)

        output = self.formatter.format_clean(result)

        assert "Query Results:" not in output
        assert "SELECT * FROM users" not in output

    def test_format_generic(self):
        """Test format_generic method."""
        # Test successful operation
        result = OperationResult()
        result.success = True
        result.start_time = datetime.fromtimestamp(1000)
        result.end_time = datetime.fromtimestamp(1500)

        output = self.formatter.format_generic(result)
        assert "Operation Report" in output
        assert "Status: SUCCESS" in output
        assert "Execution time:" in output

        # Test failed operation
        result.success = False
        result.error_message = "Test error"
        result.warnings = ["Warning 1", "Warning 2"]

        output = self.formatter.format_generic(result)
        assert "Status: FAILED" in output
        assert "Error: Test error" in output
        assert "Warning 1" in output
        assert "Warning 2" in output

    def test_format_migrate_success(self):
        """Test format_migrate method with successful migration."""
        result = MigrateResult()
        result.success = True
        result.target_schema = "test_schema"
        result.start_time = datetime.fromtimestamp(1000)
        result.end_time = datetime.fromtimestamp(1500)

        # Add a migration
        migration = Mock()
        migration.version = "1.0.1"
        migration.description = "Test migration"
        migration.type = "SQL"
        migration.status = "SUCCESS"
        migration.execution_time = 250
        result.migrations = [migration]

        output = self.formatter.format_migrate(result)
        assert "Database Migration Report" in output
        assert "Schema: test_schema" in output
        assert "Status: SUCCESS" in output
        assert "V1.0.1" in output
        assert "Test migration" in output

    def test_format_migrate_failure(self):
        """Test format_migrate method with failed migration."""
        result = MigrateResult()
        result.success = False
        result.target_schema = "test_schema"
        result.error_message = "Migration failed"
        result.start_time = datetime.fromtimestamp(1000)
        result.end_time = datetime.fromtimestamp(1500)

        output = self.formatter.format_migrate(result)
        assert "Status: FAILED" in output
        assert "Error: Migration failed" in output

    def test_format_migrate_no_migrations(self):
        """Test format_migrate method with no migrations."""
        result = MigrateResult()
        result.success = True
        result.target_schema = "test_schema"
        result.migrations = []
        result.start_time = datetime.fromtimestamp(1000)
        result.end_time = datetime.fromtimestamp(1500)

        output = self.formatter.format_migrate(result)
        assert "No migrations were executed." in output

    def test_format_clean(self):
        """Test formatting clean results."""
        result = CleanResult()
        result.success = True
        result.schema_name = "test_schema"
        result.start_time = datetime.now()
        result.end_time = datetime.now()
        result.add_schema_dropped("old_schema")
        result.add_table_dropped("old_table")

        formatted = self.formatter.format_clean(result)

        assert "Database Clean Report" in formatted
        assert "Schema: test_schema" in formatted
        assert "Status: SUCCESS" in formatted
        assert "old_schema" in formatted
        assert "old_table" in formatted

    def test_format_info(self):
        """Test formatting info results."""
        result = InfoResult()
        result.success = True
        result.schema_name = "test_schema"
        result.start_time = datetime.now()
        result.end_time = datetime.now()
        result.current_schema_version = "1.0.0"
        result.migrations = []

        formatted = self.formatter.format_info(result)

        assert "Database Info Report" in formatted
        assert "Schema: test_schema" in formatted
        assert "Status: SUCCESS" in formatted
        assert "Current schema version: 1.0.0" in formatted

    def test_format_validate(self):
        """Test formatting validate results."""
        result = ValidateResult()
        result.success = True
        result.schema_name = "test_schema"
        result.start_time = datetime.now()
        result.end_time = datetime.now()
        result.error_count = 0
        result.failed_migrations = []
        result.validated_migrations = []

        formatted = self.formatter.format_validate(result)

        assert "Database Validation Report" in formatted
        assert "Status: SUCCESS" in formatted
        assert "All migrations are properly applied" in formatted

    def test_format_baseline(self):
        """Test formatting baseline results."""
        result = BaselineResult()
        result.success = True
        result.schema_name = "test_schema"
        result.start_time = datetime.now()
        result.end_time = datetime.now()
        result.baseline_version = "1.0.0"

        formatted = self.formatter.format_baseline(result)

        assert "Database Baseline Report" in formatted
        assert "Schema: test_schema" in formatted
        assert "Status: SUCCESS" in formatted

    def test_format_repair(self):
        """Test formatting repair results."""
        result = RepairResult()
        result.success = True
        result.schema_name = "test_schema"
        result.start_time = datetime.now()
        result.end_time = datetime.now()
        result.repaired_migrations = []

        formatted = self.formatter.format_repair(result)

        assert "Database Repair Report" in formatted
        assert "Status: SUCCESS" in formatted
        assert "No migrations required repair" in formatted

    def test_format_text_default(self):
        """Test format method with text format (default)."""
        result = MigrateResult()
        result.success = True
        result.target_schema = "test_schema"
        result.start_time = datetime.fromtimestamp(1000)
        result.end_time = datetime.fromtimestamp(1500)

        output = self.formatter.format(result, "text", "test_schema", "test_db")
        assert "Database Migration Report" in output
        assert "Schema: test_schema" in output

    def test_format_with_schema_override(self):
        """Test format method with schema name override."""
        result = MigrateResult()
        result.success = True
        result.target_schema = None  # No schema set
        result.start_time = datetime.fromtimestamp(1000)
        result.end_time = datetime.fromtimestamp(1500)

        output = self.formatter.format(result, "text", "override_schema", "test_db")
        assert "Schema: override_schema" in output

    @patch("core.logger.formatters._formatter_impl.HtmlFormatter")
    def test_format_html_when_available(self, mock_html_formatter_class):
        """Test format method with HTML format when available."""
        # Mock the HTML formatter
        mock_html_formatter = Mock()
        mock_html_formatter.format_result.return_value = "<html>Test HTML</html>"
        mock_html_formatter_class.return_value = mock_html_formatter

        # Create formatter with mocked HTML formatter
        formatter = OutputFormatter()
        formatter.html_formatter = mock_html_formatter

        result = MigrateResult()
        result.success = True

        output = formatter.format(result, "html", "test_schema", "test_db")
        assert output == "<html>Test HTML</html>"
        mock_html_formatter.format_result.assert_called_once()

    @patch("core.logger.formatters._formatter_impl.JSON_AVAILABLE", True)
    @patch("core.logger.formatters._formatter_impl.JsonFormatter")
    def test_format_json_when_available(self, mock_json_formatter_class):
        """Test format method with JSON format when available."""
        # Mock the JSON formatter
        mock_json_formatter = Mock()
        mock_json_formatter.format_result.return_value = '{"status": "success"}'
        mock_json_formatter_class.return_value = mock_json_formatter

        # Create formatter with mocked JSON formatter
        formatter = OutputFormatter()
        formatter.json_formatter = mock_json_formatter

        result = MigrateResult()
        result.success = True

        output = formatter.format(result, "json", "test_schema", "test_db")
        assert output == '{"status": "success"}'
        mock_json_formatter.format_result.assert_called_once()

    def test_format_html_fallback_to_text(self):
        """Test format method falls back to text when HTML formatter not available."""
        # Ensure HTML formatter is None
        self.formatter.html_formatter = None

        result = MigrateResult()
        result.success = True
        result.target_schema = "test_schema"
        result.start_time = datetime.fromtimestamp(1000)
        result.end_time = datetime.fromtimestamp(1500)

        output = self.formatter.format(result, "html", "test_schema", "test_db")
        # Should fall back to text format
        assert "Database Migration Report" in output
        assert "Schema: test_schema" in output

    @patch("core.logger.formatters._formatter_impl.HtmlFormatter", None)
    def test_initializer_honors_patched_missing_html_formatter(self):
        """Test initializer does not re-import HTML formatter after an explicit None patch."""
        formatter = OutputFormatter()

        assert formatter.html_formatter is None

    def test_format_json_fallback_to_text(self):
        """Test format method falls back to text when JSON formatter not available."""
        # Ensure JSON formatter is None
        self.formatter.json_formatter = None

        result = MigrateResult()
        result.success = True
        result.target_schema = "test_schema"
        result.start_time = datetime.fromtimestamp(1000)
        result.end_time = datetime.fromtimestamp(1500)

        output = self.formatter.format(result, "json", "test_schema", "test_db")
        # Should fall back to text format
        assert "Database Migration Report" in output
        assert "Schema: test_schema" in output
