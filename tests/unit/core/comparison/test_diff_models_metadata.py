"""Tests for TableDiff metadata-driven to_dict() and get_diff_count() (Story 15-13)."""

from typing import ClassVar, List

import pytest

from core.comparison.diff_models import ColumnDiff, TableDiff


@pytest.mark.unit
class TestTableDiffMetadata:
    """AC#6 — Tests for ClassVar metadata and data-driven methods."""

    def test_list_str_fields_classvar_exists(self):
        """AC#6.1 — _LIST_STR_FIELDS is a ClassVar in TableDiff.__dict__."""
        assert "_LIST_STR_FIELDS" in TableDiff.__dict__
        assert isinstance(TableDiff._LIST_STR_FIELDS, list)
        assert len(TableDiff._LIST_STR_FIELDS) == 6

    def test_list_obj_fields_classvar_exists(self):
        """AC#6.2 — _LIST_OBJ_FIELDS is a ClassVar in TableDiff.__dict__."""
        assert "_LIST_OBJ_FIELDS" in TableDiff.__dict__
        assert isinstance(TableDiff._LIST_OBJ_FIELDS, list)
        assert len(TableDiff._LIST_OBJ_FIELDS) == 2

    def test_bool_fields_classvar_exists(self):
        """AC#6.3 — _BOOL_FIELDS is a ClassVar in TableDiff.__dict__."""
        assert "_BOOL_FIELDS" in TableDiff.__dict__
        assert isinstance(TableDiff._BOOL_FIELDS, list)
        assert len(TableDiff._BOOL_FIELDS) == 11

    def test_get_diff_count_includes_all_bool_fields(self):
        """AC#6.4 — All _BOOL_FIELDS are in get_diff_count() with value 0 by default."""
        td = TableDiff(object_name="t", table_name="t")
        counts = td.get_diff_count()
        for f in TableDiff._BOOL_FIELDS:
            assert f in counts, f"Missing key: {f}"
            assert counts[f] == 0, f"Expected 0 for {f}, got {counts[f]}"

    def test_get_diff_count_bool_true_returns_1(self):
        """AC#6.5 — compress_changed=True → get_diff_count()['compress_changed'] == 1."""
        td = TableDiff(object_name="t", table_name="t", compress_changed=True)
        counts = td.get_diff_count()
        assert counts["compress_changed"] == 1

    def test_get_diff_count_inherits_changed_counted(self):
        """AC#6.6 — inherits_changed=(True, False) → get_diff_count()['inherits_changed'] == 1."""
        td = TableDiff(object_name="t", table_name="t", inherits_changed=(True, False))
        counts = td.get_diff_count()
        assert counts["inherits_changed"] == 1

    def test_to_dict_data_driven_contains_all_bool_fields(self):
        """AC#6.7 — All _BOOL_FIELDS are present in to_dict()."""
        td = TableDiff(object_name="t", table_name="t")
        data = td.to_dict()
        for f in TableDiff._BOOL_FIELDS:
            assert f in data, f"Missing key in to_dict(): {f}"
            assert data[f] is False, f"Expected False for {f}"

    def test_to_dict_top_level_inherits_changed_boolean(self):
        """inherits_changed must be a top-level bool (not only under differences)."""
        td_none = TableDiff(object_name="t", table_name="t")
        assert td_none.to_dict()["inherits_changed"] is False
        td_set = TableDiff(object_name="t", table_name="t", inherits_changed=(["p"], ["q"]))
        d = td_set.to_dict()
        assert d["inherits_changed"] is True
        assert "inherits" in d["differences"]

    def test_to_dict_backward_compat_list_fields(self):
        """AC#6.8 — missing_columns=['a'] → to_dict()['missing_columns'] == ['a']."""
        td = TableDiff(object_name="t", table_name="t", missing_columns=["a"])
        data = td.to_dict()
        assert data["missing_columns"] == ["a"]

    # --- Review auto-fixes (code review story 15-13) ---

    def test_classvars_not_in_init_and_shared_across_instances(self):
        """M1 — ClassVar fields must NOT be __init__ params and must be shared across instances (PEP 557)."""
        import inspect

        init_params = inspect.signature(TableDiff.__init__).parameters
        assert (
            "_LIST_STR_FIELDS" not in init_params
        ), "_LIST_STR_FIELDS must not be a constructor param"
        assert (
            "_LIST_OBJ_FIELDS" not in init_params
        ), "_LIST_OBJ_FIELDS must not be a constructor param"
        assert "_BOOL_FIELDS" not in init_params, "_BOOL_FIELDS must not be a constructor param"
        # Verify they are truly class-level (same object across instances)
        t1 = TableDiff(object_name="a", table_name="a")
        t2 = TableDiff(object_name="b", table_name="b")
        assert (
            t1._LIST_STR_FIELDS is t2._LIST_STR_FIELDS
        ), "_LIST_STR_FIELDS must be shared (ClassVar)"
        assert t1._BOOL_FIELDS is t2._BOOL_FIELDS, "_BOOL_FIELDS must be shared (ClassVar)"

    def test_get_diff_count_inherits_changed_default_is_zero(self):
        """M3 — inherits_changed=None (default) → get_diff_count()['inherits_changed'] == 0."""
        td = TableDiff(object_name="t", table_name="t")
        counts = td.get_diff_count()
        assert "inherits_changed" in counts, "inherits_changed key missing from get_diff_count()"
        assert counts["inherits_changed"] == 0

    def test_to_dict_backward_compat_obj_fields(self):
        """M2 — modified_columns → to_dict()['modified_columns'] returns list of dicts."""
        col_diff = ColumnDiff(object_name="col1", data_type_diff=("INT", "BIGINT"))
        td = TableDiff(object_name="t", table_name="t", modified_columns=[col_diff])
        data = td.to_dict()
        assert "modified_columns" in data
        assert isinstance(data["modified_columns"], list)
        assert len(data["modified_columns"]) == 1
        assert isinstance(
            data["modified_columns"][0], dict
        ), "modified_columns items must be dicts (via .to_dict())"

    def test_get_diff_count_total_key_count(self):
        """L2 — get_diff_count() must return exactly 20 keys (6 list_str + 2 list_obj + 11 bool + 1 inherits)."""
        td = TableDiff(object_name="t", table_name="t")
        counts = td.get_diff_count()
        expected_count = (
            len(TableDiff._LIST_STR_FIELDS)
            + len(TableDiff._LIST_OBJ_FIELDS)
            + len(TableDiff._BOOL_FIELDS)
            + 1
        )  # +1 for inherits_changed
        assert (
            len(counts) == expected_count
        ), f"Expected {expected_count} keys, got {len(counts)}: {list(counts.keys())}"
