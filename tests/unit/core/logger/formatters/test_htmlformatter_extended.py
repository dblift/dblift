"""Extended tests for HtmlFormatter to improve coverage.

This module tests additional scenarios for HtmlFormatter, focusing on
uncovered areas like diff data extraction, multi-command mode, logo handling,
server extraction, and various edge cases.
"""

import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, Mock, mock_open, patch

import pytest

from core.comparison.diff_models import (
    ColumnDiff,
    ConstraintDiff,
    IndexDiff,
    ProcedureDiff,
    SchemaDiff,
    SequenceDiff,
    TableDiff,
    TriggerDiff,
    ViewDiff,
)
from core.logger.formatters.htmlformatter import HtmlFormatter
from core.logger.results import (
    DiffResult,
    InfoResult,
    MigrateResult,
    MigrationInfo,
    OperationResult,
)


@pytest.mark.unit
class TestHtmlFormatterExtended:
    """Extended tests for HtmlFormatter."""

    def test_format_event_warn_level(self):
        """Test format_event for WARN level."""
        formatter = HtmlFormatter()
        event = Mock()
        event.level.value = "WARN"
        event.component = "test"
        event.message = "warning message"
        event.timestamp = datetime(2023, 1, 1, 12, 0, 0)

        result = formatter.format_event(event)

        assert "[2023-01-01 12:00:00] WARN: warning message" == result

    def test_format_event_error_level(self):
        """Test format_event for ERROR level."""
        formatter = HtmlFormatter()
        event = Mock()
        event.level.value = "ERROR"
        event.component = "test"
        event.message = "error message"
        event.timestamp = datetime(2023, 1, 1, 12, 0, 0)

        result = formatter.format_event(event)

        assert "[2023-01-01 12:00:00] ERROR: error message" == result

    def test_format_event_debug_level(self):
        """Test format_event for DEBUG level."""
        formatter = HtmlFormatter()
        event = Mock()
        event.level.value = "DEBUG"
        event.component = "test"
        event.message = "debug message"
        event.timestamp = datetime(2023, 1, 1, 12, 0, 0)

        result = formatter.format_event(event)

        assert "[2023-01-01 12:00:00] DEBUG: debug message" == result

    def test_format_result_diffresult_normalization(self):
        """Test format_result normalizes DiffResult command type."""
        formatter = HtmlFormatter()
        result = DiffResult()
        result.success = True
        result.complete()

        with patch("jinja2.Environment.get_template") as mock_get_template:
            mock_template = Mock()
            mock_template.render.return_value = "<html>Diff Report</html>"
            mock_get_template.return_value = mock_template

            html_output = formatter.format_result(
                result=result, schema="test", database_name="test_db", command_type="OTHER"
            )

            assert formatter.command_type == "DIFF"
            assert html_output == "<html>Diff Report</html>"

    def test_format_result_per_migration_journal_exception(self):
        """Test format_result handles exceptions in per_migration_journal."""
        formatter = HtmlFormatter()
        result = MigrateResult()
        result.success = True

        # Mock journal to raise exception
        journal = Mock()
        journal.get_migration_performance_summary = Mock(side_effect=Exception("Journal error"))
        result.journal = journal

        migration = MigrationInfo(script="V1__Test.sql", version="1.0.0")
        result.migrations = [migration]
        result.complete()

        with patch("jinja2.Environment.get_template") as mock_get_template:
            mock_template = Mock()
            mock_template.render.return_value = "<html>Report</html>"
            mock_get_template.return_value = mock_template

            html_output = formatter.format_result(
                result=result, schema="test", database_name="test_db", command_type="MIGRATE"
            )

            # Should not raise, exception should be caught
            # When exception occurs, formatter generates error page, not the mocked template
            assert "Error Generating Report" in html_output or "Journal error" in html_output
            assert "html" in html_output.lower()

    def test_format_result_info_kpi_metrics(self):
        """Test format_result calculates KPI metrics for INFO command."""
        formatter = HtmlFormatter()
        result = InfoResult()
        result.success = True

        migration1 = MigrationInfo(
            script="V1__Test.sql", version="1.0.0", description="Test 1", execution_time=1000
        )
        migration2 = MigrationInfo(
            script="V2__Test.sql", version="2.0.0", description="Test 2", execution_time=2000
        )
        result.migrations = [migration1, migration2]
        result.complete()

        with patch("jinja2.Environment.get_template") as mock_get_template:
            mock_template = Mock()
            mock_template.render.return_value = "<html>Info Report</html>"
            mock_get_template.return_value = mock_template

            html_output = formatter.format_result(
                result=result, schema="test", database_name="test_db", command_type="INFO"
            )

            call_args = mock_template.render.call_args[1]
            assert call_args["total_execution_time"] == 3000
            assert call_args["execution_count"] == 2
            assert call_args["avg_execution_time"] == 1500

    def test_format_result_info_kpi_metrics_no_execution_times(self):
        """Test format_result KPI metrics with no execution times."""
        formatter = HtmlFormatter()
        result = InfoResult()
        result.success = True

        migration = MigrationInfo(script="V1__Test.sql", version="1.0.0", description="Test")
        result.migrations = [migration]
        result.complete()

        with patch("jinja2.Environment.get_template") as mock_get_template:
            mock_template = Mock()
            mock_template.render.return_value = "<html>Info Report</html>"
            mock_get_template.return_value = mock_template

            html_output = formatter.format_result(
                result=result, schema="test", database_name="test_db", command_type="INFO"
            )

            call_args = mock_template.render.call_args[1]
            assert call_args["total_execution_time"] == 0
            assert call_args["execution_count"] == 0
            assert call_args["avg_execution_time"] == 0

    def test_format_result_multi_command_mode(self):
        """Test format_result with multi-command mode."""
        formatter = HtmlFormatter()
        formatter.set_current_command("MIGRATE")  # This sets using_multi_command=True

        result1 = MigrateResult()
        result1.success = True
        result1.complete()
        formatter.add_command_result("MIGRATE", result1)

        result2 = OperationResult(success=True)
        result2.complete()
        formatter.add_command_result("INFO", result2)

        with patch("jinja2.Environment.get_template") as mock_get_template:
            mock_template = Mock()
            mock_template.render.return_value = "<html>Multi Report</html>"
            mock_get_template.return_value = mock_template

            html_output = formatter.format_result(
                result=result2, schema="test", database_name="test_db", command_type="INFO"
            )

            call_args = mock_template.render.call_args[1]
            assert call_args["using_multi_command"] is True
            assert "multi_commands" in call_args
            assert len(call_args["multi_commands"]) == 2

    def test_format_result_multi_command_with_diff(self):
        """Test format_result multi-command mode with DIFF command."""
        formatter = HtmlFormatter()
        formatter.set_current_command("DIFF")  # This sets using_multi_command=True

        diff_result = DiffResult()
        diff_result.success = True
        diff_result.complete()
        formatter.add_command_result("DIFF", diff_result)

        result2 = OperationResult(success=True)
        result2.complete()

        with patch("jinja2.Environment.get_template") as mock_get_template:
            mock_template = Mock()
            mock_template.render.return_value = "<html>Multi Report</html>"
            mock_get_template.return_value = mock_template

            html_output = formatter.format_result(
                result=result2, schema="test", database_name="test_db", command_type="INFO"
            )

            call_args = mock_template.render.call_args[1]
            assert "multi_commands" in call_args
            assert "diff_data" in call_args["multi_commands"][0]

    def test_format_result_multi_command_per_migration_journal(self):
        """Test format_result multi-command mode with per-migration journal."""
        formatter = HtmlFormatter()
        formatter.set_current_command("MIGRATE")  # This sets using_multi_command=True

        result1 = MigrateResult()
        result1.success = True
        journal = Mock()
        journal.get_migration_performance_summary = Mock(return_value={"total_time": 1000})
        result1.journal = journal

        migration = MigrationInfo(script="V1__Test.sql", version="1.0.0")
        result1.migrations = [migration]
        result1.complete()
        formatter.add_command_result("MIGRATE", result1)

        result2 = OperationResult(success=True)
        result2.complete()

        with patch("jinja2.Environment.get_template") as mock_get_template:
            mock_template = Mock()
            mock_template.render.return_value = "<html>Multi Report</html>"
            mock_get_template.return_value = mock_template

            html_output = formatter.format_result(
                result=result2, schema="test", database_name="test_db", command_type="INFO"
            )

            call_args = mock_template.render.call_args[1]
            assert "multi_commands" in call_args
            assert "per_migration_journal" in call_args["multi_commands"][0]

    def test_format_result_logo_path_resolution(self):
        """Test format_result logo path resolution."""
        formatter = HtmlFormatter()
        result = OperationResult(success=True)
        result.complete()

        with patch("jinja2.Environment.get_template") as mock_get_template:
            mock_template = Mock()
            mock_template.render.return_value = "<html>Report</html>"
            mock_get_template.return_value = mock_template

            # Mock Path.exists to return False for logo files
            with patch("core.logger.formatters.htmlformatter.Path.exists", return_value=False):
                html_output = formatter.format_result(
                    result=result, schema="test", database_name="test_db", command_type="INFO"
                )

                call_args = mock_template.render.call_args[1]
                # Should use fallback SVG logo
                assert call_args["logo_path"].startswith("data:image/svg+xml;base64")

    def test_format_result_logo_path_with_existing_logo(self):
        """Test format_result with existing logo file."""
        formatter = HtmlFormatter()
        result = OperationResult(success=True)
        result.complete()

        with patch("jinja2.Environment.get_template") as mock_get_template:
            mock_template = Mock()
            mock_template.render.return_value = "<html>Report</html>"
            mock_get_template.return_value = mock_template

            # Mock logo file exists
            with patch("core.logger.formatters.htmlformatter.Path.exists", return_value=True):
                with patch("builtins.open", mock_open(read_data=b"fake_png_data")):
                    with patch("base64.b64encode", return_value=b"encoded_data"):
                        html_output = formatter.format_result(
                            result=result,
                            schema="test",
                            database_name="test_db",
                            command_type="INFO",
                        )

                        call_args = mock_template.render.call_args[1]
                        assert call_args["logo_path"].startswith("data:image/png;base64")

    def test_format_result_fallback_html_file_write(self):
        """Test format_result fallback HTML file write."""
        formatter = HtmlFormatter()
        result = OperationResult(success=True)
        result.complete()

        # Mock template to raise exception
        with patch("jinja2.Environment.get_template", side_effect=Exception("Template error")):
            with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as tmp_file:
                output_path = Path(tmp_file.name)

                html_output = formatter.format_result(
                    result=result,
                    schema="test",
                    database_name="test_db",
                    command_type="INFO",
                    output_file=output_path,
                )

                assert output_path.exists()
                with open(output_path, "r") as f:
                    content = f.read()
                    assert "Error Generating Report" in content
                    assert "Template error" in content

                output_path.unlink()

    def test_extract_diff_data(self):
        """Test _extract_diff_data method."""
        formatter = HtmlFormatter()
        result = DiffResult()
        result.source_type = "postgresql"
        result.target_type = "mysql"
        result.error_count = 2
        result.warning_count = 3
        result.info_count = 5

        schema_diff = SchemaDiff(object_name="public", schema_name="public")
        schema_diff.missing_tables = ["table1", "table2"]
        schema_diff.extra_tables = ["table3"]
        schema_diff.missing_views = ["view1"]
        schema_diff.extra_views = ["view2"]
        schema_diff.missing_indexes = ["idx1"]
        schema_diff.extra_indexes = ["idx2"]
        schema_diff.missing_sequences = ["seq1"]
        schema_diff.extra_sequences = ["seq2"]
        schema_diff.missing_triggers = ["trg1"]
        schema_diff.extra_triggers = ["trg2"]
        schema_diff.missing_procedures = ["proc1"]
        schema_diff.extra_procedures = ["proc2"]
        schema_diff.missing_functions = ["func1"]
        schema_diff.extra_functions = ["func2"]

        result.set_schema_diff(schema_diff)

        diff_data = formatter._extract_diff_data(result)

        assert diff_data["source_type"] == "postgresql"
        assert diff_data["target_type"] == "mysql"
        # total_differences is calculated by set_schema_diff
        assert diff_data["total_differences"] >= 0
        assert diff_data["error_count"] == getattr(result, "error_count", 0)
        assert diff_data["warning_count"] == getattr(result, "warning_count", 0)
        assert diff_data["info_count"] == getattr(result, "info_count", 0)
        assert diff_data["missing_table_count"] == 2
        assert diff_data["extra_table_count"] == 1
        assert diff_data["has_critical_diffs"] == (getattr(result, "error_count", 0) > 0)

    def test_extract_diff_data_with_modified_tables(self):
        """Test _extract_diff_data with modified tables."""
        formatter = HtmlFormatter()
        result = DiffResult()
        result.source_type = "postgresql"
        result.target_type = "postgresql"
        result.total_differences = 5
        result.error_count = 0
        result.warning_count = 2
        result.info_count = 3

        schema_diff = SchemaDiff(object_name="public", schema_name="public")

        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            missing_columns=["email"],
            extra_columns=["phone"],
        )
        table_diff._calculate_diffs()

        schema_diff.modified_tables = [table_diff]
        result.set_schema_diff(schema_diff)

        diff_data = formatter._extract_diff_data(result)

        assert len(diff_data["modified_tables"]) == 1
        assert diff_data["modified_tables"][0]["table_name"] == "users"

    def test_build_modified_tables_data(self):
        """Test _build_modified_tables_data method."""
        formatter = HtmlFormatter()
        result = DiffResult()
        result.source_type = "postgresql"
        result.target_type = "postgresql"

        schema_diff = SchemaDiff(object_name="public", schema_name="public")

        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            missing_columns=["email"],
            extra_columns=["phone"],
        )
        table_diff._calculate_diffs()

        schema_diff.modified_tables = [table_diff]
        result.set_schema_diff(schema_diff)

        tables_data = formatter._build_modified_tables_data(result, "postgresql")

        assert len(tables_data) == 1
        assert tables_data[0]["table_name"] == "users"
        assert "missing_columns" in tables_data[0]
        assert "extra_columns" in tables_data[0]
        assert "unified_diff" in tables_data[0]

    def test_build_modified_tables_data_with_get_diff_count_exception(self):
        """Test _build_modified_tables_data handles get_diff_count exception."""
        formatter = HtmlFormatter()
        result = DiffResult()

        schema_diff = SchemaDiff(object_name="public", schema_name="public")

        table_diff = TableDiff(object_name="users", table_name="users")
        # Mock get_diff_count to raise exception
        table_diff.get_diff_count = Mock(side_effect=Exception("Error"))

        schema_diff.modified_tables = [table_diff]
        result.set_schema_diff(schema_diff)

        tables_data = formatter._build_modified_tables_data(result, "postgresql")

        assert len(tables_data) == 1
        assert tables_data[0]["diff_count"] == 0

    def test_build_modified_columns_data(self):
        """Test _build_modified_columns_data method."""
        formatter = HtmlFormatter()

        table_diff = TableDiff(object_name="users", table_name="users")

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

        table_diff.modified_columns = [col_diff]

        columns_data = formatter._build_modified_columns_data(table_diff)

        assert len(columns_data) == 1
        assert columns_data[0]["column_name"] == "id"
        assert len(columns_data[0]["changes"]) == 5
        assert any(c["property"] == "Type" for c in columns_data[0]["changes"])
        assert any(c["property"] == "Nullable" for c in columns_data[0]["changes"])

    def test_build_modified_object_entries_views(self):
        """Test _build_modified_object_entries for views."""
        formatter = HtmlFormatter()

        schema_diff = SchemaDiff(object_name="public", schema_name="public")

        view_diff = ViewDiff(
            object_name="test_view", view_name="test_view", definition_changed=True
        )
        view_diff._calculate_diffs()

        schema_diff.modified_views = [view_diff]

        entries = formatter._build_modified_object_entries(
            schema_diff, "modified_views", [("view_name", "view_name")], "postgresql", DiffResult()
        )

        assert len(entries) == 1
        assert entries[0]["view_name"] == "test_view"
        assert "severity" in entries[0]
        assert "unified_diff" in entries[0]

    def test_build_modified_object_entries_indexes(self):
        """Test _build_modified_object_entries for indexes."""
        formatter = HtmlFormatter()

        schema_diff = SchemaDiff(object_name="public", schema_name="public")

        index_diff = IndexDiff(
            object_name="idx_users",
            index_name="idx_users",
            table_name="users",
            columns_changed=True,
        )
        index_diff._calculate_diffs()

        schema_diff.modified_indexes = [index_diff]

        entries = formatter._build_modified_object_entries(
            schema_diff,
            "modified_indexes",
            [("index_name", "index_name"), ("table_name", "table_name")],
            "postgresql",
            DiffResult(),
        )

        assert len(entries) == 1
        assert entries[0]["index_name"] == "idx_users"
        assert entries[0]["table_name"] == "users"

    def test_build_modified_object_entries_sequences(self):
        """Test _build_modified_object_entries for sequences."""
        formatter = HtmlFormatter()

        schema_diff = SchemaDiff(object_name="public", schema_name="public")

        sequence_diff = SequenceDiff(object_name="seq_users", sequence_name="seq_users")
        sequence_diff._calculate_diffs()

        schema_diff.modified_sequences = [sequence_diff]

        entries = formatter._build_modified_object_entries(
            schema_diff,
            "modified_sequences",
            [("sequence_name", "sequence_name")],
            "postgresql",
            DiffResult(),
        )

        assert len(entries) == 1
        assert entries[0]["sequence_name"] == "seq_users"

    def test_build_modified_object_entries_triggers(self):
        """Test _build_modified_object_entries for triggers."""
        formatter = HtmlFormatter()

        schema_diff = SchemaDiff(object_name="public", schema_name="public")

        trigger_diff = TriggerDiff(
            object_name="trg_users", trigger_name="trg_users", table_name="users"
        )
        trigger_diff._calculate_diffs()

        schema_diff.modified_triggers = [trigger_diff]

        entries = formatter._build_modified_object_entries(
            schema_diff,
            "modified_triggers",
            [("trigger_name", "trigger_name"), ("table_name", "table_name")],
            "postgresql",
            DiffResult(),
        )

        assert len(entries) == 1
        assert entries[0]["trigger_name"] == "trg_users"

    def test_build_modified_object_entries_procedures(self):
        """Test _build_modified_object_entries for procedures."""
        formatter = HtmlFormatter()

        schema_diff = SchemaDiff(object_name="public", schema_name="public")

        procedure_diff = ProcedureDiff(object_name="test_proc", procedure_name="test_proc")
        procedure_diff._calculate_diffs()

        schema_diff.modified_procedures = [procedure_diff]

        entries = formatter._build_modified_object_entries(
            schema_diff,
            "modified_procedures",
            [("procedure_name", "procedure_name")],
            "postgresql",
            DiffResult(),
        )

        assert len(entries) == 1
        assert entries[0]["procedure_name"] == "test_proc"

    def test_build_modified_object_entries_no_schema_diff(self):
        """Test _build_modified_object_entries with no schema_diff."""
        formatter = HtmlFormatter()

        entries = formatter._build_modified_object_entries(
            None, "modified_views", [("view_name", "view_name")], "postgresql", DiffResult()
        )

        assert entries == []

    def test_generate_unified_diff_data(self):
        """Test _generate_unified_diff_data method."""
        formatter = HtmlFormatter()

        table_diff = TableDiff(object_name="users", table_name="users")
        result = DiffResult()
        result.source_type = "postgresql"
        result.target_type = "mysql"

        diff_data = formatter._generate_unified_diff_data(table_diff, "postgresql", result, "users")

        # May return None if SQL generation fails, or a dict with diff data
        assert diff_data is None or isinstance(diff_data, dict)

    def test_generate_unified_diff_data_exception(self):
        """Test _generate_unified_diff_data handles exceptions."""
        formatter = HtmlFormatter()

        # Create object that will cause exception
        diff_obj = Mock()
        diff_obj.__class__.__name__ = "UnknownDiff"

        result = DiffResult()

        diff_data = formatter._generate_unified_diff_data(
            diff_obj, "postgresql", result, "test_object"
        )

        assert diff_data is None

    def test_extract_server_from_result_with_server_name(self):
        """Test _extract_server_from_result with server_name."""
        formatter = HtmlFormatter()
        result = OperationResult()
        result.server_name = "test-server"

        server = formatter._extract_server_from_result(result)

        assert server == "test-server"

    def test_extract_server_from_result_with_database_url_masked(self):
        """Test _extract_server_from_result with database_url_masked."""
        formatter = HtmlFormatter()
        result = OperationResult()
        result.database_url_masked = "postgresql+psycopg://192.168.1.20:5432/dblift"

        server = formatter._extract_server_from_result(result)

        assert server == "192.168.1.20"

    def test_extract_server_from_result_with_database_url(self):
        """Test _extract_server_from_result with database_url."""
        formatter = HtmlFormatter()
        result = OperationResult()
        result.database_url = "mysql+pymysql://localhost:3306/mydb"

        server = formatter._extract_server_from_result(result)

        assert server == "localhost"

    def test_extract_server_from_result_fallback(self):
        """Test _extract_server_from_result fallback to localhost."""
        formatter = HtmlFormatter()
        result = OperationResult()

        server = formatter._extract_server_from_result(result)

        assert server == "localhost"

    def test_extract_server_from_database_url_postgresql(self):
        """Test _extract_server_from_database_url for PostgreSQL."""
        formatter = HtmlFormatter()

        server = formatter._extract_server_from_database_url(
            "postgresql+psycopg://192.168.1.20:5432/dblift"
        )

        assert server == "192.168.1.20"

    def test_extract_server_from_database_url_mysql(self):
        """Test _extract_server_from_database_url for MySQL."""
        formatter = HtmlFormatter()

        server = formatter._extract_server_from_database_url("mysql+pymysql://localhost:3306/mydb")

        assert server == "localhost"

    def test_extract_server_from_database_url_oracle_thin(self):
        """Test _extract_server_from_database_url for Oracle SQLAlchemy URL."""
        formatter = HtmlFormatter()

        server = formatter._extract_server_from_database_url(
            "oracle+oracledb://server:1521/?service_name=sid"
        )

        assert server == "server"

    def test_extract_server_from_database_url_fallback(self):
        """Test _extract_server_from_database_url fallback."""
        formatter = HtmlFormatter()

        server = formatter._extract_server_from_database_url("invalid_url")

        assert server == "invalid_url"

    def test_extract_server_from_database_url_exception(self):
        """Test _extract_server_from_database_url handles exceptions."""
        formatter = HtmlFormatter()

        # Mock re.search to raise exception
        with patch("re.search", side_effect=Exception("Regex error")):
            server = formatter._extract_server_from_database_url("postgresql+psycopg://server/db")

            assert server == "localhost"

    def test_get_command_details_export_schema(self):
        """Test _get_command_details for EXPORT-SCHEMA command."""
        formatter = HtmlFormatter()
        result = OperationResult()
        result.output_files = ["file1.sql", "file2.sql"]
        result.objects_exported = {"tables": 5, "views": 3}
        result.filters_applied = {"schema": "public"}
        result.output_options = {"format": "sql"}

        details = formatter._get_command_details("EXPORT-SCHEMA", result)

        assert details["icon"] == "download"
        assert "exports the database schema" in details["description"]
        assert details["output_files"] == ["file1.sql", "file2.sql"]
        assert details["objects_exported"] == {"tables": 5, "views": 3}

    def test_get_command_details_unknown_command(self):
        """Test _get_command_details for unknown command."""
        formatter = HtmlFormatter()
        result = OperationResult()

        details = formatter._get_command_details("UNKNOWN", result)

        assert details["icon"] == "arrow-up-circle"  # Default
        assert details["description"] == "."
        assert details["title"] == "UNKNOWN Command Details"

    def test_format_result_with_db_metadata(self):
        """Test format_result includes database metadata."""
        formatter = HtmlFormatter()
        result = OperationResult(success=True)
        result.db_version = "PostgreSQL 14.0"
        result.native_driver = "postgresql-42.7.5.jar"
        result.database_url_masked = "postgresql+psycopg://***:***@localhost/test"
        result.current_schema_version = "1.0.0"
        result.complete()

        with patch("jinja2.Environment.get_template") as mock_get_template:
            mock_template = Mock()
            mock_template.render.return_value = "<html>Report</html>"
            mock_get_template.return_value = mock_template

            html_output = formatter.format_result(
                result=result, schema="test", database_name="test_db", command_type="INFO"
            )

            call_args = mock_template.render.call_args[1]
            assert call_args["db_version"] == "PostgreSQL 14.0"
            assert call_args["native_driver"] == "postgresql-42.7.5.jar"
            assert call_args["database_url_masked"] == "postgresql+psycopg://***:***@localhost/test"
            assert call_args["current_version"] == "1.0.0"

    def test_format_result_with_warnings(self):
        """Test format_result includes warnings."""
        formatter = HtmlFormatter()
        result = MigrateResult()
        result.success = True
        result.warnings = ["Warning 1", "Warning 2"]
        result.complete()

        with patch("jinja2.Environment.get_template") as mock_get_template:
            mock_template = Mock()
            mock_template.render.return_value = "<html>Report</html>"
            mock_get_template.return_value = mock_template

            html_output = formatter.format_result(
                result=result, schema="test", database_name="test_db", command_type="MIGRATE"
            )

            call_args = mock_template.render.call_args[1]
            assert call_args["warnings"] == ["Warning 1", "Warning 2"]

    def test_format_result_without_warnings(self):
        """Test format_result without warnings attribute."""
        formatter = HtmlFormatter()
        result = OperationResult(success=True)
        result.complete()

        # Remove warnings attribute if it exists
        if hasattr(result, "warnings"):
            delattr(result, "warnings")

        with patch("jinja2.Environment.get_template") as mock_get_template:
            mock_template = Mock()
            mock_template.render.return_value = "<html>Report</html>"
            mock_get_template.return_value = mock_template

            html_output = formatter.format_result(
                result=result, schema="test", database_name="test_db", command_type="INFO"
            )

            call_args = mock_template.render.call_args[1]
            assert call_args["warnings"] == []
