"""Final edge case tests for OutputFormatter to maximize coverage.

This module tests remaining edge cases in OutputFormatter.
"""

from datetime import datetime
from unittest.mock import Mock, patch

import pytest

from core.comparison.diff_models import SchemaDiff
from core.logger.formatters.formatter import OutputFormatter
from core.logger.results import DiffResult, OperationResult


@pytest.mark.unit
class TestOutputFormatterFinal:
    """Final edge case tests for OutputFormatter."""

    def setup_method(self):
        """Set up test fixtures."""
        self.formatter = OutputFormatter()

    def test_format_generic_with_error_no_message(self):
        """Test format_generic with error but no error_message."""
        result = OperationResult()
        result.success = False
        result.error_message = None
        result.start_time = datetime.fromtimestamp(1000)
        result.end_time = datetime.fromtimestamp(1500)

        output = self.formatter.format_generic(result)

        assert "Status: FAILED" in output
        # Should not show error message when None
        assert "Error: None" not in output

    def test_format_generic_with_error_and_message(self):
        """Test format_generic with error and error_message."""
        result = OperationResult()
        result.success = False
        result.error_message = "Test error"
        result.start_time = datetime.fromtimestamp(1000)
        result.end_time = datetime.fromtimestamp(1500)

        output = self.formatter.format_generic(result)

        assert "Status: FAILED" in output
        assert "Error: Test error" in output

    def test_format_generic_with_warnings(self):
        """Test format_generic with warnings."""
        result = OperationResult()
        result.success = True
        result.warnings = ["Warning 1"]
        result.start_time = datetime.fromtimestamp(1000)
        result.end_time = datetime.fromtimestamp(1500)

        output = self.formatter.format_generic(result)

        assert "Warnings:" in output
        assert "Warning 1" in output

    def test_format_migrate_success_no_error_message(self):
        """Test format_migrate with success=True and no error_message."""
        from core.logger.results import MigrateResult

        result = MigrateResult()
        result.success = True
        result.target_schema = "test_schema"
        result.error_message = None  # No error message
        result.start_time = datetime.fromtimestamp(1000)
        result.end_time = datetime.fromtimestamp(1500)

        output = self.formatter.format_migrate(result)

        # Should show SUCCESS since success=True and no error_message
        assert "Status: SUCCESS" in output

    def test_format_migrate_failed_with_error_message(self):
        """Test format_migrate with success=False and error_message."""
        from core.logger.results import MigrateResult

        result = MigrateResult()
        result.success = False
        result.target_schema = "test_schema"
        result.error_message = "Migration error"
        result.start_time = datetime.fromtimestamp(1000)
        result.end_time = datetime.fromtimestamp(1500)

        output = self.formatter.format_migrate(result)

        assert "Status: FAILED" in output
        assert "Error: Migration error" in output

    def test_format_migrate_failed_no_error_message(self):
        """Test format_migrate with success=False but no error_message."""
        from core.logger.results import MigrateResult

        result = MigrateResult()
        result.success = False
        result.target_schema = "test_schema"
        result.error_message = None
        result.start_time = datetime.fromtimestamp(1000)
        result.end_time = datetime.fromtimestamp(1500)

        output = self.formatter.format_migrate(result)

        assert "Status: FAILED" in output
        assert "Error: Unknown error occurred" in output

    def test_format_clean_with_schemas_and_tables(self):
        """Test format_clean with both schemas and tables dropped."""
        from core.logger.results import CleanResult

        result = CleanResult()
        result.success = True
        result.schema_name = "test_schema"
        result.start_time = datetime.fromtimestamp(1000)
        result.end_time = datetime.fromtimestamp(1500)
        result.add_schema_dropped("old_schema")
        result.add_table_dropped("old_table")

        output = self.formatter.format_clean(result)

        assert "Schemas dropped:" in output
        assert "old_schema" in output
        assert "Tables dropped:" in output
        assert "old_table" in output

    def test_format_clean_with_error(self):
        """Test format_clean with error."""
        from core.logger.results import CleanResult

        result = CleanResult()
        result.success = False
        result.schema_name = "test_schema"
        result.error_message = "Clean error"
        result.start_time = datetime.fromtimestamp(1000)
        result.end_time = datetime.fromtimestamp(1500)

        output = self.formatter.format_clean(result)

        assert "Status: FAILED" in output
        assert "Error: Clean error" in output

    def test_format_info_with_none_schema_version(self):
        """Test format_info with None current_schema_version."""
        from core.logger.results import InfoResult

        result = InfoResult()
        result.success = True
        result.schema_name = "test_schema"
        result.current_schema_version = None
        result.start_time = datetime.fromtimestamp(1000)
        result.end_time = datetime.fromtimestamp(1500)

        output = self.formatter.format_info(result)

        assert "Current schema version: n/a" in output

    def test_format_info_with_error(self):
        """Test format_info with error."""
        from core.logger.results import InfoResult

        result = InfoResult()
        result.success = False
        result.schema_name = "test_schema"
        result.error_message = "Info error"
        result.start_time = datetime.fromtimestamp(1000)
        result.end_time = datetime.fromtimestamp(1500)

        output = self.formatter.format_info(result)

        assert "Status: FAILED" in output
        assert "Error: Info error" in output

    def test_format_diff_table_get_diff_count(self):
        """Test format_diff calls get_diff_count on table_diff."""
        from core.comparison.diff_models import TableDiff

        result = DiffResult()
        result.target_schema = "public"

        table_diff = TableDiff(object_name="users", table_name="users", missing_columns=["email"])
        # Ensure get_diff_count is called
        table_diff.get_diff_count()

        schema_diff = SchemaDiff(
            object_name="public", schema_name="public", modified_tables=[table_diff]
        )
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "users" in output
        assert "Missing Columns" in output

    def test_format_diff_table_with_all_column_diffs(self):
        """Test format_diff with table having all types of column diffs."""
        from core.comparison.diff_models import ColumnDiff, TableDiff

        result = DiffResult()
        result.target_schema = "public"

        col_diff = ColumnDiff(
            object_name="test_col",
            column_name="test_col",
            data_type_diff=("INTEGER", "VARCHAR"),
            nullable_diff=(True, False),
            default_diff=("0", "1"),
            identity_diff=(True, False),
            computed_diff=(True, False),
        )

        table_diff = TableDiff(object_name="users", table_name="users", modified_columns=[col_diff])

        schema_diff = SchemaDiff(
            object_name="public", schema_name="public", modified_tables=[table_diff]
        )
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "test_col" in output
        assert "type:" in output
        assert "nullable" in output
        assert "default" in output
        assert "identity" in output
        assert "computed" in output

    def test_format_diff_table_with_no_column_diffs(self):
        """Test format_diff with table having no column diffs (only constraints/indexes)."""
        from core.comparison.diff_models import TableDiff

        result = DiffResult()
        result.target_schema = "public"

        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            missing_columns=[],
            extra_columns=[],
            modified_columns=[],
            missing_constraints=["pk_users"],
        )

        schema_diff = SchemaDiff(
            object_name="public", schema_name="public", modified_tables=[table_diff]
        )
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "users" in output
        assert "Missing Constraints" in output
        # Should not show column sections when empty
        assert "Missing Columns (0)" not in output

    def test_format_diff_table_with_extra_columns(self):
        """Test format_diff with table having extra columns."""
        from core.comparison.diff_models import TableDiff

        result = DiffResult()
        result.target_schema = "public"

        table_diff = TableDiff(
            object_name="users", table_name="users", extra_columns=["phone", "address"]
        )

        schema_diff = SchemaDiff(
            object_name="public", schema_name="public", modified_tables=[table_diff]
        )
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "users" in output
        assert "Extra Columns" in output
        assert "phone" in output
        assert "address" in output

    def test_format_diff_table_with_all_constraint_diffs(self):
        """Test format_diff with table having all types of constraint diffs."""
        from core.comparison.diff_models import ConstraintDiff, TableDiff

        result = DiffResult()
        result.target_schema = "public"

        constraint_diff = ConstraintDiff(
            object_name="test_const",
            constraint_name="test_const",
            columns_diff=(["id"], ["id", "version"]),
            references_diff=("users", "orders"),
            check_clause_diff=("age > 0", "age >= 0"),
        )

        table_diff = TableDiff(
            object_name="users", table_name="users", modified_constraints=[constraint_diff]
        )

        schema_diff = SchemaDiff(
            object_name="public", schema_name="public", modified_tables=[table_diff]
        )
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "test_const" in output
        assert "columns" in output
        assert "references" in output
        assert "check" in output

    def test_format_diff_view_with_expected_definition_only(self):
        """Test format_diff with view having only expected_definition."""
        from core.comparison.diff_models import ViewDiff

        result = DiffResult()
        result.target_schema = "public"

        view_diff = ViewDiff(
            object_name="test_view",
            view_name="test_view",
            definition_changed=True,
            expected_definition="SELECT * FROM users",
            actual_definition=None,
        )

        schema_diff = SchemaDiff(
            object_name="public", schema_name="public", modified_views=[view_diff]
        )
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "test_view" in output
        assert "Definition changed" in output
        assert "Expected:" in output

    def test_format_diff_view_with_actual_definition_only(self):
        """Test format_diff with view having only actual_definition."""
        from core.comparison.diff_models import ViewDiff

        result = DiffResult()
        result.target_schema = "public"

        view_diff = ViewDiff(
            object_name="test_view",
            view_name="test_view",
            definition_changed=True,
            expected_definition=None,
            actual_definition="SELECT id, name FROM users",
        )

        schema_diff = SchemaDiff(
            object_name="public", schema_name="public", modified_views=[view_diff]
        )
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "test_view" in output
        assert "Definition changed" in output
        assert "Actual:" in output

    def test_format_diff_index_with_columns_changed_tuple(self):
        """Test format_diff with index having columns_changed as tuple."""
        from core.comparison.diff_models import IndexDiff

        result = DiffResult()
        result.target_schema = "public"

        index_diff = IndexDiff(
            object_name="idx_users",
            index_name="idx_users",
            table_name="users",
            columns_changed=True,
        )
        # Set as tuple for formatter
        index_diff.columns_changed = (["id"], ["id", "name"])

        schema_diff = SchemaDiff(
            object_name="public", schema_name="public", modified_indexes=[index_diff]
        )
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "idx_users" in output
        assert "Columns" in output
