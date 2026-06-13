"""Per-module tests for ``core.comparison._diff_table``.

PR-G9: narrow coverage on the extracted module (PR-G4 split). The previously
uncovered surface is ``ColumnDiff.__str__`` and ``ConstraintDiff.__str__``
no-diffs branches, the ``_render_ddl`` exception swallow, and the various
``TableDiff.__str__`` branches that report counts / boolean state changes.
"""

from unittest.mock import MagicMock

import pytest

from core.comparison._diff_base import DiffSeverity
from core.comparison._diff_table import ColumnDiff, ConstraintDiff, TableDiff

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# ColumnDiff
# ---------------------------------------------------------------------------


class TestColumnDiffStr:
    def test_str_no_diffs(self):
        c = ColumnDiff(object_name="x", column_name="x")
        assert str(c) == "Column 'x': No differences"

    def test_str_with_data_type_diff(self):
        c = ColumnDiff(
            object_name="x",
            column_name="x",
            data_type_diff=("INTEGER", "VARCHAR"),
        )
        s = str(c)
        assert "Column 'x'" in s
        assert "data_type: INTEGER → VARCHAR" in s
        assert "[error]" in s

    def test_no_diffs(self):
        c = ColumnDiff(object_name="x", column_name="x")
        assert c.has_diffs is False
        assert c.severity == DiffSeverity.INFO

    def test_collation_diff_is_warning(self):
        c = ColumnDiff(
            object_name="x",
            column_name="x",
            collation_diff=("utf8", "ascii"),
        )
        assert c.severity == DiffSeverity.WARNING

    def test_to_dict_includes_only_set_diffs(self):
        c = ColumnDiff(
            object_name="x",
            column_name="x",
            data_type_diff=("INTEGER", "VARCHAR"),
        )
        out = c.to_dict()
        assert "data_type" in out["differences"]
        assert "nullable" not in out["differences"]


# ---------------------------------------------------------------------------
# ConstraintDiff
# ---------------------------------------------------------------------------


class TestConstraintDiffStr:
    def test_str_no_diffs(self):
        c = ConstraintDiff(
            object_name="pk_t",
            constraint_name="pk_t",
            constraint_type="PRIMARY KEY",
        )
        assert str(c) == "Constraint 'pk_t' (PRIMARY KEY): No differences"

    def test_check_clause_uses_concise_label(self):
        c = ConstraintDiff(
            object_name="ck_x",
            constraint_name="ck_x",
            constraint_type="CHECK",
            check_clause_diff=("col > 0", "col >= 0"),
        )
        s = str(c)
        assert "check clause differs" in s
        # The exact left/right SQL should NOT be embedded (concise mode).
        assert "col > 0" not in s

    def test_columns_diff_is_error(self):
        c = ConstraintDiff(
            object_name="pk_t",
            constraint_name="pk_t",
            constraint_type="PRIMARY KEY",
            columns_diff=(["a"], ["a", "b"]),
        )
        assert c.severity == DiffSeverity.ERROR

    def test_deferrable_only_is_warning(self):
        c = ConstraintDiff(
            object_name="fk_t",
            constraint_name="fk_t",
            constraint_type="FOREIGN KEY",
            deferrable_diff=(False, True),
        )
        assert c.severity == DiffSeverity.WARNING

    def test_no_diffs(self):
        c = ConstraintDiff(
            object_name="pk_t",
            constraint_name="pk_t",
            constraint_type="PRIMARY KEY",
        )
        assert c.has_diffs is False


# ---------------------------------------------------------------------------
# TableDiff
# ---------------------------------------------------------------------------


class TestTableDiffNoChange:
    def test_no_diffs(self):
        d = TableDiff(object_name="t", table_name="t")
        assert d.has_diffs is False
        assert d.severity == DiffSeverity.INFO

    def test_str_no_diffs(self):
        d = TableDiff(object_name="t", table_name="t")
        # Covers the early-return branch in __str__.
        assert str(d) == "Table 't': No differences"


