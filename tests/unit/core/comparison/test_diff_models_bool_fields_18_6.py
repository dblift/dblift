"""Tests for TableDiff._BOOL_FIELDS validation (story 18-6).

Validates that _BOOL_FIELDS names match actual dataclass fields on each
instantiation, and invalid names raise AssertionError.
"""

from unittest.mock import patch

import pytest

from core.comparison.diff_models import TableDiff

pytestmark = [pytest.mark.unit]


class TestTableDiffBoolFieldsValidation:
    def test_bool_fields_all_exist_in_dataclass(self):
        """AC#1 — All names in _BOOL_FIELDS are real dataclass fields."""
        diff = TableDiff(object_name="t", table_name="t")
        assert diff is not None

    def test_bool_fields_invalid_name_raises_assertion_error(self):
        """AC#1 — Invalid name in _BOOL_FIELDS raises AssertionError."""
        original = TableDiff._BOOL_FIELDS
        with patch.object(TableDiff, "_BOOL_FIELDS", original + ["nonexistent_field"]):
            with pytest.raises(AssertionError, match="nonexistent_field"):
                TableDiff(object_name="t", table_name="t")

    def test_bool_fields_revalidated_on_each_instance(self):
        """Invalid _BOOL_FIELDS is not masked by a prior successful instantiation."""
        TableDiff(object_name="first", table_name="t")
        with patch.object(TableDiff, "_BOOL_FIELDS", ["nonexistent_field"]):
            with pytest.raises(AssertionError, match="nonexistent_field"):
                TableDiff(object_name="second", table_name="t")

    def test_super_post_init_still_called(self):
        """AC#1.4 — _calculate_diffs() still called via super().__post_init__()."""
        from core.comparison.diff_models import ColumnDiff

        col_diff = ColumnDiff(object_name="col1", column_name="col1")
        col_diff.has_diffs = True
        diff = TableDiff(object_name="t", table_name="t", modified_columns=[col_diff])
        assert diff.has_diffs is True
