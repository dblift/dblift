"""Tests for Diff Reporter.

This module tests the DiffReporter class which formats diff results
into human-readable reports.
"""

from unittest.mock import MagicMock, Mock, patch

import pytest

from core.comparison.diff_models import SchemaDiff, TableDiff
from core.comparison.diff_reporter import DiffReporter
from core.logger import DiffResult


@pytest.mark.unit
class TestDiffReporter:
    """Test DiffReporter class."""

    def test_init_default(self):
        """Test DiffReporter initialization with default values."""
        reporter = DiffReporter()

        assert reporter.use_colors is True
        assert reporter.formatter is not None

    def test_init_with_colors_disabled(self):
        """Test DiffReporter initialization with colors disabled."""
        reporter = DiffReporter(use_colors=False)

        assert reporter.use_colors is False
        assert reporter.formatter is not None

    def test_create_diff_result_with_schema_diff(self):
        """Test creating DiffResult with schema_diff."""
        reporter = DiffReporter()

        schema_diff = SchemaDiff(
            object_name="public",
            schema_name="public",
            missing_tables=["users"],
        )

        result = reporter.create_diff_result(
            schema_diff=schema_diff, comparison_type="schema", target_schema="public"
        )

        assert isinstance(result, DiffResult)
        assert result.comparison_type == "schema"
        assert result.target_schema == "public"
        assert result.source_type == "script"
        assert result.target_type == "database"

    def test_create_diff_result_with_table_diffs(self):
        """Test creating DiffResult with table_diffs."""
        reporter = DiffReporter()

        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            missing_columns=["email"],
        )

        result = reporter.create_diff_result(
            table_diffs=[table_diff], comparison_type="table", target_schema="public"
        )

        assert isinstance(result, DiffResult)
        assert result.comparison_type == "table"
        assert result.target_schema == "public"

    def test_create_diff_result_with_both_schema_and_tables(self):
        """Test creating DiffResult with both schema_diff and table_diffs."""
        reporter = DiffReporter()

        schema_diff = SchemaDiff(
            object_name="public",
            schema_name="public",
        )

        table_diff = TableDiff(
            object_name="users",
            table_name="users",
        )

        result = reporter.create_diff_result(
            schema_diff=schema_diff,
            table_diffs=[table_diff],
            comparison_type="schema",
            target_schema="public",
        )

        assert isinstance(result, DiffResult)
        assert result.comparison_type == "schema"

    def test_create_diff_result_custom_parameters(self):
        """Test creating DiffResult with custom parameters."""
        reporter = DiffReporter()

        result = reporter.create_diff_result(
            comparison_type="table",
            source_type="database",
            target_type="script",
            target_schema="test_schema",
        )

        assert isinstance(result, DiffResult)
        assert result.comparison_type == "table"
        assert result.source_type == "database"
        assert result.target_type == "script"
        assert result.target_schema == "test_schema"

    def test_format_text(self):
        """Test formatting diff result as text."""
        reporter = DiffReporter()

        schema_diff = SchemaDiff(
            object_name="public",
            schema_name="public",
        )

        result = reporter.create_diff_result(schema_diff=schema_diff, target_schema="public")

        formatted = reporter.format(result, format_type="text")

        assert isinstance(formatted, str)
        assert len(formatted) > 0

    def test_format_json(self):
        """Test formatting diff result as JSON."""
        reporter = DiffReporter()

        schema_diff = SchemaDiff(
            object_name="public",
            schema_name="public",
        )

        result = reporter.create_diff_result(schema_diff=schema_diff, target_schema="public")

        formatted = reporter.format(result, format_type="json")

        assert isinstance(formatted, str)
        # JSON should be parseable
        import json

        json.loads(formatted)

    def test_format_html(self):
        """Test formatting diff result as HTML."""
        reporter = DiffReporter()

        schema_diff = SchemaDiff(
            object_name="public",
            schema_name="public",
        )

        result = reporter.create_diff_result(schema_diff=schema_diff, target_schema="public")

        formatted = reporter.format(result, format_type="html")

        assert isinstance(formatted, str)
        assert len(formatted) > 0

    def test_format_with_custom_schema_name(self):
        """Test formatting with custom schema_name."""
        reporter = DiffReporter()

        result = reporter.create_diff_result(target_schema="public")

        formatted = reporter.format(result, format_type="text", schema_name="custom_schema")

        assert isinstance(formatted, str)

    def test_format_with_database_name(self):
        """Test formatting with database_name."""
        reporter = DiffReporter()

        result = reporter.create_diff_result(target_schema="public")

        formatted = reporter.format(
            result, format_type="text", schema_name="public", database_name="testdb"
        )

        assert isinstance(formatted, str)

    def test_format_schema_diff(self):
        """Test format_schema_diff convenience method."""
        reporter = DiffReporter()

        schema_diff = SchemaDiff(
            object_name="public",
            schema_name="public",
            missing_tables=["users"],
        )

        formatted = reporter.format_schema_diff(
            schema_diff, format_type="text", schema_name="public"
        )

        assert isinstance(formatted, str)
        assert len(formatted) > 0

    def test_format_schema_diff_json(self):
        """Test format_schema_diff with JSON format."""
        reporter = DiffReporter()

        schema_diff = SchemaDiff(
            object_name="public",
            schema_name="public",
        )

        formatted = reporter.format_schema_diff(
            schema_diff, format_type="json", schema_name="public"
        )

        assert isinstance(formatted, str)
        import json

        json.loads(formatted)

    def test_format_table_diff(self):
        """Test format_table_diff convenience method."""
        reporter = DiffReporter()

        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            missing_columns=["email"],
        )

        formatted = reporter.format_table_diff(table_diff, format_type="text", schema_name="public")

        assert isinstance(formatted, str)
        assert len(formatted) > 0

    def test_format_table_diff_json(self):
        """Test format_table_diff with JSON format."""
        reporter = DiffReporter()

        table_diff = TableDiff(
            object_name="users",
            table_name="users",
        )

        formatted = reporter.format_table_diff(table_diff, format_type="json", schema_name="public")

        assert isinstance(formatted, str)
        import json

        json.loads(formatted)

    def test_format_uses_result_target_schema_when_not_provided(self):
        """Test that format uses result.target_schema when schema_name not provided."""
        reporter = DiffReporter()

        result = reporter.create_diff_result(target_schema="custom_schema")

        # Mock formatter to verify it receives correct schema_name
        mock_formatter = MagicMock()
        mock_formatter.format.return_value = "formatted output"
        reporter.formatter = mock_formatter

        reporter.format(result, format_type="text")

        # Verify formatter was called with custom_schema
        mock_formatter.format.assert_called_once()
        call_kwargs = mock_formatter.format.call_args[1]
        assert call_kwargs["schema_name"] == "custom_schema"

    def test_format_with_explicit_schema_name_overrides_result(self):
        """Test that explicit schema_name overrides result.target_schema."""
        reporter = DiffReporter()

        result = reporter.create_diff_result(target_schema="default_schema")

        # Mock formatter to verify it receives correct schema_name
        mock_formatter = MagicMock()
        mock_formatter.format.return_value = "formatted output"
        reporter.formatter = mock_formatter

        reporter.format(result, format_type="text", schema_name="explicit_schema")

        # Verify formatter was called with explicit_schema
        mock_formatter.format.assert_called_once()
        call_kwargs = mock_formatter.format.call_args[1]
        assert call_kwargs["schema_name"] == "explicit_schema"
