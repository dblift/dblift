"""Tests for format_diff() decomposition into private helpers (story 19-10).

Validates that the 14 extracted helpers produce correct output independently
and that format_diff() is now a pure orchestrator under 35 lines.
"""

import inspect

import pytest

from core.comparison.diff_models import (
    ColumnDiff,
    ConstraintDiff,
    DiffSeverity,
    IndexDiff,
    SchemaDiff,
    TableDiff,
    ViewDiff,
)
from core.logger.formatters.formatter import OutputFormatter
from core.logger.results import DiffResult


def _make_diff_result(schema_name="public", success=True, total_differences=0, error_count=0):
    """Helper to create a DiffResult with a SchemaDiff attached.

    Note: set_schema_diff recalculates success/error_count from schema_diff data,
    so the explicit overrides below must come AFTER set_schema_diff to be effective.
    """
    result = DiffResult()
    result.target_schema = schema_name
    result.source_type = "script"
    result.target_type = "database"
    schema_diff = SchemaDiff(object_name=schema_name, schema_name=schema_name)
    result.set_schema_diff(schema_diff)
    # Override after set_schema_diff (which recalculates from schema_diff content)
    result.success = success
    result.total_differences = total_differences
    result.error_count = error_count
    return result


@pytest.mark.unit
class TestFormatDiffHeader:
    """Tests for _format_diff_header."""

    def setup_method(self):
        self.formatter = OutputFormatter()

    def test_header_contains_schema_name(self):
        result = _make_diff_result(schema_name="myschema")
        output = self.formatter._format_diff_header(result)
        assert "Schema: myschema" in output

    def test_header_contains_comparison_report_title(self):
        result = _make_diff_result()
        output = self.formatter._format_diff_header(result)
        assert "Schema Comparison Report" in output

    def test_header_success_vs_failure_status(self):
        result_ok = _make_diff_result(success=True, total_differences=0)
        output_ok = self.formatter._format_diff_header(result_ok)
        assert "✓ No critical differences" in output_ok

        result_fail = _make_diff_result(success=False)
        result_fail.error_count = 3
        output_fail = self.formatter._format_diff_header(result_fail)
        assert "✗ 3 critical difference(s) found" in output_fail


@pytest.mark.unit
class TestFormatDiffCounts:
    """Tests for _format_diff_counts."""

    def setup_method(self):
        self.formatter = OutputFormatter()

    def test_counts_shows_table_counts(self):
        result = _make_diff_result()
        result.missing_tables = ["t1"]
        result.extra_tables = ["t2", "t3"]
        output = self.formatter._format_diff_counts(result)
        assert "Missing Tables:  1" in output
        assert "Extra Tables:    2" in output

    def test_counts_all_zeros_still_renders(self):
        result = _make_diff_result()
        output = self.formatter._format_diff_counts(result)
        assert "Summary:" in output
        assert "Missing Tables:  0" in output
        assert "Total Diffs:     0" in output

    def test_counts_includes_postgresql_specific_objects(self):
        result = _make_diff_result()
        result.missing_extensions = ["pg_trgm"]
        result.missing_foreign_data_wrappers = ["postgres_fdw"]
        output = self.formatter._format_diff_counts(result)
        assert "Missing Extensions: 1" in output
        assert "Missing Foreign Data Wrappers: 1" in output


@pytest.mark.unit
class TestFormatTableDiff:
    """Tests for _format_table_diff."""

    def setup_method(self):
        self.formatter = OutputFormatter()

    def test_table_diff_shows_missing_table(self):
        result = _make_diff_result()
        result.missing_tables = ["users"]
        output = self.formatter._format_table_diff(result)
        assert "Missing Tables (1):" in output
        assert "  - users" in output

    def test_table_diff_shows_extra_table(self):
        result = _make_diff_result()
        result.extra_tables = ["temp_data"]
        output = self.formatter._format_table_diff(result)
        assert "Extra Tables (1):" in output
        assert "  + temp_data" in output

    def test_table_diff_shows_modified_column(self):
        result = _make_diff_result()
        col_diff = ColumnDiff(
            object_name="email",
            column_name="email",
            data_type_diff=("varchar(100)", "varchar(255)"),
            nullable_diff=(False, True),
        )
        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            modified_columns=[col_diff],
        )
        result.schema_diff.modified_tables = [table_diff]
        output = self.formatter._format_table_diff(result)
        assert "Modified Tables (1):" in output
        assert "email" in output
        assert "type: varchar(100) → varchar(255)" in output
        assert "nullable: False → True" in output

    def test_table_diff_shows_modified_constraint(self):
        result = _make_diff_result()
        const_diff = ConstraintDiff(
            object_name="pk_users",
            constraint_name="pk_users",
            constraint_type="PRIMARY KEY",
            columns_diff=(["id"], ["id", "tenant_id"]),
        )
        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            modified_constraints=[const_diff],
        )
        result.schema_diff.modified_tables = [table_diff]
        output = self.formatter._format_table_diff(result)
        assert "Modified Constraints (1):" in output
        assert "pk_users" in output

    def test_table_diff_empty_when_no_diffs(self):
        result = _make_diff_result()
        output = self.formatter._format_table_diff(result)
        assert output == ""


