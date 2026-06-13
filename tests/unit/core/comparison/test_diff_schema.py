"""Per-module tests for ``core.comparison._diff_schema``.

PR-G9: narrow coverage on the extracted module (PR-G4 split).
"""

import pytest

from core.comparison._diff_base import DiffSeverity
from core.comparison._diff_index import IndexDiff
from core.comparison._diff_routine import FunctionDiff, ProcedureDiff
from core.comparison._diff_schema import SchemaDiff
from core.comparison._diff_simple import (
    DatabaseLinkDiff,
    EventDiff,
    ExtensionDiff,
    PackageDiff,
    SynonymDiff,
    UserDefinedTypeDiff,
)
from core.comparison._diff_table import ColumnDiff, TableDiff
from core.comparison._diff_view import ViewDiff

pytestmark = [pytest.mark.unit]


class TestSchemaDiffNoChange:
    def test_no_diffs(self):
        d = SchemaDiff(object_name="public", schema_name="public")
        assert d.has_diffs is False

    def test_str_no_diffs(self):
        # Covers the previously uncovered line 232: __str__ no-diffs branch.
        d = SchemaDiff(object_name="public", schema_name="public")
        assert str(d) == "Schema 'public': No differences"

    def test_to_dict_no_diffs_includes_schema_name(self):
        d = SchemaDiff(object_name="public", schema_name="public")
        out = d.to_dict()
        assert out["schema_name"] == "public"
        assert out["total_diff_count"] == 0


class TestSchemaDiffSeverity:
    """The ``_calculate_diffs`` method uses three signals to escalate:

    1. ``missing_<critical>`` (tables, views, procedures, functions, packages,
       user_defined_types) ⇒ ERROR
    2. ``extra_user_defined_types`` ⇒ ERROR
    3. Any modified child carrying ERROR ⇒ ERROR
    Otherwise: WARNING.
    """

    def test_missing_table_is_error(self):
        d = SchemaDiff(
            object_name="public",
            schema_name="public",
            missing_tables=["t"],
        )
        assert d.severity == DiffSeverity.ERROR

    def test_missing_view_is_error(self):
        d = SchemaDiff(
            object_name="public",
            schema_name="public",
            missing_views=["v"],
        )
        assert d.severity == DiffSeverity.ERROR

    def test_missing_procedure_is_error(self):
        d = SchemaDiff(
            object_name="public",
            schema_name="public",
            missing_procedures=["p"],
        )
        assert d.severity == DiffSeverity.ERROR

    def test_missing_function_is_error(self):
        d = SchemaDiff(
            object_name="public",
            schema_name="public",
            missing_functions=["f"],
        )
        assert d.severity == DiffSeverity.ERROR

    def test_missing_package_is_error(self):
        d = SchemaDiff(
            object_name="public",
            schema_name="public",
            missing_packages=["pkg"],
        )
        assert d.severity == DiffSeverity.ERROR

    def test_missing_user_defined_type_is_error(self):
        d = SchemaDiff(
            object_name="public",
            schema_name="public",
            missing_user_defined_types=["udt"],
        )
        assert d.severity == DiffSeverity.ERROR

    def test_extra_user_defined_type_is_error(self):
        d = SchemaDiff(
            object_name="public",
            schema_name="public",
            extra_user_defined_types=["udt"],
        )
        assert d.severity == DiffSeverity.ERROR

    def test_modified_table_with_error_escalates(self):
        col = ColumnDiff(
            object_name="x",
            column_name="x",
            data_type_diff=("INTEGER", "VARCHAR"),
        )
        modified_table = TableDiff(object_name="t", table_name="t", modified_columns=[col])
        # Sanity: the table itself is ERROR.
        assert modified_table.severity == DiffSeverity.ERROR

        d = SchemaDiff(
            object_name="public",
            schema_name="public",
            modified_tables=[modified_table],
        )
        assert d.severity == DiffSeverity.ERROR

    def test_modified_view_with_warning_only_is_warning(self):
        modified_view = ViewDiff(object_name="v", view_name="v", definition_changed=True)
        assert modified_view.severity == DiffSeverity.WARNING

        d = SchemaDiff(
            object_name="public",
            schema_name="public",
            modified_views=[modified_view],
        )
        assert d.severity == DiffSeverity.WARNING

    def test_extra_tables_alone_is_warning(self):
        d = SchemaDiff(
            object_name="public",
            schema_name="public",
            extra_tables=["t"],
        )
        assert d.has_diffs is True
        assert d.severity == DiffSeverity.WARNING

    def test_modified_index_warning_is_warning(self):
        idx = IndexDiff(
            object_name="ix",
            index_name="ix",
            table_name="t",
            type_changed=("btree", "hash"),
        )
        d = SchemaDiff(
            object_name="public",
            schema_name="public",
            modified_indexes=[idx],
        )
        assert d.severity == DiffSeverity.WARNING


