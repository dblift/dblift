"""Edge case tests for OutputFormatter to further improve coverage.

This module tests edge cases and uncovered branches in OutputFormatter.
"""

from datetime import datetime
from unittest.mock import Mock, patch

import pytest

from core.comparison.diff_models import (
    ColumnDiff,
    ConstraintDiff,
    DiffSeverity,
    IndexDiff,
    ProcedureDiff,
    SchemaDiff,
    TableDiff,
    ViewDiff,
)
from core.logger.formatters.formatter import OutputFormatter
from core.logger.results import (
    BaselineResult,
    CleanResult,
    DiffResult,
    InfoResult,
    MigrateResult,
    OperationResult,
    RepairResult,
    ValidateResult,
)


@pytest.mark.unit
class TestOutputFormatterEdgeCases:
    """Edge case tests for OutputFormatter."""

    def setup_method(self):
        """Set up test fixtures."""
        self.formatter = OutputFormatter()

    def test_format_with_baseline_result(self):
        """Test format method with BaselineResult."""
        result = BaselineResult()
        result.success = True
        result.schema_name = "test_schema"
        result.baseline_version = "1.0.0"
        result.start_time = datetime.fromtimestamp(1000)
        result.end_time = datetime.fromtimestamp(1500)

        output = self.formatter.format(result, "text")

        assert "Database Baseline Report" in output

    def test_format_with_repair_result(self):
        """Test format method with RepairResult."""
        result = RepairResult()
        result.success = True
        result.start_time = datetime.fromtimestamp(1000)
        result.end_time = datetime.fromtimestamp(1500)

        output = self.formatter.format(result, "text")

        assert "Database Repair Report" in output

    def test_format_with_info_result(self):
        """Test format method with InfoResult."""
        result = InfoResult()
        result.success = True
        result.schema_name = "test_schema"
        result.start_time = datetime.fromtimestamp(1000)
        result.end_time = datetime.fromtimestamp(1500)

        output = self.formatter.format(result, "text")

        assert "Database Info Report" in output

    def test_format_with_validate_result(self):
        """Test format method with ValidateResult."""
        result = ValidateResult()
        result.success = True
        result.start_time = datetime.fromtimestamp(1000)
        result.end_time = datetime.fromtimestamp(1500)

        output = self.formatter.format(result, "text")

        assert "Database Validation Report" in output

    def test_format_with_clean_result(self):
        """Test format method with CleanResult."""
        result = CleanResult()
        result.success = True
        result.schema_name = "test_schema"
        result.start_time = datetime.fromtimestamp(1000)
        result.end_time = datetime.fromtimestamp(1500)

        output = self.formatter.format(result, "text")

        assert "Database Clean Report" in output

    def test_format_with_diff_result(self):
        """Test format method with DiffResult."""
        result = DiffResult()
        result.target_schema = "public"

        schema_diff = SchemaDiff(object_name="public", schema_name="public")
        result.set_schema_diff(schema_diff)

        output = self.formatter.format(result, "text")

        assert "Schema Comparison Report" in output

    def test_format_generic_with_no_warnings(self):
        """Test format_generic with no warnings."""
        result = OperationResult()
        result.success = True
        result.warnings = []
        result.start_time = datetime.fromtimestamp(1000)
        result.end_time = datetime.fromtimestamp(1500)

        output = self.formatter.format_generic(result)

        assert "Operation Report" in output
        assert "Status: SUCCESS" in output
        assert "Warnings:" not in output

    def test_format_migrate_with_migration_none_version(self):
        """Test format_migrate with migration having None version."""
        result = MigrateResult()
        result.success = True
        result.target_schema = "test_schema"
        result.start_time = datetime.fromtimestamp(1000)
        result.end_time = datetime.fromtimestamp(1500)

        migration = Mock()
        migration.version = None
        migration.description = "Test migration"
        migration.type = "SQL"
        migration.status = "SUCCESS"
        migration.execution_time = 250
        result.migrations = [migration]

        output = self.formatter.format_migrate(result)

        assert "Database Migration Report" in output
        assert "n/a" in output or "Vn/a" in output

    def test_format_clean_with_only_schemas_dropped(self):
        """Test format_clean with only schemas dropped."""
        result = CleanResult()
        result.success = True
        result.schema_name = "test_schema"
        result.start_time = datetime.fromtimestamp(1000)
        result.end_time = datetime.fromtimestamp(1500)
        result.add_schema_dropped("old_schema")

        output = self.formatter.format_clean(result)

        assert "Schemas dropped:" in output
        assert "old_schema" in output
        assert "Tables dropped:" not in output

    def test_format_clean_with_only_tables_dropped(self):
        """Test format_clean with only tables dropped."""
        result = CleanResult()
        result.success = True
        result.schema_name = "test_schema"
        result.start_time = datetime.fromtimestamp(1000)
        result.end_time = datetime.fromtimestamp(1500)
        result.add_table_dropped("old_table")

        output = self.formatter.format_clean(result)

        assert "Tables dropped:" in output
        assert "old_table" in output

    def test_format_info_with_migration_none_version(self):
        """Test format_info with migration having None version."""
        result = InfoResult()
        result.success = True
        result.schema_name = "test_schema"
        result.start_time = datetime.fromtimestamp(1000)
        result.end_time = datetime.fromtimestamp(1500)

        migration = Mock()
        migration.version = None
        migration.description = "Test migration"
        migration.type = "SQL"
        migration.status = "PENDING"
        result.migrations = [migration]

        output = self.formatter.format_info(result)

        assert "Available Migrations" in output
        assert "n/a" in output

    def test_format_validate_with_error_message(self):
        """Test format_validate with error_message."""
        result = ValidateResult()
        result.success = False
        result.error_count = 2
        result.error_message = "Validation failed"
        result.start_time = datetime.fromtimestamp(1000)
        result.end_time = datetime.fromtimestamp(1500)

        output = self.formatter.format_validate(result)

        assert "Status: FAILED" in output
        assert "Found 2 validation errors" in output
        assert "Error: Validation failed" in output

    def test_format_baseline_with_error(self):
        """Test format_baseline with error."""
        result = BaselineResult()
        result.success = False
        result.schema_name = "test_schema"
        result.error_message = "Baseline failed"
        result.start_time = datetime.fromtimestamp(1000)
        result.end_time = datetime.fromtimestamp(1500)

        output = self.formatter.format_baseline(result)

        assert "Status: FAILED" in output
        assert "Error: Baseline failed" in output

    def test_format_repair_with_error(self):
        """Test format_repair with error."""
        result = RepairResult()
        result.success = False
        result.error_message = "Repair failed"
        result.start_time = datetime.fromtimestamp(1000)
        result.end_time = datetime.fromtimestamp(1500)

        output = self.formatter.format_repair(result)

        assert "Status: FAILED" in output
        assert "Error: Repair failed" in output

    def test_format_diff_table_with_missing_constraints(self):
        """Test format_diff with table having missing constraints."""
        result = DiffResult()
        result.target_schema = "public"

        table_diff = TableDiff(
            object_name="users", table_name="users", missing_constraints=["pk_users"]
        )

        schema_diff = SchemaDiff(
            object_name="public", schema_name="public", modified_tables=[table_diff]
        )
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "Missing Constraints" in output
        assert "pk_users" in output

    def test_format_diff_table_with_extra_constraints(self):
        """Test format_diff with table having extra constraints."""
        result = DiffResult()
        result.target_schema = "public"

        table_diff = TableDiff(
            object_name="users", table_name="users", extra_constraints=["extra_constraint"]
        )

        schema_diff = SchemaDiff(
            object_name="public", schema_name="public", modified_tables=[table_diff]
        )
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "Extra Constraints" in output
        assert "extra_constraint" in output

    def test_format_diff_table_with_warning_severity_column(self):
        """Test format_diff with table column having warning severity."""
        result = DiffResult()
        result.target_schema = "public"

        col_diff = ColumnDiff(
            object_name="age",
            column_name="age",
            nullable_diff=(True, False),
            severity=None,  # Will be calculated
        )
        col_diff._calculate_diffs()
        # Force warning severity
        from core.comparison.diff_models import DiffSeverity

        col_diff.severity = DiffSeverity.WARNING

        table_diff = TableDiff(object_name="users", table_name="users", modified_columns=[col_diff])

        schema_diff = SchemaDiff(
            object_name="public", schema_name="public", modified_tables=[table_diff]
        )
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "age" in output
        assert "⚠" in output  # Warning symbol

    def test_format_diff_view_without_definitions(self):
        """Test format_diff with view diff without definitions."""
        result = DiffResult()
        result.target_schema = "public"

        view_diff = ViewDiff(
            object_name="test_view",
            view_name="test_view",
            definition_changed=True,
            expected_definition=None,
            actual_definition=None,
        )

        schema_diff = SchemaDiff(
            object_name="public", schema_name="public", modified_views=[view_diff]
        )
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "test_view" in output
        assert "Definition changed" in output

    def test_format_diff_index_without_changes(self):
        """Test format_diff with index diff but no specific changes."""
        result = DiffResult()
        result.target_schema = "public"

        index_diff = IndexDiff(
            object_name="idx_users",
            index_name="idx_users",
            table_name="users",
            columns_changed=False,
            uniqueness_changed=None,
            type_changed=None,
        )
        # Set columns_changed as tuple for formatter
        index_diff.columns_changed = None

        schema_diff = SchemaDiff(
            object_name="public", schema_name="public", modified_indexes=[index_diff]
        )
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "idx_users" in output

    def test_format_diff_sequence_without_changes(self):
        """Test format_diff with sequence diff but no specific changes."""
        from core.comparison.diff_models import SequenceDiff

        result = DiffResult()
        result.target_schema = "public"

        sequence_diff = SequenceDiff(object_name="seq_users", sequence_name="seq_users")

        schema_diff = SchemaDiff(
            object_name="public", schema_name="public", modified_sequences=[sequence_diff]
        )
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "seq_users" in output

    def test_format_diff_procedure_without_parameters(self):
        """Test format_diff with procedure diff without parameters."""
        result = DiffResult()
        result.target_schema = "public"

        procedure_diff = ProcedureDiff(
            object_name="test_proc",
            procedure_name="test_proc",
            parameters_changed=False,
            definition_changed=True,
        )

        schema_diff = SchemaDiff(
            object_name="public", schema_name="public", modified_procedures=[procedure_diff]
        )
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "test_proc" in output
        assert "Definition changed" in output

    def test_format_diff_with_extra_indexes(self):
        """Test format_diff with extra indexes."""
        result = DiffResult()
        result.target_schema = "public"

        schema_diff = SchemaDiff(
            object_name="public", schema_name="public", extra_indexes=["idx_extra"]
        )
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "Extra Indexes" in output
        assert "idx_extra" in output

    def test_format_diff_with_extra_sequences(self):
        """Test format_diff with extra sequences."""
        result = DiffResult()
        result.target_schema = "public"

        schema_diff = SchemaDiff(
            object_name="public", schema_name="public", extra_sequences=["seq_extra"]
        )
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "Extra Sequences" in output
        assert "seq_extra" in output

    def test_format_diff_with_extra_triggers(self):
        """Test format_diff with extra triggers."""
        result = DiffResult()
        result.target_schema = "public"

        schema_diff = SchemaDiff(
            object_name="public", schema_name="public", extra_triggers=["trg_extra"]
        )
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "Extra Triggers" in output
        assert "trg_extra" in output

    def test_format_diff_with_extra_procedures(self):
        """Test format_diff with extra procedures."""
        result = DiffResult()
        result.target_schema = "public"

        schema_diff = SchemaDiff(
            object_name="public", schema_name="public", extra_procedures=["proc_extra"]
        )
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "Extra Procedures" in output
        assert "proc_extra" in output

    def test_format_diff_with_extra_functions(self):
        """Test format_diff with extra functions."""
        result = DiffResult()
        result.target_schema = "public"

        schema_diff = SchemaDiff(
            object_name="public", schema_name="public", extra_functions=["func_extra"]
        )
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "Extra Functions" in output
        assert "func_extra" in output

    def test_format_diff_with_extra_views(self):
        """Test format_diff with extra views."""
        result = DiffResult()
        result.target_schema = "public"

        schema_diff = SchemaDiff(
            object_name="public", schema_name="public", extra_views=["view_extra"]
        )
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "Extra Views" in output
        assert "view_extra" in output