class TestTableDiffStrBranches:
    """Each branch of TableDiff.__str__ appends exactly one ``parts`` line."""

    def test_missing_columns_reported(self):
        d = TableDiff(object_name="t", table_name="t", missing_columns=["a", "b"])
        s = str(d)
        assert "2 missing column(s)" in s
        assert "[error]" in s  # missing columns => ERROR

    def test_extra_columns_reported(self):
        d = TableDiff(object_name="t", table_name="t", extra_columns=["x"])
        assert "1 extra column(s)" in str(d)

    def test_modified_columns_reported(self):
        col = ColumnDiff(
            object_name="x",
            column_name="x",
            nullable_diff=(True, False),
        )
        d = TableDiff(object_name="t", table_name="t", modified_columns=[col])
        assert "1 modified column(s)" in str(d)

    def test_missing_constraints_reported(self):
        d = TableDiff(
            object_name="t",
            table_name="t",
            missing_constraints=["pk_t"],
        )
        assert "1 missing constraint(s)" in str(d)

    def test_extra_constraints_reported(self):
        d = TableDiff(
            object_name="t",
            table_name="t",
            extra_constraints=["uq_t"],
        )
        assert "1 extra constraint(s)" in str(d)

    def test_modified_constraints_reported(self):
        con = ConstraintDiff(
            object_name="ck_x",
            constraint_name="ck_x",
            constraint_type="CHECK",
            check_clause_diff=("a", "b"),
        )
        d = TableDiff(
            object_name="t",
            table_name="t",
            modified_constraints=[con],
        )
        assert "1 modified constraint(s)" in str(d)

    def test_missing_indexes_reported(self):
        d = TableDiff(
            object_name="t",
            table_name="t",
            missing_indexes=["ix_t"],
        )
        s = str(d)
        assert "1 missing index(es)" in s
        # Only indexes → INFO severity.
        assert "[info]" in s

    def test_extra_indexes_reported(self):
        d = TableDiff(
            object_name="t",
            table_name="t",
            extra_indexes=["ix_t"],
        )
        assert "1 extra index(es)" in str(d)

    def test_temporary_changed_reported(self):
        d = TableDiff(object_name="t", table_name="t", temporary_changed=True)
        s = str(d)
        assert "temporary property changed" in s
        # Bool-property-only ⇒ WARNING.
        assert "[warning]" in s

    def test_filegroup_changed_reported(self):
        d = TableDiff(object_name="t", table_name="t", filegroup_changed=True)
        assert "filegroup changed" in str(d)

    def test_memory_optimized_changed_reported(self):
        d = TableDiff(
            object_name="t",
            table_name="t",
            memory_optimized_changed=True,
        )
        assert "memory-optimized property changed" in str(d)

    def test_system_versioned_changed_reported(self):
        d = TableDiff(
            object_name="t",
            table_name="t",
            system_versioned_changed=True,
        )
        assert "system-versioned property changed" in str(d)

    def test_history_table_changed_reported(self):
        d = TableDiff(
            object_name="t",
            table_name="t",
            history_table_changed=True,
        )
        assert "history table changed" in str(d)

    def test_inherits_changed_reported(self):
        d = TableDiff(
            object_name="t",
            table_name="t",
            inherits_changed=(["a"], ["a", "b"]),
        )
        assert "inherits changed" in str(d)


class TestTableDiffSeverityCascade:
    """Cover the severity decision tree once explicitly."""

    def test_modified_column_error_escalates_table_severity(self):
        col = ColumnDiff(
            object_name="x",
            column_name="x",
            data_type_diff=("INTEGER", "VARCHAR"),
        )
        d = TableDiff(object_name="t", table_name="t", modified_columns=[col])
        assert d.severity == DiffSeverity.ERROR

    def test_modified_constraint_error_escalates_table_severity(self):
        con = ConstraintDiff(
            object_name="ck_x",
            constraint_name="ck_x",
            constraint_type="CHECK",
            columns_diff=(["a"], ["b"]),
        )
        d = TableDiff(object_name="t", table_name="t", modified_constraints=[con])
        assert d.severity == DiffSeverity.ERROR

    def test_only_extra_columns_is_warning(self):
        d = TableDiff(object_name="t", table_name="t", extra_columns=["x"])
        assert d.severity == DiffSeverity.WARNING

    def test_only_bool_field_is_warning(self):
        d = TableDiff(object_name="t", table_name="t", filegroup_changed=True)
        assert d.severity == DiffSeverity.WARNING

    def test_only_indexes_is_info(self):
        d = TableDiff(
            object_name="t",
            table_name="t",
            extra_indexes=["ix_t"],
        )
        assert d.severity == DiffSeverity.INFO

    def test_only_inherits_changed_is_info(self):
        # inherits_changed is the only Optional[tuple] in TableDiff and
        # contributes via ``is not None``. It is not a list_str_field or
        # bool_field, so without any other markers it lands in the
        # "index-only / fall-through" branch (INFO).
        d = TableDiff(
            object_name="t",
            table_name="t",
            inherits_changed=(["a"], ["a", "b"]),
        )
        assert d.severity == DiffSeverity.INFO