@pytest.mark.unit
class TestFormatViewDiff:
    """Tests for _format_view_diff."""

    def setup_method(self):
        self.formatter = OutputFormatter()

    def test_view_diff_shows_missing_view(self):
        result = _make_diff_result()
        result.missing_views = ["v_active_users"]
        output = self.formatter._format_view_diff(result)
        assert "Missing Views (1):" in output
        assert "  - v_active_users" in output

    def test_view_diff_empty_when_no_diffs(self):
        result = _make_diff_result()
        output = self.formatter._format_view_diff(result)
        assert output == ""


@pytest.mark.unit
class TestFormatIndexDiff:
    """Tests for _format_index_diff."""

    def setup_method(self):
        self.formatter = OutputFormatter()

    def test_index_diff_shows_missing_index(self):
        result = _make_diff_result()
        result.missing_indexes = ["idx_users_email"]
        output = self.formatter._format_index_diff(result)
        assert "Missing Indexes (1):" in output
        assert "  - idx_users_email" in output

    def test_index_diff_empty_when_no_diffs(self):
        result = _make_diff_result()
        output = self.formatter._format_index_diff(result)
        assert output == ""


@pytest.mark.unit
class TestFormatDiffFooter:
    """Tests for _format_diff_footer."""

    def setup_method(self):
        self.formatter = OutputFormatter()

    def test_footer_contains_execution_time(self):
        result = _make_diff_result()
        output = self.formatter._format_diff_footer(result)
        assert "Execution time:" in output
        assert "ms" in output


@pytest.mark.unit
class TestFormatHelperEmptyWhenNoDiffs:
    """Verify each helper returns '' when no relevant diffs exist (AC#1 contract)."""

    def setup_method(self):
        self.formatter = OutputFormatter()
        self.result = _make_diff_result()

    def test_sequence_diff_empty_when_no_diffs(self):
        assert self.formatter._format_sequence_diff(self.result) == ""

    def test_trigger_diff_empty_when_no_diffs(self):
        assert self.formatter._format_trigger_diff(self.result) == ""

    def test_procedure_diff_empty_when_no_diffs(self):
        assert self.formatter._format_procedure_diff(self.result) == ""

    def test_type_diff_empty_when_no_diffs(self):
        assert self.formatter._format_type_diff(self.result) == ""

    def test_extension_diff_empty_when_no_diffs(self):
        assert self.formatter._format_extension_diff(self.result) == ""

    def test_fdw_diff_empty_when_no_diffs(self):
        assert self.formatter._format_fdw_diff(self.result) == ""

    def test_server_diff_empty_when_no_diffs(self):
        assert self.formatter._format_server_diff(self.result) == ""

    def test_event_diff_empty_when_no_diffs(self):
        assert self.formatter._format_event_diff(self.result) == ""


@pytest.mark.unit
class TestFormatDiffStructural:
    """Structural tests for format_diff decomposition."""

    def test_format_diff_is_orchestrator_under_35_lines(self):
        source = inspect.getsource(OutputFormatter.format_diff)
        line_count = len(source.strip().splitlines())
        assert line_count < 35, f"format_diff has {line_count} lines, expected < 35"

    def test_all_helpers_in_class_dict(self):
        expected_helpers = [
            "_format_diff_header",
            "_format_diff_counts",
            "_format_table_diff",
            "_format_view_diff",
            "_format_index_diff",
            "_format_sequence_diff",
            "_format_trigger_diff",
            "_format_procedure_diff",
            "_format_type_diff",
            "_format_extension_diff",
            "_format_fdw_diff",
            "_format_server_diff",
            "_format_event_diff",
            "_format_diff_footer",
        ]
        for helper in expected_helpers:
            assert hasattr(
                OutputFormatter, helper
            ), f"{helper} not found on OutputFormatter (may be in a mixin)"

    def test_format_diff_in_class_dict(self):
        assert hasattr(OutputFormatter, "format_diff")
