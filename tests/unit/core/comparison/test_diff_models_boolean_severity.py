"""Story 16-10 — Tests for boolean property severity in TableDiff._calculate_diffs()."""

import pytest

from core.comparison.diff_models import DiffSeverity, TableDiff

pytestmark = [pytest.mark.unit]


class TestTableDiffBooleanSeverity:
    """AC#2: boolean property changes → DiffSeverity.WARNING."""

    @pytest.mark.parametrize(
        "field",
        [
            "temporary_changed",
            "filegroup_changed",
            "memory_optimized_changed",
            "system_versioned_changed",
            "history_table_changed",
            "partition_method_changed",
            "partition_columns_changed",
            "compress_changed",
            "compress_type_changed",
            "logged_changed",
            "organize_by_changed",
        ],
    )
    def test_single_boolean_field_triggers_warning(self, field):
        """Each boolean property alone → WARNING."""
        diff = TableDiff(object_name="t", table_name="t", **{field: True})
        assert diff.has_diffs is True
        assert (
            diff.severity == DiffSeverity.WARNING
        ), f"{field}=True should produce WARNING, got {diff.severity}"

    def test_boolean_and_missing_column_produces_error(self):
        """AC#3 — ERROR takes precedence over boolean WARNING."""
        diff = TableDiff(
            object_name="t",
            table_name="t",
            missing_columns=["col1"],
            filegroup_changed=True,
        )
        assert diff.severity == DiffSeverity.ERROR

    def test_boolean_and_missing_constraint_produces_error(self):
        """AC#3 — ERROR from missing_constraints takes precedence over boolean WARNING."""
        diff = TableDiff(
            object_name="t",
            table_name="t",
            missing_constraints=["pk1"],
            compress_changed=True,
        )
        assert diff.severity == DiffSeverity.ERROR

    def test_index_only_produces_info(self):
        """AC#4 — indexes alone → INFO."""
        diff = TableDiff(
            object_name="t",
            table_name="t",
            missing_indexes=["idx1"],
        )
        assert diff.has_diffs is True
        assert diff.severity == DiffSeverity.INFO

    def test_extra_indexes_only_produces_info(self):
        """AC#4 — extra indexes alone → INFO."""
        diff = TableDiff(
            object_name="t",
            table_name="t",
            extra_indexes=["idx1"],
        )
        assert diff.has_diffs is True
        assert diff.severity == DiffSeverity.INFO

    def test_no_diffs_no_severity_change(self):
        """No diffs → has_diffs=False, severity stays at default INFO."""
        diff = TableDiff(object_name="t", table_name="t")
        assert diff.has_diffs is False
        assert diff.severity == DiffSeverity.INFO

    def test_multiple_booleans_triggers_warning(self):
        """Multiple boolean fields together → WARNING."""
        diff = TableDiff(
            object_name="t",
            table_name="t",
            filegroup_changed=True,
            compress_changed=True,
            logged_changed=True,
        )
        assert diff.has_diffs is True
        assert diff.severity == DiffSeverity.WARNING

    def test_boolean_and_extra_column_produces_warning(self):
        """Extra columns + boolean → WARNING (extra_columns branch fires first)."""
        diff = TableDiff(
            object_name="t",
            table_name="t",
            extra_columns=["col1"],
            temporary_changed=True,
        )
        assert diff.has_diffs is True
        assert diff.severity == DiffSeverity.WARNING

    def test_boolean_with_extra_indexes_produces_warning(self):
        """Boolean + extra indexes → WARNING (boolean branch fires, not else/index branch)."""
        diff = TableDiff(
            object_name="t",
            table_name="t",
            extra_indexes=["idx1"],
            filegroup_changed=True,
        )
        assert diff.has_diffs is True
        assert diff.severity == DiffSeverity.WARNING

    def test_inherits_changed_only_produces_info(self):
        """inherits_changed alone → has_diffs=True but severity stays INFO (else branch)."""
        diff = TableDiff(
            object_name="t",
            table_name="t",
            inherits_changed=("schema_a", "schema_b"),
        )
        assert diff.has_diffs is True
        assert diff.severity == DiffSeverity.INFO
