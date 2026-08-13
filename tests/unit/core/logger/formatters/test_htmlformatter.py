"""Tests for HTML formatter."""

import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from core.logger.formatters.htmlformatter import HtmlFormatter
from core.logger.results import (
    BaselineResult,
    CleanResult,
    InfoResult,
    MigrateResult,
    MigrationInfo,
    MigrationQueryResultInfo,
    MigrationSqlInfo,
    OperationResult,
    RepairResult,
    ValidateResult,
)


@pytest.mark.unit
class TestHtmlFormatter:
    """Test HTML formatter functionality."""

    def test_formatter_initialization_default(self):
        """Test formatter initialization with default template directory."""
        formatter = HtmlFormatter()

        assert formatter.template_dir is not None
        assert formatter.env is not None
        assert formatter.log_entries == []
        assert formatter.command_type == "MIGRATE"
        assert formatter.command_results == []
        assert formatter.current_command is None
        assert formatter.using_multi_command is False

    def test_formatter_initialization_custom_template_dir(self):
        """Test formatter initialization with custom template directory."""
        custom_dir = Path("/custom/templates")
        formatter = HtmlFormatter(template_dir=custom_dir)

        assert formatter.template_dir == custom_dir

    def test_format_event(self):
        """Test formatting of individual log events."""
        formatter = HtmlFormatter()

        # Create a mock log event
        mock_event = Mock()
        mock_event.level.value = "INFO"
        mock_event.component = "test_component"
        mock_event.message = "Test message"
        mock_event.timestamp = datetime(2023, 1, 1, 12, 0, 0)

        result = formatter.format_event(mock_event)

        # Should return formatted string (INFO prefix removed for consistency)
        assert "[2023-01-01 12:00:00] Test message" == result

    def test_format_result_includes_sql_only_when_show_sql_enabled(self):
        formatter = HtmlFormatter()
        result = MigrateResult()
        result.show_sql = True
        result.add_sql_migration(
            MigrationSqlInfo("V1__init.sql", version="1", statements=["CREATE TABLE users"])
        )

        html = formatter.format_result(result, "public", "test", "MIGRATE")

        assert "CREATE TABLE users" in html

    def test_format_result_hides_sql_when_show_sql_disabled(self):
        formatter = HtmlFormatter()
        result = MigrateResult()
        result.show_sql = False
        result.add_sql_migration(
            MigrationSqlInfo("V1__init.sql", version="1", statements=["CREATE TABLE users"])
        )

        html = formatter.format_result(result, "public", "test", "MIGRATE")

        assert "CREATE TABLE users" not in html

    def test_format_result_includes_query_results_only_when_enabled(self):
        formatter = HtmlFormatter()
        result = MigrateResult()
        result.show_query_results = True
        info = MigrationQueryResultInfo("V1__init.sql", version="1", description="init")
        info.add_result("SELECT * FROM users", ["id", "name"], [[1, "alice"], [2, "bob"]])
        result.query_results.append(info)

        html = formatter.format_result(result, "public", "test", "MIGRATE")

        assert "Query result" in html
        assert "SQL statements" not in html
        assert "alice" in html
        assert "bob" in html
        assert 'class="t"' in html
        assert "SELECT * FROM users" not in html

    def test_format_result_includes_query_results_for_clean_command(self):
        """CLEAN's --show-query-results panel renders (Bug 2 regression guard)."""
        formatter = HtmlFormatter()
        result = CleanResult()
        result.show_query_results = True
        info = MigrationQueryResultInfo("beforeClean/check.sql", version=None, description="check")
        info.add_result("SELECT * FROM users", ["id", "name"], [[1, "alice"], [2, "bob"]])
        result.query_results.append(info)

        html = formatter.format_result(result, "public", "test", "CLEAN")

        assert "Query results" in html
        assert "SELECT * FROM users" in html
        assert "alice" in html
        assert "bob" in html
        assert 'class="t"' in html

    def test_format_result_hides_query_results_when_disabled(self):
        formatter = HtmlFormatter()
        result = MigrateResult()
        result.show_query_results = False
        info = MigrationQueryResultInfo("V1__init.sql", version="1", description="init")
        info.add_result("SELECT * FROM users", ["id"], [[1]])
        result.query_results.append(info)

        html = formatter.format_result(result, "public", "test", "MIGRATE")

        assert "Query results" not in html

    def test_format_result_query_results_independent_of_show_sql(self):
        """show_sql and show_query_results gate their own, independent panels."""
        formatter = HtmlFormatter()
        result = MigrateResult()
        result.show_sql = True
        result.show_query_results = False
        result.add_sql_migration(
            MigrationSqlInfo("V1__init.sql", version="1", statements=["CREATE TABLE users"])
        )
        info = MigrationQueryResultInfo("V1__init.sql", version="1")
        info.add_result("SELECT 1", ["one"], [[1]])
        result.query_results.append(info)

        html = formatter.format_result(result, "public", "test", "MIGRATE")

        assert "CREATE TABLE users" in html
        assert "Query results" not in html

    def test_format_result_preserves_performance_panel_without_show_sql(self):
        formatter = HtmlFormatter()
        result = MigrateResult()
        result.show_sql = False
        result.journal = Mock()
        result.journal.get_migration_performance_summary.return_value = {
            "version": "1",
            "description": "init",
            "total_execution_time": 7,
            "min_statement_time": 7,
            "max_statement_time": 7,
            "statements": [
                {
                    "statement": "CREATE TABLE users (id INTEGER)",
                    "execution_time": 7,
                    "success": True,
                }
            ],
        }
        result.journal.get_performance_stats_by_object_type.return_value = {}
        result.add_migration(MigrationInfo(script="V1__init.sql", version="1"))

        html = formatter.format_result(result, "public", "test", "MIGRATE")

        assert "Per-migration execution" in html
        assert '<div class="lbl">Statements</div>\n    <div class="num">1</div>' in html
        assert '<div class="lbl">Total SQL Time</div>\n    <div class="num warn">7<span' in html
        assert "CREATE TABLE users" not in html

    def test_format_result_does_not_duplicate_sql_when_show_sql_enabled(self):
        formatter = HtmlFormatter()
        result = MigrateResult()
        result.show_sql = True
        result.add_sql_migration(
            MigrationSqlInfo(
                "V1__init.sql",
                version="1",
                statements=["CREATE TABLE users (id INTEGER)"],
            )
        )
        result.journal = Mock()
        result.journal.get_migration_performance_summary.return_value = {
            "version": "1",
            "description": "init",
            "total_execution_time": 7,
            "min_statement_time": 7,
            "max_statement_time": 7,
            "statements": [
                {
                    "statement": "CREATE TABLE users (id INTEGER)",
                    "execution_time": 7,
                    "success": True,
                }
            ],
        }
        result.journal.get_performance_stats_by_object_type.return_value = {}
        result.add_migration(MigrationInfo(script="V1__init.sql", version="1"))

        html = formatter.format_result(result, "public", "test", "MIGRATE")

        assert "SQL statements" not in html
        assert html.count("<pre>CREATE TABLE users (id INTEGER)</pre>") == 1

    def test_format_header(self):
        """Test formatting of HTML header."""
        formatter = HtmlFormatter()

        result = formatter.format_header(schema="test_schema", database_name="test_db")

        assert "<!DOCTYPE html>" in result
        assert "<html>" in result
        assert "<title>Dblift Migration Log (Temporary)</title>" in result
        assert "Dblift Migration Log" in result
        assert "temporary file" in result

    def test_format_footer(self):
        """Test formatting of HTML footer."""
        formatter = HtmlFormatter()

        result = formatter.format_footer()

        assert "</pre>" in result
        assert "</body>" in result
        assert "</html>" in result

    def test_add_log_entry(self):
        """Test adding log entries."""
        formatter = HtmlFormatter()

        with patch("core.logger.formatters.htmlformatter.datetime") as mock_datetime:
            mock_datetime.now.return_value.strftime.return_value = "2023-01-01 12:00:00"

            formatter.add_log_entry("ERROR", "migration", "Test error message")

            assert len(formatter.log_entries) == 1
            entry = formatter.log_entries[0]
            assert entry["timestamp"] == "2023-01-01 12:00:00"
            assert entry["level"] == "ERROR"
            assert entry["component"] == "migration"
            assert entry["message"] == "Test error message"

    def test_set_current_command(self):
        """Test setting current command."""
        formatter = HtmlFormatter()

        formatter.set_current_command("CLEAN")

        assert formatter.current_command == "CLEAN"
        assert formatter.using_multi_command is True

    def test_add_command_result(self):
        """Test adding command results."""
        formatter = HtmlFormatter()

        # Create mock result
        mock_result = Mock(spec=OperationResult)
        mock_result.success = True
        mock_result.error_message = None
        mock_result.execution_time.return_value = 1500

        with patch("core.logger.formatters.htmlformatter.datetime") as mock_datetime:
            mock_datetime.now.return_value.strftime.return_value = "2023-01-01 12:00:00"

            formatter.add_command_result("MIGRATE", mock_result)

            assert len(formatter.command_results) == 1
            command_result = formatter.command_results[0]
            assert command_result["command_type"] == "MIGRATE"
            assert command_result["result"] == mock_result
            assert command_result["success"] is True
            assert command_result["error_message"] is None
            assert command_result["execution_time"] == 1500
            assert command_result["timestamp"] == "2023-01-01 12:00:00"

    @patch("jinja2.Environment.get_template")
    def test_format_result_success(self, mock_get_template):
        """Test successful format_result with template rendering."""
        formatter = HtmlFormatter()

        # Mock template
        mock_template = Mock()
        mock_template.render.return_value = "<html>Test Report</html>"
        mock_get_template.return_value = mock_template

        # Create test result
        result = MigrateResult()
        result.success = True
        result.complete()

        html_output = formatter.format_result(
            result=result, schema="test_schema", database_name="test_db", command_type="MIGRATE"
        )

        assert html_output == "<html>Test Report</html>"
        assert formatter.command_type == "MIGRATE"
        mock_get_template.assert_called_once_with("report.html")
        mock_template.render.assert_called_once()

    @patch("jinja2.Environment.get_template")
    def test_format_result_with_output_file(self, mock_get_template):
        """Test format_result with output file."""
        formatter = HtmlFormatter()

        # Mock template
        mock_template = Mock()
        mock_template.render.return_value = "<html>Test Report</html>"
        mock_get_template.return_value = mock_template

        result = MigrateResult()
        result.success = True
        result.complete()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as tmp_file:
            output_path = Path(tmp_file.name)

            html_output = formatter.format_result(
                result=result,
                schema="test_schema",
                database_name="test_db",
                command_type="MIGRATE",
                output_file=output_path,
            )

            # Check file was written
            assert output_path.exists()
            with open(output_path, "r") as f:
                file_content = f.read()
            assert file_content == "<html>Test Report</html>"

            # Cleanup
            output_path.unlink()

    @patch("jinja2.Environment.get_template")
    def test_format_result_template_error_fallback(self, mock_get_template):
        """Test format_result fallback when template rendering fails."""
        formatter = HtmlFormatter()

        # Mock template to raise an exception
        mock_get_template.side_effect = Exception("Template not found")

        result = MigrateResult()
        result.success = False
        result.set_error("Migration failed")

        html_output = formatter.format_result(
            result=result, schema="test_schema", database_name="test_db", command_type="MIGRATE"
        )

        assert "Error Generating Report" in html_output
        assert "Error rendering HTML template: Template not found" in html_output
        assert "Command: MIGRATE" in html_output
        assert "Schema: test_schema" in html_output
        assert "Database: test_db" in html_output

    @patch("jinja2.Environment.get_template")
    def test_format_result_with_migrations(self, mock_get_template):
        """Test format_result with migration data."""
        formatter = HtmlFormatter()

        # Mock template
        mock_template = Mock()
        mock_template.render.return_value = "<html>Migration Report</html>"
        mock_get_template.return_value = mock_template

        # Create result with migrations
        result = MigrateResult()
        migration1 = MigrationInfo(
            script="V1__Initial.sql",
            version="1.0.0",
            description="Initial migration",
            status="SUCCESS",
        )
        migration2 = MigrationInfo(
            script="V2__Add_tables.sql", version="2.0.0", description="Add tables", status="PENDING"
        )
        result.add_migration(migration1)
        result.add_migration(migration2)
        result.complete()

        html_output = formatter.format_result(
            result=result, schema="test_schema", database_name="test_db", command_type="MIGRATE"
        )

        # Verify template was called with migrations
        call_args = mock_template.render.call_args[1]
        assert "migration_data" in call_args
        assert len(call_args["migration_data"]) == 2

    def test_get_command_details_migrate(self):
        """Test get_command_details for MIGRATE command."""
        formatter = HtmlFormatter()
        result = MigrateResult()

        details = formatter._get_command_details("MIGRATE", result)

        assert details["icon"] == "arrow-up-circle"
        assert "executes all pending migrations" in details["description"]
        assert details["title"] == "MIGRATE Command Details"

    def test_get_command_details_clean(self):
        """Test get_command_details for CLEAN command."""
        formatter = HtmlFormatter()
        result = CleanResult()
        result.add_table_dropped("table1")
        result.add_table_dropped("table2")
        result.add_schema_dropped("schema1")

        details = formatter._get_command_details("CLEAN", result)

        assert details["icon"] == "trash"
        assert "cleans (drops) all objects" in details["description"]
        assert details["tables_dropped"] == {"table1", "table2"}
        assert details["schemas_dropped"] == {"schema1"}
        assert "objects_by_type" in details
        assert set(details["objects_by_type"]["table"]) == {"table1", "table2"}

    def test_get_command_details_info(self):
        """Test get_command_details for INFO command."""
        formatter = HtmlFormatter()
        result = InfoResult()

        details = formatter._get_command_details("INFO", result)

        assert details["icon"] == "info-circle"
        assert "shows information about all migrations" in details["description"]

    def test_get_command_details_validate(self):
        """Test get_command_details for VALIDATE command."""
        formatter = HtmlFormatter()
        result = ValidateResult()

        details = formatter._get_command_details("VALIDATE", result)

        assert details["icon"] == "check-circle"
        assert "validates all migrations" in details["description"]

    def test_get_command_details_undo(self):
        """Test get_command_details for UNDO command."""
        formatter = HtmlFormatter()
        result = OperationResult()

        details = formatter._get_command_details("UNDO", result)

        assert details["icon"] == "arrow-counterclockwise"
        assert "undoes migrations to a target version" in details["description"]

    def test_get_command_details_baseline(self):
        """Test get_command_details for BASELINE command."""
        formatter = HtmlFormatter()
        result = BaselineResult()

        details = formatter._get_command_details("BASELINE", result)

        assert details["icon"] == "flag"
        assert "baselined the schema" in details["description"]

    def test_get_command_details_repair(self):
        """Test get_command_details for REPAIR command."""
        formatter = HtmlFormatter()
        result = RepairResult()

        details = formatter._get_command_details("REPAIR", result)

        assert details["icon"] == "wrench"
        assert "repairs the schema history table" in details["description"]

    def test_calculate_migration_stats_with_dict_migrations(self):
        """Test calculate_migration_stats with dictionary migrations."""
        formatter = HtmlFormatter()

        migrations = [
            {"status": "SUCCESS"},
            {"status": "PENDING"},
            {"status": "FAILED"},
            {"status": "SUCCESS"},
            {"status": "OUTDATED"},
            {"status": "UNDONE"},
        ]

        stats = formatter._calculate_migration_stats(migrations)

        assert stats["total"] == 6
        assert stats["success"] == 2
        assert stats["pending"] == 1
        assert stats["failed"] == 1
        assert stats["outdated"] == 1
        assert stats["undone"] == 1

    def test_calculate_migration_stats_with_object_migrations(self):
        """Test calculate_migration_stats with object migrations."""
        formatter = HtmlFormatter()

        # Create mock migration objects with proper status values
        migrations = []
        for status in ["SUCCESS", "PENDING", "FAILED"]:
            migration = MigrationInfo(script="test.sql", status=status)
            migrations.append(migration)

        stats = formatter._calculate_migration_stats(migrations)

        assert stats["total"] == 3
        assert stats["success"] == 1
        assert stats["pending"] == 1
        assert stats["failed"] == 1
        assert stats["outdated"] == 0
        assert stats["undone"] == 0

    def test_calculate_migration_stats_with_dict_attribute_migrations(self):
        """Test calculate_migration_stats with __dict__ attribute migrations."""
        formatter = HtmlFormatter()

        # Create simple objects using a basic class instead of Mock
        class SimpleMigration:
            def __init__(self, status):
                self.__dict__ = {"status": status}

        migration1 = SimpleMigration("SUCCESS")
        migration2 = SimpleMigration("PENDING")

        migrations = [migration1, migration2]

        stats = formatter._calculate_migration_stats(migrations)

        assert stats["total"] == 2
        assert stats["success"] == 1
        assert stats["pending"] == 1

    def test_calculate_migration_stats_with_unknown_status(self):
        """Test calculate_migration_stats with unknown status."""
        formatter = HtmlFormatter()

        # Create migration with no status information
        migration1 = Mock(spec=[])  # No attributes
        migrations = [migration1]

        stats = formatter._calculate_migration_stats(migrations)

        assert stats["total"] == 1
        assert stats["success"] == 0
        assert stats["pending"] == 0
        assert stats["failed"] == 0

    def test_calculate_migration_stats_baseline_vs_below_baseline(self):
        """BASELINE counts as success; BELOW BASELINE must not match BASELINE substring."""
        formatter = HtmlFormatter()
        migrations = [
            {"status": "BASELINE"},
            {"status": "Below baseline"},
            {"status": "SUCCESS"},
        ]
        stats = formatter._calculate_migration_stats(migrations)
        assert stats["total"] == 3
        assert stats["success"] == 2
        assert stats["pending"] == 0

    def test_get_output_filename(self):
        """Test get_output_filename generation."""
        formatter = HtmlFormatter()

        with patch("core.logger.formatters.htmlformatter.datetime") as mock_datetime:
            mock_datetime.now.return_value.strftime.return_value = "20230101_120000"

            filename = formatter.get_output_filename("test_schema", "test_db", "migrate")

            assert filename == "Dblift_test_schema_test_db_migrate_20230101_120000.html"

    def test_add_test_markers(self):
        """Test adding test markers to HTML output."""
        formatter = HtmlFormatter()

        html_input = "<html><body><h1>Test</h1></body></html>"

        result = formatter._add_test_markers(html_input)

        assert "<!-- Test markers -->" in result
        assert "migrate-command-details" in result
        assert "MIGRATE Command Details" in result
        assert "migration-information" in result
        assert "version-marker" in result
        assert "Current Version: 1.0.0" in result
        assert "baseline-description" in result
        assert "bi bi-arrow-up-circle" in result

    def test_add_test_markers_no_body_tag(self):
        """Test adding test markers when no body tag exists."""
        formatter = HtmlFormatter()

        html_input = "<html><h1>Test</h1></html>"

        result = formatter._add_test_markers(html_input)

        assert "<!-- Test markers -->" in result
        assert result.endswith(
            '<!-- Test markers -->\n            <div style="display:none;">\n                <div id="migrate-command-details">MIGRATE Command Details</div>\n                <div id="migration-information">Migration Information</div>\n                <div id="version-marker">1.0.0</div>\n                <div id="current-version">Current Version: 1.0.0</div>\n                <div id="baseline-description">Initial baseline</div>\n                <div id="icons">\n                    <i class="bi bi-arrow-up-circle"></i>\n                    <i class="bi bi-database"></i>\n                    <i class="bi bi-check-circle"></i>\n                </div>\n            </div>\n            '
        )

    @patch("jinja2.Environment.get_template")
    def test_format_result_with_journal_data(self, mock_get_template):
        """Test format_result with journal performance data."""
        formatter = HtmlFormatter()

        # Mock template
        mock_template = Mock()
        mock_template.render.return_value = "<html>Report with Journal</html>"
        mock_get_template.return_value = mock_template

        # Create result with journal
        result = MigrateResult()
        result.journal = Mock()
        result.journal.get_migration_performance_summary.return_value = {"total_time": 1500}
        result.journal.get_performance_stats_by_object_type.return_value = {"tables": 5}

        # Add migration with script_name
        migration = MigrationInfo(script="V1__Initial.sql", version="1.0.0")
        migration.script_name = "V1__Initial.sql"
        result.add_migration(migration)
        result.complete()

        html_output = formatter.format_result(
            result=result, schema="test_schema", database_name="test_db", command_type="MIGRATE"
        )

        # Verify journal methods were called
        # get_migration_performance_summary is called twice: once for journal_data and once for per_migration_journal
        assert result.journal.get_migration_performance_summary.call_count == 2
        result.journal.get_migration_performance_summary.assert_any_call("V1__Initial.sql")
        result.journal.get_performance_stats_by_object_type.assert_called_once_with(
            "V1__Initial.sql"
        )

        # Verify template was called with journal data
        call_args = mock_template.render.call_args[1]
        assert call_args["journal_data"] == {"total_time": 1500}
        assert call_args["object_stats"] == {"tables": 5}
        # Verify per_migration_journal is populated
        assert "per_migration_journal" in call_args
        assert "V1__Initial.sql" in call_args["per_migration_journal"]
        assert call_args["per_migration_journal"]["V1__Initial.sql"] == {"total_time": 1500}

    @patch("core.logger.formatters.htmlformatter.resolve_dblift_package_version", return_value=None)
    def test_report_metadata_omits_empty_version(self, _mock_version):
        formatter = HtmlFormatter()
        meta = formatter._report_metadata(MigrateResult(), "2026-08-12 19:17:29")

        assert meta["dblift_version"] is None

    def test_report_db_user_from_cli_and_migration(self):
        formatter = HtmlFormatter()
        from_cli = MigrateResult()
        from_cli.cli_options = {"username": "cli_user"}
        assert formatter._report_db_user(from_cli) == "cli_user"

        from_mig = MigrateResult()
        from_mig.add_migration(MigrationInfo(script="V1__init.sql", installed_by="hist_user"))
        assert formatter._report_db_user(from_mig) == "hist_user"
        assert formatter._report_db_user(MigrateResult()) is None

    def test_merge_sql_into_empty_journal_summary(self):
        formatter = HtmlFormatter()
        result = MigrateResult()
        result.show_sql = True
        result.add_sql_migration(
            MigrationSqlInfo(
                "V1__init.sql", version="1", description="init", statements=["SELECT 1"]
            )
        )
        journal = {"V1__init.sql": {"version": None, "description": "", "statements": []}}
        formatter._merge_sql_visibility(journal, result)
        assert journal["V1__init.sql"]["statements"][0]["statement"] == "SELECT 1"
        assert journal["V1__init.sql"]["version"] == "1"

    def test_attach_query_result_sets_matches_and_skips(self):
        formatter = HtmlFormatter()
        result = MigrateResult()
        result.show_query_results = True
        info = MigrationQueryResultInfo("V1__init.sql", version="1")
        info.add_result("SELECT 1", ["one"], [[1]])
        result.query_results.append(info)
        journal = {
            "V1__init.sql": {
                "statements": [
                    {"statement": "CREATE TABLE t (id int)"},
                    "not-a-dict",
                ]
            },
            "other.sql": "not-a-dict",
        }
        formatter._attach_query_result_sets(journal, result)
        assert journal["V1__init.sql"]["statements"][0]["result_set"] is None
        extra = journal["V1__init.sql"]["statements"][-1]
        assert extra["statement"] == "SELECT 1"
        assert extra["result_set"]["rows"] == [[1]]

    def test_multiple_log_entries(self):
        """Test handling multiple log entries."""
        formatter = HtmlFormatter()

        # Add multiple log entries
        formatter.add_log_entry("INFO", "migration", "Starting migration")
        formatter.add_log_entry("DEBUG", "database", "Connecting to database")
        formatter.add_log_entry("ERROR", "migration", "Migration failed")

        assert len(formatter.log_entries) == 3
        assert formatter.log_entries[0]["level"] == "INFO"
        assert formatter.log_entries[1]["level"] == "DEBUG"
        assert formatter.log_entries[2]["level"] == "ERROR"

    def test_format_result_edge_cases(self):
        """Test format_result with edge cases and error scenarios."""
        formatter = HtmlFormatter()

        # Test with minimal result
        result = OperationResult(success=False, error_message="Test error")
        result.complete()

        with patch("jinja2.Environment.get_template") as mock_get_template:
            mock_template = Mock()
            mock_template.render.return_value = "<html>Error Report</html>"
            mock_get_template.return_value = mock_template

            html_output = formatter.format_result(
                result=result, schema="", database_name="", command_type="UNKNOWN"
            )

            assert html_output == "<html>Error Report</html>"

            # Verify template context
            call_args = mock_template.render.call_args[1]
            assert call_args["operation_success"] is False
            assert call_args["error_message"] == "Test error"
            assert call_args["command_type"] == "UNKNOWN"
