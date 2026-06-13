"""Per-module tests for ``core.comparison._diff_index``.

PR-G9: narrow coverage on the extracted module (PR-G4 split).
"""

import pytest

from core.comparison._diff_base import DiffSeverity
from core.comparison._diff_index import IndexDiff

pytestmark = [pytest.mark.unit]


class TestIndexDiffNoChange:
    def test_no_diffs(self):
        d = IndexDiff(object_name="ix", index_name="ix", table_name="t")
        assert d.has_diffs is False
        assert d.severity == DiffSeverity.INFO
        assert d.object_type == "index"


class TestIndexDiffSeverityBranches:
    def test_columns_changed_is_error(self):
        d = IndexDiff(
            object_name="ix",
            index_name="ix",
            table_name="t",
            columns_changed=True,
        )
        assert d.has_diffs is True
        assert d.severity == DiffSeverity.ERROR

    def test_uniqueness_changed_is_error(self):
        d = IndexDiff(
            object_name="ix",
            index_name="ix",
            table_name="t",
            uniqueness_changed=(False, True),
        )
        assert d.severity == DiffSeverity.ERROR

    def test_type_changed_is_warning(self):
        d = IndexDiff(
            object_name="ix",
            index_name="ix",
            table_name="t",
            type_changed=("btree", "hash"),
        )
        assert d.severity == DiffSeverity.WARNING

    def test_online_changed_is_warning(self):
        d = IndexDiff(
            object_name="ix",
            index_name="ix",
            table_name="t",
            online_changed=(False, True),
        )
        assert d.severity == DiffSeverity.WARNING

    def test_concurrently_changed_is_warning(self):
        d = IndexDiff(
            object_name="ix",
            index_name="ix",
            table_name="t",
            concurrently_changed=(False, True),
        )
        assert d.severity == DiffSeverity.WARNING

    def test_tablespace_changed_is_warning(self):
        d = IndexDiff(
            object_name="ix",
            index_name="ix",
            table_name="t",
            tablespace_changed=("USERS", "DATA"),
        )
        assert d.severity == DiffSeverity.WARNING

    def test_include_columns_changed_is_warning(self):
        d = IndexDiff(
            object_name="ix",
            index_name="ix",
            table_name="t",
            include_columns_changed=([], ["name"]),
        )
        assert d.severity == DiffSeverity.WARNING

    def test_columns_changed_dominates_type_changed(self):
        d = IndexDiff(
            object_name="ix",
            index_name="ix",
            table_name="t",
            columns_changed=True,
            type_changed=("btree", "hash"),
        )
        assert d.severity == DiffSeverity.ERROR


class TestIndexDiffNameFieldSync:
    def test_index_name_synced_from_object_name(self):
        d = IndexDiff(object_name="my_ix", table_name="t")
        assert d.index_name == "my_ix"

    def test_explicit_index_name_wins(self):
        d = IndexDiff(object_name="x", index_name="explicit", table_name="t")
        assert d.index_name == "explicit"
