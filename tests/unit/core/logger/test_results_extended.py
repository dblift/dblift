"""Extended tests for core.logger.results to improve coverage.

This module tests additional scenarios for the results module, focusing on
uncovered areas like CleanResult helper methods, DiffResult set_schema_diff,
unmanaged objects, and various result types.
"""

from datetime import datetime
from unittest.mock import Mock

import pytest

from core.comparison.diff_models import DiffSeverity, SchemaDiff
from core.logger.results import (
    CleanResult,
    DiffResult,
    ExportSchemaResult,
    GenerateSqlFromDiffResult,
    GenerateUndoScriptResult,
    MigrateResult,
    MigrationInfo,
    OperationResult,
    SnapshotResult,
    UndoResult,
)


@pytest.mark.unit
class TestCleanResultExtended:
    """Extended tests for CleanResult."""

    def test_add_view_dropped(self):
        """Test add_view_dropped helper method."""
        result = CleanResult()
        result.add_view_dropped("view1")
        result.add_view_dropped("view2")

        assert len(result.views_dropped) == 2
        assert "view1" in result.views_dropped
        assert "view2" in result.views_dropped

    def test_add_function_dropped(self):
        """Test add_function_dropped helper method."""
        result = CleanResult()
        result.add_function_dropped("func1")
        result.add_function_dropped("func2")

        assert len(result.functions_dropped) == 2
        assert "func1" in result.functions_dropped
        assert "func2" in result.functions_dropped

    def test_add_procedure_dropped(self):
        """Test add_procedure_dropped helper method."""
        result = CleanResult()
        result.add_procedure_dropped("proc1")
        result.add_procedure_dropped("proc2")

        assert len(result.procedures_dropped) == 2
        assert "proc1" in result.procedures_dropped
        assert "proc2" in result.procedures_dropped

    def test_add_sequence_dropped(self):
        """Test add_sequence_dropped helper method."""
        result = CleanResult()
        result.add_sequence_dropped("seq1")
        result.add_sequence_dropped("seq2")

        assert len(result.sequences_dropped) == 2
        assert "seq1" in result.sequences_dropped
        assert "seq2" in result.sequences_dropped

    def test_add_trigger_dropped(self):
        """Test add_trigger_dropped helper method."""
        result = CleanResult()
        result.add_trigger_dropped("trg1")
        result.add_trigger_dropped("trg2")

        assert len(result.triggers_dropped) == 2
        assert "trg1" in result.triggers_dropped
        assert "trg2" in result.triggers_dropped

    def test_add_cleaned_object_empty_name(self):
        """Test add_cleaned_object with empty name."""
        result = CleanResult()
        result.add_cleaned_object("table", "")

        assert len(result.tables_dropped) == 0

    def test_add_cleaned_object_empty_type(self):
        """Test add_cleaned_object with empty type."""
        result = CleanResult()
        result.add_cleaned_object("", "table1")

        assert len(result.tables_dropped) == 0

    def test_add_cleaned_object_with_schema(self):
        """Test add_cleaned_object with schema."""
        result = CleanResult()
        result.add_cleaned_object("table", "table1", schema="test_schema")

        assert "table1" in result.tables_dropped
        assert result.schema_name == "test_schema"
        details = result.get_object_details("table", "table1")
        assert details["schema"] == "test_schema"

    def test_add_cleaned_object_with_details(self):
        """Test add_cleaned_object with details."""
        result = CleanResult()
        result.add_cleaned_object("table", "table1", details={"key": "value", "number": 123})

        details = result.get_object_details("table", "table1")
        assert details["key"] == "value"
        assert details["number"] == "123"  # Converted to string

    def test_add_cleaned_object_normalizes_name(self):
        """Test add_cleaned_object normalizes name."""
        result = CleanResult()
        result.add_cleaned_object("table", '  "table1"  ')

        assert "table1" in result.tables_dropped

    def test_get_object_details_not_found(self):
        """Test get_object_details for non-existent object."""
        result = CleanResult()
        details = result.get_object_details("table", "nonexistent")

        assert details == {}

    def test_get_object_details_normalized_type(self):
        """Test get_object_details normalizes type."""
        result = CleanResult()
        result.add_cleaned_object("TABLE", "table1", schema="test")

        details = result.get_object_details("  TABLE  ", "table1")
        assert details["schema"] == "test"


