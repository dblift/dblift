"""Unit tests for OutputFormatterFactory."""

from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from dblift.core.logger.formatters.factory import OutputFormatterFactory
from dblift.core.logger.formatters.formatter import OutputFormatter
from dblift.core.logger.results import MigrateResult, OperationResult

pytestmark = [pytest.mark.unit]


class TestOutputFormatterFactory:
    """Test OutputFormatterFactory functionality."""

    def setup_method(self):
        """Reset factory state before each test."""
        # Reset factory to default state
        OutputFormatterFactory._formatter = None
        OutputFormatterFactory._format_type = "text"
        OutputFormatterFactory._schema_name = None
        OutputFormatterFactory._database_name = None
        OutputFormatterFactory._output_dir = None

    def test_factory_initial_state(self):
        """Test factory initial state."""
        assert OutputFormatterFactory._formatter is None
        assert OutputFormatterFactory._format_type == "text"
        assert OutputFormatterFactory._schema_name is None
        assert OutputFormatterFactory._database_name is None
        assert OutputFormatterFactory._output_dir is None

    def test_configure_basic(self):
        """Test basic configuration."""
        OutputFormatterFactory.configure(
            format_type="html", schema_name="test_schema", database_name="test_db"
        )

        assert OutputFormatterFactory._format_type == "html"
        assert OutputFormatterFactory._schema_name == "test_schema"
        assert OutputFormatterFactory._database_name == "test_db"
        assert OutputFormatterFactory._output_dir is None
        assert OutputFormatterFactory._formatter is None  # Should be reset

    def test_configure_with_output_dir(self):
        """Test configuration with output directory."""
        output_dir = Path("/test/output")

        OutputFormatterFactory.configure(
            format_type="JSON",  # Test case insensitive
            schema_name="schema",
            database_name="database",
            output_dir=output_dir,
        )

        assert OutputFormatterFactory._format_type == "json"  # Should be lowercase
        assert OutputFormatterFactory._schema_name == "schema"
        assert OutputFormatterFactory._database_name == "database"
        assert OutputFormatterFactory._output_dir == output_dir

    def test_configure_resets_formatter(self):
        """Test that configure resets the formatter instance."""
        # Create a formatter first
        result = OperationResult()
        formatter1 = OutputFormatterFactory.get_formatter(result)
        assert formatter1 is not None
        assert OutputFormatterFactory._formatter is formatter1

        # Configure should reset the formatter
        OutputFormatterFactory.configure(format_type="html")
        assert OutputFormatterFactory._formatter is None

        # Getting formatter again should create a new instance
        formatter2 = OutputFormatterFactory.get_formatter(result)
        assert formatter2 is not None
        assert formatter2 is not formatter1

    def test_get_formatter_creates_instance(self):
        """Test that get_formatter creates OutputFormatter instance."""
        result = OperationResult()

        formatter = OutputFormatterFactory.get_formatter(result)

        assert isinstance(formatter, OutputFormatter)
        assert OutputFormatterFactory._formatter is formatter

    def test_get_formatter_reuses_instance(self):
        """Test that get_formatter reuses existing instance."""
        result = OperationResult()

        formatter1 = OutputFormatterFactory.get_formatter(result)
        formatter2 = OutputFormatterFactory.get_formatter(result)

        assert formatter1 is formatter2

    def test_format_result_basic(self):
        """Test basic result formatting."""
        result = OperationResult()
        result.success = True

        with patch.object(
            OutputFormatter, "format", return_value="formatted output"
        ) as mock_format:
            output = OutputFormatterFactory.format_result(result)

            assert output == "formatted output"
            mock_format.assert_called_once_with(
                result, format_type="text", schema_name=None, database_name=None, output_path=None
            )

    def test_format_result_with_configuration(self):
        """Test result formatting with factory configuration."""
        OutputFormatterFactory.configure(
            format_type="html", schema_name="test_schema", database_name="test_db"
        )

        result = MigrateResult()
        result.success = True

        with patch.object(OutputFormatter, "format", return_value="html output") as mock_format:
            output = OutputFormatterFactory.format_result(result)

            assert output == "html output"
            mock_format.assert_called_once_with(
                result,
                format_type="html",
                schema_name="test_schema",
                database_name="test_db",
                output_path=None,
            )

    def test_format_result_html_with_output_dir(self):
        """Test HTML result formatting with output directory."""
        output_dir = Path("/test/output")
        OutputFormatterFactory.configure(
            format_type="html",
            schema_name="test_schema",
            database_name="test_db",
            output_dir=output_dir,
        )

        result = MigrateResult()

        # Mock the formatter and its HTML formatter
        mock_html_formatter = Mock()
        mock_html_formatter.get_output_filename.return_value = "test_report.html"

        with patch.object(OutputFormatterFactory, "get_formatter") as mock_get_formatter:
            mock_formatter = Mock()
            mock_formatter._get_command_type.return_value = "migrate"
            mock_formatter.html_formatter = mock_html_formatter
            mock_formatter.format.return_value = "html content"
            mock_get_formatter.return_value = mock_formatter

            output = OutputFormatterFactory.format_result(result)

            assert output == "html content"
            mock_html_formatter.get_output_filename.assert_called_once_with(
                "test_schema", "test_db", "migrate"
            )
            expected_output_path = output_dir / "test_report.html"
            mock_formatter.format.assert_called_once_with(
                result,
                format_type="html",
                schema_name="test_schema",
                database_name="test_db",
                output_path=expected_output_path,
            )

    def test_format_result_json_with_output_dir(self):
        """Test JSON result formatting with output directory."""
        output_dir = Path("/test/output")
        OutputFormatterFactory.configure(
            format_type="json",
            schema_name="schema",
            database_name="database",
            output_dir=output_dir,
        )

        result = OperationResult()

        # Mock the formatter and its JSON formatter
        mock_json_formatter = Mock()
        mock_json_formatter.get_output_filename.return_value = "test_report.json"

        with patch.object(OutputFormatterFactory, "get_formatter") as mock_get_formatter:
            mock_formatter = Mock()
            mock_formatter._get_command_type.return_value = "operation"
            mock_formatter.json_formatter = mock_json_formatter
            mock_formatter.format.return_value = '{"status": "success"}'
            mock_get_formatter.return_value = mock_formatter

            output = OutputFormatterFactory.format_result(result)

            assert output == '{"status": "success"}'
            mock_json_formatter.get_output_filename.assert_called_once_with(
                "schema", "database", "operation"
            )
            expected_output_path = output_dir / "test_report.json"
            mock_formatter.format.assert_called_once_with(
                result,
                format_type="json",
                schema_name="schema",
                database_name="database",
                output_path=expected_output_path,
            )

    def test_format_result_html_no_html_formatter(self):
        """Test HTML formatting when html_formatter is not available."""
        output_dir = Path("/test/output")
        OutputFormatterFactory.configure(
            format_type="html",
            schema_name="test_schema",
            database_name="test_db",
            output_dir=output_dir,
        )

        result = OperationResult()

        with patch.object(OutputFormatterFactory, "get_formatter") as mock_get_formatter:
            mock_formatter = Mock()
            mock_formatter._get_command_type.return_value = "operation"
            mock_formatter.html_formatter = None  # No HTML formatter available
            mock_formatter.format.return_value = "text fallback"
            mock_get_formatter.return_value = mock_formatter

            output = OutputFormatterFactory.format_result(result)

            assert output == "text fallback"
            # Should call format without output_path since HTML formatter is not available
            mock_formatter.format.assert_called_once_with(
                result,
                format_type="html",
                schema_name="test_schema",
                database_name="test_db",
                output_path=None,
            )

    def test_format_result_json_no_json_formatter(self):
        """Test JSON formatting when json_formatter is not available."""
        output_dir = Path("/test/output")
        OutputFormatterFactory.configure(
            format_type="json",
            schema_name="schema",
            database_name="database",
            output_dir=output_dir,
        )

        result = OperationResult()

        with patch.object(OutputFormatterFactory, "get_formatter") as mock_get_formatter:
            mock_formatter = Mock()
            mock_formatter._get_command_type.return_value = "operation"
            mock_formatter.json_formatter = None  # No JSON formatter available
            mock_formatter.format.return_value = "text fallback"
            mock_get_formatter.return_value = mock_formatter

            output = OutputFormatterFactory.format_result(result)

            assert output == "text fallback"
            # Should call format without output_path since JSON formatter is not available
            mock_formatter.format.assert_called_once_with(
                result,
                format_type="json",
                schema_name="schema",
                database_name="database",
                output_path=None,
            )

    def test_format_result_text_with_output_dir(self):
        """Test text formatting with output directory (should not create output path)."""
        output_dir = Path("/test/output")
        OutputFormatterFactory.configure(
            format_type="text",
            schema_name="schema",
            database_name="database",
            output_dir=output_dir,
        )

        result = OperationResult()

        with patch.object(OutputFormatter, "format", return_value="text output") as mock_format:
            output = OutputFormatterFactory.format_result(result)

            assert output == "text output"
            # Text format should not create output path even with output_dir
            mock_format.assert_called_once_with(
                result,
                format_type="text",
                schema_name="schema",
                database_name="database",
                output_path=None,
            )

    def test_format_result_default_names(self):
        """Test formatting with default schema and database names."""
        output_dir = Path("/test/output")
        OutputFormatterFactory.configure(format_type="html", output_dir=output_dir)

        result = OperationResult()

        # Mock the formatter and its HTML formatter
        mock_html_formatter = Mock()
        mock_html_formatter.get_output_filename.return_value = "default_report.html"

        with patch.object(OutputFormatterFactory, "get_formatter") as mock_get_formatter:
            mock_formatter = Mock()
            mock_formatter._get_command_type.return_value = "operation"
            mock_formatter.html_formatter = mock_html_formatter
            mock_formatter.format.return_value = "html content"
            mock_get_formatter.return_value = mock_formatter

            output = OutputFormatterFactory.format_result(result)

            assert output == "html content"
            # Should use "default" for None schema/database names
            mock_html_formatter.get_output_filename.assert_called_once_with(
                "default", "default", "operation"
            )

    def test_format_result_missing_html_formatter_attribute(self):
        """Test HTML formatting when formatter doesn't have html_formatter attribute."""
        output_dir = Path("/test/output")
        OutputFormatterFactory.configure(
            format_type="html",
            schema_name="schema",
            database_name="database",
            output_dir=output_dir,
        )

        result = OperationResult()

        with patch.object(OutputFormatterFactory, "get_formatter") as mock_get_formatter:
            mock_formatter = Mock()
            mock_formatter._get_command_type.return_value = "operation"
            # Simulate missing html_formatter attribute
            del mock_formatter.html_formatter
            mock_formatter.format.return_value = "text fallback"
            mock_get_formatter.return_value = mock_formatter

            output = OutputFormatterFactory.format_result(result)

            assert output == "text fallback"
            mock_formatter.format.assert_called_once_with(
                result,
                format_type="html",
                schema_name="schema",
                database_name="database",
                output_path=None,
            )

    def test_format_result_missing_json_formatter_attribute(self):
        """Test JSON formatting when formatter doesn't have json_formatter attribute."""
        output_dir = Path("/test/output")
        OutputFormatterFactory.configure(
            format_type="json",
            schema_name="schema",
            database_name="database",
            output_dir=output_dir,
        )

        result = OperationResult()

        with patch.object(OutputFormatterFactory, "get_formatter") as mock_get_formatter:
            mock_formatter = Mock()
            mock_formatter._get_command_type.return_value = "operation"
            # Simulate missing json_formatter attribute
            del mock_formatter.json_formatter
            mock_formatter.format.return_value = "text fallback"
            mock_get_formatter.return_value = mock_formatter

            output = OutputFormatterFactory.format_result(result)

            assert output == "text fallback"
            mock_formatter.format.assert_called_once_with(
                result,
                format_type="json",
                schema_name="schema",
                database_name="database",
                output_path=None,
            )