class TestSchemaDiffStr:
    def test_str_with_diffs_includes_counts(self):
        d = SchemaDiff(
            object_name="public",
            schema_name="public",
            missing_tables=["t1", "t2"],
            extra_views=["v1"],
        )
        s = str(d)
        assert "Schema 'public'" in s
        assert "[error]" in s
        assert "2 missing table(s)" in s
        assert "1 extra view(s)" in s


class TestSchemaDiffGetCounts:
    def test_get_diff_count_includes_every_action_key(self):
        d = SchemaDiff(
            object_name="public",
            schema_name="public",
            missing_tables=["t"],
            extra_views=["v"],
            modified_indexes=[
                IndexDiff(
                    object_name="ix",
                    index_name="ix",
                    table_name="t",
                    type_changed=("btree", "hash"),
                )
            ],
        )
        counts = d.get_diff_count()
        # 17 object types × 3 actions = 51 keys.
        assert len(counts) == 17 * 3
        assert counts["missing_tables"] == 1
        assert counts["extra_views"] == 1
        assert counts["modified_indexes"] == 1
        assert counts["missing_views"] == 0

    def test_total_diff_count_sums_everything(self):
        d = SchemaDiff(
            object_name="public",
            schema_name="public",
            missing_tables=["t"],
            extra_views=["v"],
        )
        assert d.get_total_diff_count() == 2


class TestSchemaDiffToDictIncludesAllChildren:
    """Exercise the to_dict ``modified_<prefix>`` branch for each object type."""

    def test_to_dict_serializes_modified_children(self):
        modified_function = FunctionDiff(
            object_name="f", function_name="f", parameters_changed=True
        )
        modified_proc = ProcedureDiff(object_name="p", procedure_name="p", parameters_changed=True)
        modified_pkg = PackageDiff(object_name="pkg", package_name="pkg", spec_changed=True)
        modified_syn = SynonymDiff(
            object_name="syn",
            synonym_name="syn",
            target_changed=("a", "b"),
        )
        modified_ext = ExtensionDiff(
            object_name="ext",
            extension_name="ext",
            version_changed=("1.0", "2.0"),
        )
        modified_event = EventDiff(
            object_name="evt",
            event_name="evt",
            schedule_changed=("a", "b"),
        )
        modified_udt = UserDefinedTypeDiff(
            object_name="udt",
            type_name="udt",
            base_type_changed=("INT", "BIGINT"),
        )
        modified_dl = DatabaseLinkDiff(
            object_name="dl",
            link_name="dl",
            host_changed=("h1", "h2"),
        )

        d = SchemaDiff(
            object_name="public",
            schema_name="public",
            modified_functions=[modified_function],
            modified_procedures=[modified_proc],
            modified_packages=[modified_pkg],
            modified_synonyms=[modified_syn],
            modified_extensions=[modified_ext],
            modified_events=[modified_event],
            modified_user_defined_types=[modified_udt],
            modified_database_links=[modified_dl],
        )

        out = d.to_dict()
        assert isinstance(out["modified_functions"], list)
        assert isinstance(out["modified_functions"][0], dict)
        # PackageDiff has no bespoke to_dict() — only base fields are emitted.
        assert out["modified_packages"][0]["object_name"] == "pkg"
        assert out["modified_packages"][0]["has_diffs"] is True
        # Every action key is present.
        assert "missing_modules" in out
        assert "extra_linked_servers" in out
        assert "modified_foreign_data_wrappers" in out
        assert out["total_diff_count"] >= 8