@pytest.mark.unit
class TestDiffResultExtended:
    """Extended tests for DiffResult."""

    def test_init(self):
        """Test DiffResult initialization."""
        result = DiffResult()

        assert result.schema_diff is None
        assert result.table_diffs == []
        assert result.comparison_type == "schema"
        assert result.source_type == "script"
        assert result.target_type == "database"
        assert result.total_differences == 0
        assert result.error_count == 0
        assert result.warning_count == 0
        assert result.info_count == 0
        assert result.missing_tables == []
        assert result.has_unmanaged_objects is False

    def test_set_schema_diff_none(self):
        """Test set_schema_diff with None."""
        result = DiffResult()
        result.set_schema_diff(None)

        assert result.success is True
        assert result.total_differences == 0

    def test_set_schema_diff_empty(self):
        """Test set_schema_diff with empty SchemaDiff."""
        result = DiffResult()
        schema_diff = SchemaDiff(object_name="public", schema_name="public")
        result.set_schema_diff(schema_diff)

        assert result.total_differences == 0
        assert result.success is True

    def test_set_schema_diff_with_missing_tables(self):
        """Test set_schema_diff with missing tables."""
        result = DiffResult()
        schema_diff = SchemaDiff(object_name="public", schema_name="public")
        schema_diff.missing_tables = ["table1", "table2"]
        schema_diff.severity = DiffSeverity.ERROR
        schema_diff.get_total_diff_count = Mock(return_value=2)

        result.set_schema_diff(schema_diff)

        assert result.missing_tables == ["table1", "table2"]
        assert result.total_differences == 2
        assert result.error_count == 2
        assert result.success is False
        assert "Found 2 critical differences" in result.error_message

    def test_set_schema_diff_with_warning_severity(self):
        """Test set_schema_diff with WARNING severity."""
        result = DiffResult()
        schema_diff = SchemaDiff(object_name="public", schema_name="public")
        schema_diff.missing_tables = ["table1"]
        schema_diff.severity = DiffSeverity.WARNING
        schema_diff.get_total_diff_count = Mock(return_value=1)

        result.set_schema_diff(schema_diff)

        assert result.total_differences == 1
        assert result.warning_count == 1
        assert result.error_count == 0
        assert result.success is False
        assert "Found 1 schema differences" in result.error_message

    def test_set_schema_diff_with_info_severity(self):
        """Test set_schema_diff with INFO severity."""
        result = DiffResult()
        schema_diff = SchemaDiff(object_name="public", schema_name="public")
        schema_diff.missing_tables = ["table1"]
        schema_diff.severity = DiffSeverity.INFO
        schema_diff.get_total_diff_count = Mock(return_value=1)

        result.set_schema_diff(schema_diff)

        assert result.total_differences == 1
        assert result.info_count == 1
        assert result.error_count == 0
        assert result.warning_count == 0
        assert result.success is False
        assert "Found 1 informational differences" in result.error_message

    def test_set_schema_diff_extracts_all_object_types(self):
        """Test set_schema_diff extracts all object types."""
        result = DiffResult()
        schema_diff = SchemaDiff(object_name="public", schema_name="public")

        # Set up schema_diff with various object types
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
        schema_diff.missing_user_defined_types = ["type1"]
        schema_diff.extra_user_defined_types = ["type2"]
        schema_diff.missing_extensions = ["ext1"]
        schema_diff.extra_extensions = ["ext2"]
        schema_diff.missing_foreign_data_wrappers = ["fdw1"]
        schema_diff.extra_foreign_data_wrappers = ["fdw2"]
        schema_diff.missing_foreign_servers = ["server1"]
        schema_diff.extra_foreign_servers = ["server2"]
        schema_diff.missing_events = ["event1"]
        schema_diff.extra_events = ["event2"]

        schema_diff.severity = DiffSeverity.INFO
        schema_diff.get_total_diff_count = Mock(return_value=0)

        result.set_schema_diff(schema_diff)

        assert result.missing_views == ["view1"]
        assert result.extra_views == ["view2"]
        assert result.missing_indexes == ["idx1"]
        assert result.extra_indexes == ["idx2"]
        assert result.missing_sequences == ["seq1"]
        assert result.extra_sequences == ["seq2"]
        assert result.missing_triggers == ["trg1"]
        assert result.extra_triggers == ["trg2"]
        assert result.missing_procedures == ["proc1"]
        assert result.extra_procedures == ["proc2"]
        assert result.missing_functions == ["func1"]
        assert result.extra_functions == ["func2"]
        assert result.missing_user_defined_types == ["type1"]
        assert result.extra_user_defined_types == ["type2"]
        assert result.missing_extensions == ["ext1"]
        assert result.extra_extensions == ["ext2"]
        assert result.missing_foreign_data_wrappers == ["fdw1"]
        assert result.extra_foreign_data_wrappers == ["fdw2"]
        assert result.missing_foreign_servers == ["server1"]
        assert result.extra_foreign_servers == ["server2"]
        assert result.missing_events == ["event1"]
        assert result.extra_events == ["event2"]

    def test_set_schema_diff_with_modified_objects(self):
        """Test set_schema_diff with modified objects."""
        result = DiffResult()
        schema_diff = SchemaDiff(object_name="public", schema_name="public")

        # Create mock modified objects
        from core.comparison.diff_models import TableDiff, ViewDiff

        table_diff = TableDiff(object_name="users", table_name="users")
        view_diff = ViewDiff(object_name="test_view", view_name="test_view")

        schema_diff.modified_tables = [table_diff]
        schema_diff.modified_views = [view_diff]
        schema_diff.severity = DiffSeverity.ERROR
        schema_diff.get_total_diff_count = Mock(return_value=2)

        result.set_schema_diff(schema_diff)

        assert result.modified_tables == ["users"]
        assert result.modified_views == ["test_view"]

    def test_add_table_diff(self):
        """Test add_table_diff method."""
        result = DiffResult()
        table_diff = Mock()

        result.add_table_diff(table_diff)

        assert len(result.table_diffs) == 1
        assert result.table_diffs[0] == table_diff

    def test_set_unmanaged_objects(self):
        """Test set_unmanaged_objects method."""
        result = DiffResult()
        result.set_unmanaged_objects(
            tables=["table1", "table2"],
            views=["view1"],
            procedures=["proc1"],
            functions=["func1"],
            triggers=["trg1"],
        )

        assert result.unmanaged_tables == ["table1", "table2"]
        assert result.unmanaged_views == ["view1"]
        assert result.unmanaged_procedures == ["proc1"]
        assert result.unmanaged_functions == ["func1"]
        assert result.unmanaged_triggers == ["trg1"]
        assert result.has_unmanaged_objects is True

    def test_set_unmanaged_objects_empty(self):
        """Test set_unmanaged_objects with empty lists."""
        result = DiffResult()
        result.set_unmanaged_objects()

        assert result.unmanaged_tables == []
        assert result.has_unmanaged_objects is False

    def test_set_unmanaged_objects_partial(self):
        """Test set_unmanaged_objects with partial data."""
        result = DiffResult()
        result.set_unmanaged_objects(tables=["table1"])

        assert result.unmanaged_tables == ["table1"]
        assert result.unmanaged_views == []
        assert result.has_unmanaged_objects is True

    def test_get_unmanaged_count(self):
        """Test get_unmanaged_count method."""
        result = DiffResult()
        result.set_unmanaged_objects(
            tables=["table1", "table2"],
            views=["view1"],
            procedures=["proc1"],
            functions=["func1", "func2"],
            triggers=["trg1"],
        )

        count = result.get_unmanaged_count()

        assert count == 7  # 2 + 1 + 1 + 2 + 1

    def test_get_unmanaged_count_empty(self):
        """Test get_unmanaged_count with no unmanaged objects."""
        result = DiffResult()

        count = result.get_unmanaged_count()

        assert count == 0