class TestTableDiffBoolFieldsValidation:
    def test_bool_fields_with_invalid_entry_raises(self, monkeypatch):
        # Cover the AssertionError raised in __post_init__ when
        # _BOOL_FIELDS references a non-existent field.
        monkeypatch.setattr(
            TableDiff,
            "_BOOL_FIELDS",
            TableDiff._BOOL_FIELDS + ["does_not_exist"],
        )
        with pytest.raises(AssertionError) as ei:
            TableDiff(object_name="t", table_name="t")
        assert "does_not_exist" in str(ei.value)


class TestTableDiffGetDiffCount:
    def test_diff_count_counts_lists_and_bools(self):
        d = TableDiff(
            object_name="t",
            table_name="t",
            missing_columns=["a", "b"],
            extra_indexes=["ix"],
            filegroup_changed=True,
            inherits_changed=(["a"], ["a", "b"]),
        )
        counts = d.get_diff_count()
        assert counts["missing_columns"] == 2
        assert counts["extra_indexes"] == 1
        assert counts["filegroup_changed"] == 1
        assert counts["inherits_changed"] == 1

    def test_diff_count_inherits_none(self):
        d = TableDiff(object_name="t", table_name="t")
        counts = d.get_diff_count()
        assert counts["inherits_changed"] == 0


class TestTableDiffResolveDialect:
    def test_resolve_dialect_picks_first_non_empty(self):
        expected = MagicMock()
        expected.dialect = ""
        actual = MagicMock()
        actual.dialect = "postgresql"
        assert TableDiff._resolve_dialect(expected, actual) == "postgresql"

    def test_resolve_dialect_handles_none(self):
        actual = MagicMock()
        actual.dialect = "oracle"
        assert TableDiff._resolve_dialect(None, actual) == "oracle"

    def test_resolve_dialect_no_signal_returns_empty(self):
        # All-None and missing-dialect inputs fall through to "".
        assert TableDiff._resolve_dialect(None, None) == ""
        empty = MagicMock(spec=[])  # no ``dialect`` attribute
        assert TableDiff._resolve_dialect(empty) == ""


class TestTableDiffRenderDdl:
    def test_render_ddl_none_returns_none(self):
        # Static method — no instance needed.
        assert TableDiff._render_ddl(None, "postgresql") is None

    def test_render_ddl_swallows_exception(self, monkeypatch):
        # Replace the import target so ``render_table_ddl`` raises.
        import core.sql_generator.table_ddl_render as ddl_mod

        def boom(*a, **k):
            raise RuntimeError("simulated render failure")

        monkeypatch.setattr(ddl_mod, "render_table_ddl", boom)
        # Anything truthy passes the ``if table is None`` guard. The
        # render call inside raises, the ``except Exception`` swallows.
        table_obj = MagicMock()
        assert TableDiff._render_ddl(table_obj, "postgresql") is None


class TestTableDiffToDict:
    def test_inherits_changed_serializes_to_differences(self):
        d = TableDiff(
            object_name="t",
            table_name="t",
            inherits_changed=(["a"], ["a", "b"]),
        )
        out = d.to_dict()
        assert out["differences"]["inherits"] == {
            "expected": ["a"],
            "actual": ["a", "b"],
        }
        # Top-level boolean for API consumers.
        assert out["inherits_changed"] is True

    def test_no_inherits_changed_omits_differences_key(self):
        d = TableDiff(object_name="t", table_name="t")
        out = d.to_dict()
        assert out["differences"] == {}
        assert out["inherits_changed"] is False
