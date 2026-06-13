"""Per-module tests for ``core.comparison._diff_base``.

PR-G9: narrow coverage on the extracted module (PR-G4 split). Imports the
module directly rather than via the ``diff_models`` façade so the per-file
coverage cost is unambiguously billed to ``_diff_base``.
"""

from dataclasses import dataclass
from typing import ClassVar

import pytest

from core.comparison._diff_base import DiffResult, DiffSeverity

pytestmark = [pytest.mark.unit]


class TestDiffSeverityEnum:
    """Sanity checks on the severity enum values."""

    def test_values(self):
        assert DiffSeverity.ERROR.value == "error"
        assert DiffSeverity.WARNING.value == "warning"
        assert DiffSeverity.INFO.value == "info"

    def test_distinct_members(self):
        # Three distinct members — guards against accidental enum merges.
        assert len({DiffSeverity.ERROR, DiffSeverity.WARNING, DiffSeverity.INFO}) == 3


class TestPostInitNameFieldFallback:
    """Cover the ``__post_init__`` fallback that copies ``object_name`` into
    the subclass-declared name field when the subclass field is empty."""

    def test_name_field_synced_when_subclass_field_empty(self):
        @dataclass
        class FakeDiff(DiffResult):
            _name_field: ClassVar[str] = "fake_name"
            _object_type_label: ClassVar[str] = "fake"
            fake_name: str = ""

        d = FakeDiff(object_name="alpha")
        assert d.fake_name == "alpha"
        assert d.object_type == "fake"

    def test_name_field_preserved_when_subclass_field_set(self):
        @dataclass
        class FakeDiff(DiffResult):
            _name_field: ClassVar[str] = "fake_name"
            _object_type_label: ClassVar[str] = "fake"
            fake_name: str = ""

        d = FakeDiff(object_name="alpha", fake_name="beta")
        assert d.fake_name == "beta"  # explicit value wins

    def test_no_name_field_no_object_type_label(self):
        # Base DiffResult itself: no _name_field or _object_type_label declared,
        # so __post_init__ should be a no-op.
        d = DiffResult(object_name="x", object_type="table")
        assert d.object_type == "table"
        assert d.has_diffs is False


class TestStaticHelpers:
    """Cover the static helpers on ``DiffResult``."""

    def test_add_tuple_diffs_skips_none(self):
        result = {"differences": {}}
        DiffResult._add_tuple_diffs(
            result,
            {"a": None, "b": ("x", "y"), "c": None},
        )
        assert result["differences"] == {"b": {"expected": "x", "actual": "y"}}

    def test_add_tuple_diffs_with_all_none_produces_empty(self):
        result = {"differences": {}}
        DiffResult._add_tuple_diffs(result, {"a": None})
        assert result["differences"] == {}

    def test_format_tuple_diffs_filters_none(self):
        parts = DiffResult._format_tuple_diffs({"a": None, "b": ("x", "y"), "c": ("p", "q")})
        # Order is preserved from the input dict.
        assert parts == ["b: x → y", "c: p → q"]

    def test_format_tuple_diffs_all_none_returns_empty_list(self):
        parts = DiffResult._format_tuple_diffs({"a": None, "b": None})
        assert parts == []


class TestSetSeverityFromPairs:
    """Cover ``_set_severity_from_pairs`` for every branch."""

    def test_all_falsy_no_diffs(self):
        d = DiffResult(object_name="x")
        d._set_severity_from_pairs(
            [(None, DiffSeverity.ERROR), (False, DiffSeverity.WARNING), ("", DiffSeverity.INFO)]
        )
        assert d.has_diffs is False
        # Severity should stay at the default INFO when no pair contributed.
        assert d.severity == DiffSeverity.INFO

    def test_single_warning_set(self):
        d = DiffResult(object_name="x")
        d._set_severity_from_pairs([(None, DiffSeverity.ERROR), (("a", "b"), DiffSeverity.WARNING)])
        assert d.has_diffs is True
        assert d.severity == DiffSeverity.WARNING

    def test_error_overrides_warning(self):
        d = DiffResult(object_name="x")
        d._set_severity_from_pairs(
            [(("a", "b"), DiffSeverity.WARNING), (("c", "d"), DiffSeverity.ERROR)]
        )
        assert d.severity == DiffSeverity.ERROR

    def test_warning_overrides_info(self):
        d = DiffResult(object_name="x")
        d._set_severity_from_pairs(
            [(("a", "b"), DiffSeverity.INFO), (("c", "d"), DiffSeverity.WARNING)]
        )
        assert d.severity == DiffSeverity.WARNING

    def test_info_only(self):
        d = DiffResult(object_name="x")
        d._set_severity_from_pairs([(("a", "b"), DiffSeverity.INFO)])
        assert d.has_diffs is True
        assert d.severity == DiffSeverity.INFO

    def test_truthy_bool_is_set(self):
        d = DiffResult(object_name="x")
        d._set_severity_from_pairs([(True, DiffSeverity.WARNING)])
        assert d.has_diffs is True
        assert d.severity == DiffSeverity.WARNING


class TestBaseStrAndSummary:
    """Cover the base ``__str__`` and ``get_summary`` branches."""

    def test_str_with_diffs_includes_severity(self):
        d = DiffResult(object_name="x", object_type="table", has_diffs=True)
        d.severity = DiffSeverity.WARNING
        assert "WARNING" in str(d)
        assert "Differences found" in str(d)

    def test_get_summary_match(self):
        d = DiffResult(object_name="x", object_type="table")
        assert d.get_summary() == "table 'x': MATCH"

    def test_get_summary_diff(self):
        d = DiffResult(object_name="x", object_type="table", has_diffs=True)
        d.severity = DiffSeverity.ERROR
        assert "DIFF (error)" in d.get_summary()