@pytest.mark.unit
class TestExportSchemaResult:
    """Tests for ExportSchemaResult."""

    def test_init_default(self):
        """Test ExportSchemaResult default initialization."""
        result = ExportSchemaResult()

        assert result.success is True
        assert result.error_message is None
        assert result.output_files == []
        assert result.objects_exported == {}
        assert result.current_schema_version is None
        assert result.filters_applied is None
        assert result.output_options is None

    def test_init_with_params(self):
        """Test ExportSchemaResult initialization with parameters."""
        result = ExportSchemaResult(
            success=False,
            error_message="Export failed",
            output_files=["file1.sql", "file2.sql"],
            objects_exported={"tables": 5, "views": 3},
        )

        assert result.success is False
        assert result.error_message == "Export failed"
        assert result.output_files == ["file1.sql", "file2.sql"]
        assert result.objects_exported == {"tables": 5, "views": 3}


@pytest.mark.unit
class TestSnapshotResult:
    """Tests for SnapshotResult."""

    def test_init_default(self):
        """Test SnapshotResult default initialization."""
        result = SnapshotResult()

        assert result.success is True
        assert result.error_message is None
        assert result.output_file is None
        assert result.snapshot_id is None
        assert result.captured_at is None

    def test_init_with_params(self):
        """Test SnapshotResult initialization with parameters."""
        result = SnapshotResult(
            success=True,
            output_file="snapshot.json",
            snapshot_id="snap123",
            captured_at="2023-01-01T12:00:00",
        )

        assert result.success is True
        assert result.output_file == "snapshot.json"
        assert result.snapshot_id == "snap123"
        assert result.captured_at == "2023-01-01T12:00:00"


