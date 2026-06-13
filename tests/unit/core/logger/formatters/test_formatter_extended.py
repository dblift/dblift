"""Extended tests for OutputFormatter to further improve coverage.

This module tests additional scenarios for OutputFormatter, focusing on
uncovered areas like user-defined types, extensions, foreign data wrappers,
foreign servers, events, and edge cases.
"""

from datetime import datetime
from unittest.mock import Mock, patch

import pytest

from core.comparison.diff_models import (
    EventDiff,
    ExtensionDiff,
    ForeignDataWrapperDiff,
    ForeignServerDiff,
    SchemaDiff,
    UserDefinedTypeDiff,
)
from core.logger.formatters.formatter import OutputFormatter
from core.logger.results import DiffResult


@pytest.mark.unit
class TestOutputFormatterExtended:
    """Extended tests for OutputFormatter."""

    def setup_method(self):
        """Set up test fixtures."""
        self.formatter = OutputFormatter()

    def test_format_diff_with_missing_user_defined_types(self):
        """Test format_diff with missing user-defined types."""
        result = DiffResult()
        result.target_schema = "public"

        schema_diff = SchemaDiff(
            object_name="public", schema_name="public", missing_user_defined_types=["status_type"]
        )
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "Missing User-Defined Types" in output
        assert "status_type" in output

    def test_format_diff_with_extra_user_defined_types(self):
        """Test format_diff with extra user-defined types."""
        result = DiffResult()
        result.target_schema = "public"

        schema_diff = SchemaDiff(
            object_name="public", schema_name="public", extra_user_defined_types=["old_type"]
        )
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "Extra User-Defined Types" in output
        assert "old_type" in output

    def test_format_diff_with_modified_user_defined_types(self):
        """Test format_diff with modified user-defined types."""
        result = DiffResult()
        result.target_schema = "public"

        udt_diff = UserDefinedTypeDiff(
            object_name="status_type",
            type_name="status_type",
            type_category_changed=("ENUM", "DOMAIN"),
            base_type_changed=("VARCHAR(10)", "INTEGER"),
            attributes_changed=True,
            expected_attributes={"field1": "VARCHAR"},
            actual_attributes={"field1": "TEXT"},
            enum_values_changed=True,
            expected_enum_values=["active", "inactive"],
            actual_enum_values=["active", "inactive", "pending"],
            definition_changed=True,
            expected_base_type="VARCHAR(10)",
            actual_base_type="INTEGER",
            severity=None,  # Will be calculated
        )
        udt_diff._calculate_diffs()

        schema_diff = SchemaDiff(
            object_name="public", schema_name="public", modified_user_defined_types=[udt_diff]
        )
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "Modified User-Defined Types" in output
        assert "status_type" in output
        assert "Category" in output
        assert "Base Type" in output
        assert "Attributes changed" in output
        assert "Enum values changed" in output
        assert "Definition changed" in output

    def test_format_diff_with_missing_extensions(self):
        """Test format_diff with missing extensions."""
        result = DiffResult()
        result.target_schema = "public"

        schema_diff = SchemaDiff(
            object_name="public", schema_name="public", missing_extensions=["pg_trgm"]
        )
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "Missing Extensions" in output
        assert "pg_trgm" in output

    def test_format_diff_with_extra_extensions(self):
        """Test format_diff with extra extensions."""
        result = DiffResult()
        result.target_schema = "public"

        schema_diff = SchemaDiff(
            object_name="public", schema_name="public", extra_extensions=["unwanted_ext"]
        )
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "Extra Extensions" in output
        assert "unwanted_ext" in output

    def test_format_diff_with_modified_extensions(self):
        """Test format_diff with modified extensions."""
        result = DiffResult()
        result.target_schema = "public"

        ext_diff = ExtensionDiff(
            object_name="pg_trgm",
            extension_name="pg_trgm",
            version_changed=("1.0", "1.1"),
            schema_changed=("public", "extensions"),
            severity=None,  # Will be calculated
        )
        ext_diff._calculate_diffs()

        schema_diff = SchemaDiff(
            object_name="public", schema_name="public", modified_extensions=[ext_diff]
        )
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "Modified Extensions" in output
        assert "pg_trgm" in output
        assert "Version" in output
        assert "Schema" in output

    def test_format_diff_with_extension_error_severity(self):
        """Test format_diff with extension having error severity."""
        result = DiffResult()
        result.target_schema = "public"

        ext_diff = ExtensionDiff(
            object_name="pg_trgm", extension_name="pg_trgm", version_changed=("1.0", "1.1")
        )
        ext_diff.severity = None  # Will be calculated
        ext_diff._calculate_diffs()
        # Force error severity for test
        from core.comparison.diff_models import DiffSeverity

        ext_diff.severity = DiffSeverity.ERROR

        schema_diff = SchemaDiff(
            object_name="public", schema_name="public", modified_extensions=[ext_diff]
        )
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "Modified Extensions" in output
        assert "ERROR" in output
        assert "✗" in output

    def test_format_diff_with_missing_foreign_data_wrappers(self):
        """Test format_diff with missing foreign data wrappers."""
        result = DiffResult()
        result.target_schema = "public"

        schema_diff = SchemaDiff(
            object_name="public",
            schema_name="public",
            missing_foreign_data_wrappers=["postgres_fdw"],
        )
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "Missing Foreign Data Wrappers" in output
        assert "postgres_fdw" in output

    def test_format_diff_with_extra_foreign_data_wrappers(self):
        """Test format_diff with extra foreign data wrappers."""
        result = DiffResult()
        result.target_schema = "public"

        schema_diff = SchemaDiff(
            object_name="public", schema_name="public", extra_foreign_data_wrappers=["old_fdw"]
        )
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "Extra Foreign Data Wrappers" in output
        assert "old_fdw" in output

    def test_format_diff_with_modified_foreign_data_wrappers(self):
        """Test format_diff with modified foreign data wrappers."""
        result = DiffResult()
        result.target_schema = "public"

        fdw_diff = ForeignDataWrapperDiff(
            object_name="postgres_fdw",
            fdw_name="postgres_fdw",
            handler_changed=("old_handler", "new_handler"),
            validator_changed=("old_validator", "new_validator"),
            options_changed=({"option1": "value1"}, {"option1": "value2"}),
            severity=None,  # Will be calculated
        )
        fdw_diff._calculate_diffs()
        # Add wrapper_name attribute for compatibility with results.py
        fdw_diff.wrapper_name = fdw_diff.fdw_name

        schema_diff = SchemaDiff(
            object_name="public", schema_name="public", modified_foreign_data_wrappers=[fdw_diff]
        )
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "Modified Foreign Data Wrappers" in output
        # The formatter uses wrapper_name from result, but we set fdw_name
        # Check that the diff is included
        assert "Handler" in output or "postgres_fdw" in output
        assert "Validator" in output
        assert "Options" in output

    def test_format_diff_with_missing_foreign_servers(self):
        """Test format_diff with missing foreign servers."""
        result = DiffResult()
        result.target_schema = "public"

        schema_diff = SchemaDiff(
            object_name="public", schema_name="public", missing_foreign_servers=["remote_server"]
        )
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "Missing Foreign Servers" in output
        assert "remote_server" in output

    def test_format_diff_with_extra_foreign_servers(self):
        """Test format_diff with extra foreign servers."""
        result = DiffResult()
        result.target_schema = "public"

        schema_diff = SchemaDiff(
            object_name="public", schema_name="public", extra_foreign_servers=["old_server"]
        )
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "Extra Foreign Servers" in output
        assert "old_server" in output

    def test_format_diff_with_modified_foreign_servers(self):
        """Test format_diff with modified foreign servers."""
        result = DiffResult()
        result.target_schema = "public"

        server_diff = ForeignServerDiff(
            object_name="remote_server",
            server_name="remote_server",
            fdw_changed=("postgres_fdw", "mysql_fdw"),
            host_changed=("localhost", "remote.host.com"),
            port_changed=(5432, 3306),
            dbname_changed=("postgres", "mysql_db"),
            options_changed=({"option1": "value1"}, {"option1": "value2"}),
            severity=None,  # Will be calculated
        )
        server_diff._calculate_diffs()

        schema_diff = SchemaDiff(
            object_name="public", schema_name="public", modified_foreign_servers=[server_diff]
        )
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "Modified Foreign Servers" in output
        assert "remote_server" in output
        assert "FDW" in output
        assert "Host" in output
        assert "Port" in output
        assert "Database" in output
        assert "Options" in output

    def test_format_diff_with_missing_events(self):
        """Test format_diff with missing events."""
        result = DiffResult()
        result.target_schema = "public"

        schema_diff = SchemaDiff(
            object_name="public", schema_name="public", missing_events=["cleanup_event"]
        )
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "Missing Events" in output
        assert "cleanup_event" in output

    def test_format_diff_with_extra_events(self):
        """Test format_diff with extra events."""
        result = DiffResult()
        result.target_schema = "public"

        schema_diff = SchemaDiff(
            object_name="public", schema_name="public", extra_events=["old_event"]
        )
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "Extra Events" in output
        assert "old_event" in output

    def test_format_diff_with_modified_events(self):
        """Test format_diff with modified events."""
        result = DiffResult()
        result.target_schema = "public"

        event_diff = EventDiff(
            object_name="cleanup_event",
            event_name="cleanup_event",
            definition_changed=True,
            schedule_changed=("EVERY 1 DAY", "EVERY 1 HOUR"),
            enabled_changed=(True, False),
            severity=None,  # Will be calculated
        )
        event_diff._calculate_diffs()

        schema_diff = SchemaDiff(
            object_name="public", schema_name="public", modified_events=[event_diff]
        )
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "Modified Events" in output
        assert "cleanup_event" in output
        assert "Definition changed" in output
        assert "Schedule" in output
        assert "Enabled" in output

    def test_format_diff_with_warnings(self):
        """Test format_diff with warnings."""
        result = DiffResult()
        result.target_schema = "public"
        result.warnings = ["Warning 1", "Warning 2"]

        schema_diff = SchemaDiff(object_name="public", schema_name="public")
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "Warnings:" in output
        assert "Warning 1" in output
        assert "Warning 2" in output

    def test_format_diff_table_with_extra_constraints(self):
        """Test format_diff with table having extra constraints."""
        from core.comparison.diff_models import TableDiff

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

    def test_format_diff_table_with_missing_indexes(self):
        """Test format_diff with table having missing indexes."""
        from core.comparison.diff_models import TableDiff

        result = DiffResult()
        result.target_schema = "public"

        table_diff = TableDiff(
            object_name="users", table_name="users", missing_indexes=["idx_email"]
        )

        schema_diff = SchemaDiff(
            object_name="public", schema_name="public", modified_tables=[table_diff]
        )
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "users" in output
        assert "Missing Indexes" in output or "idx_email" in output

    def test_format_diff_table_with_extra_indexes(self):
        """Test format_diff with table having extra indexes."""
        from core.comparison.diff_models import TableDiff

        result = DiffResult()
        result.target_schema = "public"

        table_diff = TableDiff(object_name="users", table_name="users", extra_indexes=["idx_extra"])

        schema_diff = SchemaDiff(
            object_name="public", schema_name="public", modified_tables=[table_diff]
        )
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "users" in output
        assert "Extra Indexes" in output or "idx_extra" in output

    def test_format_diff_table_with_identity_diff(self):
        """Test format_diff with table column having identity diff."""
        from core.comparison.diff_models import ColumnDiff, TableDiff

        result = DiffResult()
        result.target_schema = "public"

        col_diff = ColumnDiff(object_name="id", column_name="id", identity_diff=(True, False))

        table_diff = TableDiff(object_name="users", table_name="users", modified_columns=[col_diff])

        schema_diff = SchemaDiff(
            object_name="public", schema_name="public", modified_tables=[table_diff]
        )
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "id" in output
        assert "identity" in output

    def test_format_diff_table_with_computed_diff(self):
        """Test format_diff with table column having computed diff."""
        from core.comparison.diff_models import ColumnDiff, TableDiff

        result = DiffResult()
        result.target_schema = "public"

        col_diff = ColumnDiff(
            object_name="full_name", column_name="full_name", computed_diff=(True, False)
        )

        table_diff = TableDiff(object_name="users", table_name="users", modified_columns=[col_diff])

        schema_diff = SchemaDiff(
            object_name="public", schema_name="public", modified_tables=[table_diff]
        )
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "full_name" in output
        assert "computed" in output

    def test_format_diff_view_with_long_definition(self):
        """Test format_diff with view having long definition (truncated)."""
        from core.comparison.diff_models import ViewDiff

        result = DiffResult()
        result.target_schema = "public"

        long_definition = "SELECT " + ", ".join([f"col{i}" for i in range(200)])

        view_diff = ViewDiff(
            object_name="long_view",
            view_name="long_view",
            definition_changed=True,
            expected_definition=long_definition,
            actual_definition=long_definition + ", extra_col",
        )

        schema_diff = SchemaDiff(
            object_name="public", schema_name="public", modified_views=[view_diff]
        )
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "long_view" in output
        assert "Definition changed" in output
        # Should truncate long definitions
        assert "..." in output or len(output) < len(long_definition) * 2

    def test_format_diff_trigger_with_list_events(self):
        """Test format_diff with trigger having list events."""
        from core.comparison.diff_models import TriggerDiff

        result = DiffResult()
        result.target_schema = "public"

        trigger_diff = TriggerDiff(
            object_name="trg_users",
            trigger_name="trg_users",
            table_name="users",
            event_changed=(["INSERT", "UPDATE"], ["INSERT", "UPDATE", "DELETE"]),
        )

        schema_diff = SchemaDiff(
            object_name="public", schema_name="public", modified_triggers=[trigger_diff]
        )
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "trg_users" in output
        assert "Event changed" in output
        assert "INSERT" in output

    def test_format_diff_with_no_schema_name(self):
        """Test format_diff when schema_diff has no schema_name."""
        result = DiffResult()
        result.target_schema = None

        schema_diff = SchemaDiff(object_name="unknown", schema_name="")
        result.set_schema_diff(schema_diff)

        output = self.formatter.format_diff(result)

        assert "Schema Comparison Report" in output
        assert "unknown" in output or "Schema:" in output

    def test_format_migrate_with_warnings(self):
        """Test format_migrate with warnings."""
        from core.logger.results import MigrateResult

        result = MigrateResult()
        result.success = True
        result.target_schema = "test_schema"
        result.warnings = ["Migration warning"]
        result.start_time = datetime.fromtimestamp(1000)
        result.end_time = datetime.fromtimestamp(1500)

        output = self.formatter.format_migrate(result)

        assert "Warnings:" in output
        assert "Migration warning" in output

    def test_format_clean_with_warnings(self):
        """Test format_clean with warnings."""
        from core.logger.results import CleanResult

        result = CleanResult()
        result.success = True
        result.schema_name = "test_schema"
        result.warnings = ["Clean warning"]
        result.start_time = datetime.fromtimestamp(1000)
        result.end_time = datetime.fromtimestamp(1500)

        output = self.formatter.format_clean(result)

        assert "Warnings:" in output
        assert "Clean warning" in output

    def test_format_info_with_warnings(self):
        """Test format_info with warnings."""
        from core.logger.results import InfoResult

        result = InfoResult()
        result.success = True
        result.schema_name = "test_schema"
        result.warnings = ["Info warning"]
        result.start_time = datetime.fromtimestamp(1000)
        result.end_time = datetime.fromtimestamp(1500)

        output = self.formatter.format_info(result)

        assert "Warnings:" in output
        assert "Info warning" in output

    def test_format_validate_with_warnings(self):
        """Test format_validate with warnings."""
        from core.logger.results import ValidateResult

        result = ValidateResult()
        result.success = True
        result.warnings = ["Validation warning"]
        result.start_time = datetime.fromtimestamp(1000)
        result.end_time = datetime.fromtimestamp(1500)

        output = self.formatter.format_validate(result)

        assert "Warnings:" in output
        assert "Validation warning" in output

    def test_format_baseline_with_warnings(self):
        """Test format_baseline with warnings."""
        from core.logger.results import BaselineResult

        result = BaselineResult()
        result.success = True
        result.schema_name = "test_schema"
        result.baseline_version = "1.0.0"
        result.warnings = ["Baseline warning"]
        result.start_time = datetime.fromtimestamp(1000)
        result.end_time = datetime.fromtimestamp(1500)

        output = self.formatter.format_baseline(result)

        assert "Warnings:" in output
        assert "Baseline warning" in output

    def test_format_repair_with_warnings(self):
        """Test format_repair with warnings."""
        from core.logger.results import RepairResult

        result = RepairResult()
        result.success = True
        result.warnings = ["Repair warning"]
        result.start_time = datetime.fromtimestamp(1000)
        result.end_time = datetime.fromtimestamp(1500)

        output = self.formatter.format_repair(result)

        assert "Warnings:" in output
        assert "Repair warning" in output

    def test_format_with_unknown_result_type(self):
        """Test format method with unknown result type."""
        from core.logger.results import OperationResult

        result = OperationResult()
        result.success = True
        result.start_time = datetime.fromtimestamp(1000)
        result.end_time = datetime.fromtimestamp(1500)

        output = self.formatter.format(result, "text")

        assert "Operation Report" in output
        assert "Status: SUCCESS" in output

    def test_format_sets_target_schema_when_none(self):
        """Test format method sets target_schema when None."""
        from core.logger.results import MigrateResult

        result = MigrateResult()
        result.success = True
        result.target_schema = None
        result.start_time = datetime.fromtimestamp(1000)
        result.end_time = datetime.fromtimestamp(1500)

        output = self.formatter.format(result, "text", schema_name="override_schema")

        assert "Schema: override_schema" in output

    def test_format_does_not_override_existing_target_schema(self):
        """Test format method does not override existing target_schema."""
        from core.logger.results import MigrateResult

        result = MigrateResult()
        result.success = True
        result.target_schema = "existing_schema"
        result.start_time = datetime.fromtimestamp(1000)
        result.end_time = datetime.fromtimestamp(1500)

        output = self.formatter.format(result, "text", schema_name="override_schema")

        # Should use existing target_schema, not override
        assert "Schema: existing_schema" in output