@pytest.mark.unit
class TestUndoResult:
    """Tests for UndoResult."""

    def test_init(self):
        """Test UndoResult initialization."""
        result = UndoResult()

        assert result.success is True
        assert result.target_version == ""
        assert result.target_schema == ""
        assert result.schema_name == ""
        assert result.current_schema_version is None
        assert result.undone_migrations == []
        assert result.undone_count == 0

    def test_add_undone_migration(self):
        """Test add_undone_migration method."""
        result = UndoResult()
        migration = MigrationInfo("V1__Test.sql", version="1.0.0")

        result.add_undone_migration(migration)

        assert len(result.undone_migrations) == 1
        assert result.undone_count == 1

    def test_add_undone_migration_multiple(self):
        """Test add_undone_migration with multiple migrations."""
        result = UndoResult()
        migration1 = MigrationInfo("V1__Test.sql", version="1.0.0")
        migration2 = MigrationInfo("V2__Test.sql", version="2.0.0")

        result.add_undone_migration(migration1)
        result.add_undone_migration(migration2)

        assert len(result.undone_migrations) == 2
        assert result.undone_count == 2

    def test_migrations_property(self):
        """Test migrations property."""
        result = UndoResult()
        migration = MigrationInfo("V1__Test.sql", version="1.0.0")
        result.add_undone_migration(migration)

        assert result.migrations == result.undone_migrations


@pytest.mark.unit
class TestGenerateUndoScriptResult:
    """Tests for GenerateUndoScriptResult."""

    def test_init(self):
        """Test GenerateUndoScriptResult initialization."""
        result = GenerateUndoScriptResult()

        assert result.success is True
        assert result.migration_path is None
        assert result.undo_script_path is None
        assert result.overwritten is False
        assert result.statements_generated == 0
        assert result.requires_manual_review is False

    def test_add_warning_with_manual_review(self):
        """Test add_warning sets requires_manual_review."""
        result = GenerateUndoScriptResult()
        result.add_warning("This requires manual review")

        assert result.requires_manual_review is True

    def test_add_warning_with_warning_keyword(self):
        """Test add_warning with 'warning' keyword."""
        result = GenerateUndoScriptResult()
        result.add_warning("Warning: potential issue")

        assert result.requires_manual_review is True

    def test_add_warning_without_keywords(self):
        """Test add_warning without manual review keywords."""
        result = GenerateUndoScriptResult()
        result.add_warning("Simple message")

        assert result.requires_manual_review is False


@pytest.mark.unit
class TestGenerateSqlFromDiffResult:
    """Tests for GenerateSqlFromDiffResult."""

    def test_init(self):
        """Test GenerateSqlFromDiffResult initialization."""
        result = GenerateSqlFromDiffResult()

        assert result.success is True
        assert result.sql_script is None
        assert result.sql_file_path is None
        assert result.statements_generated == 0
        assert result.requires_manual_review is False
        assert result.diff_summary is None

    def test_add_warning_with_manual_review(self):
        """Test add_warning sets requires_manual_review."""
        result = GenerateSqlFromDiffResult()
        result.add_warning("This requires manual review")

        assert result.requires_manual_review is True

    def test_add_warning_with_warning_keyword(self):
        """Test add_warning with 'warning' keyword."""
        result = GenerateSqlFromDiffResult()
        result.add_warning("Warning: potential issue")

        assert result.requires_manual_review is True

    def test_add_warning_without_keywords(self):
        """Test add_warning without manual review keywords."""
        result = GenerateSqlFromDiffResult()
        result.add_warning("Simple message")

        assert result.requires_manual_review is False


@pytest.mark.unit
class TestMigrateResultExtended:
    """Extended tests for MigrateResult."""

    def test_add_migration_with_success_status(self):
        """Test add_migration with 'Success' status (backward compatibility)."""
        result = MigrateResult()
        migration = MigrationInfo("test.sql", status="Success")

        result.add_migration(migration)

        assert result.success is True
        assert len(result.migrations) == 1

    def test_is_successful_with_success_status(self):
        """Test is_successful with 'Success' status."""
        result = MigrateResult()
        migration = MigrationInfo("test.sql", status="Success")
        result.add_migration(migration)

        assert result.is_successful() is True

    def test_migrations_applied_with_success_status(self):
        """Test migrations_applied with 'Success' status."""
        result = MigrateResult()
        migration = MigrationInfo("V1__Test.sql", version="1.0.0", status="Success")
        result.add_migration(migration)

        applied = result.migrations_applied
        assert "1.0.0" in applied

    def test_set_error_with_non_string(self):
        """Test set_error with non-string error_message."""
        result = MigrateResult()
        result.set_error(None)

        assert result.success is False
        assert result.error_message is None


@pytest.mark.unit
class TestOperationResultExtended:
    """Extended tests for OperationResult."""

    def test_init_with_error_and_error_message(self):
        """Test init with both error and error_message (error takes precedence)."""
        result = OperationResult(error="error_param", error_message="error_message_param")

        assert result.error_message == "error_param"

    def test_execution_time_negative_delta(self):
        """Test execution_time with negative delta (shouldn't happen but test edge case)."""
        result = OperationResult()
        result.start_time = datetime(2023, 1, 1, 12, 0, 0)
        result.end_time = datetime(2023, 1, 1, 11, 0, 0)  # Before start_time

        execution_time = result.execution_time()

        # Should return 0 or negative value (implementation dependent)
        assert isinstance(execution_time, int)
