"""Per-module tests for ``core.comparison._diff_view``.

PR-G9: narrow coverage on the extracted module (PR-G4 split). The previously
uncovered line is the ``differences["security_invoker"]`` set branch in
``to_dict``.
"""

import pytest

from core.comparison._diff_base import DiffSeverity
from core.comparison._diff_view import ViewDiff

pytestmark = [pytest.mark.unit]


class TestViewDiffNoChange:
    def test_no_diffs(self):
        d = ViewDiff(object_name="v", view_name="v")
        assert d.has_diffs is False
        assert d.severity == DiffSeverity.INFO
        assert d.object_type == "view"

    def test_to_dict_no_diffs_has_empty_differences(self):
        d = ViewDiff(object_name="v", view_name="v")
        out = d.to_dict()
        assert out["differences"] == {}
        assert out["definition_changed"] is False


class TestViewDiffSeverity:
    def test_definition_changed_is_warning(self):
        d = ViewDiff(object_name="v", view_name="v", definition_changed=True)
        assert d.severity == DiffSeverity.WARNING

    def test_materialized_changed_is_warning(self):
        d = ViewDiff(object_name="v", view_name="v", materialized_changed=(False, True))
        assert d.severity == DiffSeverity.WARNING

    def test_security_definer_changed_is_error(self):
        d = ViewDiff(
            object_name="v",
            view_name="v",
            security_definer_changed=(False, True),
        )
        assert d.severity == DiffSeverity.ERROR

    def test_security_invoker_changed_is_error(self):
        d = ViewDiff(
            object_name="v",
            view_name="v",
            security_invoker_changed=(False, True),
        )
        assert d.severity == DiffSeverity.ERROR


class TestViewDiffSerializeTuple:
    def test_serialize_tuple_none(self):
        d = ViewDiff(object_name="v", view_name="v")
        assert d._serialize_tuple(None) is None

    def test_serialize_tuple_value(self):
        d = ViewDiff(object_name="v", view_name="v")
        assert d._serialize_tuple(("a", "b")) == {"expected": "a", "actual": "b"}


class TestViewDiffToDictBranches:
    """Exercise both ``security_definer`` and ``security_invoker`` branches
    in ``to_dict`` — the previously uncovered tail of the function."""

    def test_security_definer_branch_populated(self):
        d = ViewDiff(
            object_name="v",
            view_name="v",
            security_definer_changed=(False, True),
        )
        out = d.to_dict()
        assert out["differences"]["security_definer"] == {
            "expected": False,
            "actual": True,
        }
        # ``security_invoker`` branch is NOT triggered.
        assert "security_invoker" not in out["differences"]

    def test_security_invoker_branch_populated(self):
        d = ViewDiff(
            object_name="v",
            view_name="v",
            security_invoker_changed=(True, False),
        )
        out = d.to_dict()
        assert out["differences"]["security_invoker"] == {
            "expected": True,
            "actual": False,
        }

    def test_both_branches_populated(self):
        d = ViewDiff(
            object_name="v",
            view_name="v",
            security_definer_changed=(False, True),
            security_invoker_changed=(True, False),
        )
        out = d.to_dict()
        assert "security_definer" in out["differences"]
        assert "security_invoker" in out["differences"]


class TestViewDiffOptionalTuplesSerialization:
    """Round-trip every Optional[tuple] field through ``to_dict``."""

    def test_all_optional_tuple_fields_serialize(self):
        d = ViewDiff(
            object_name="v",
            view_name="v",
            materialized_changed=(False, True),
            unlogged_changed=(False, True),
            algorithm_changed=("MERGE", "UNDEFINED"),
            sql_security_changed=("DEFINER", "INVOKER"),
            definer_changed=("a@h", "b@h"),
            force_changed=("FORCE", "NOFORCE"),
            is_populated_changed=(True, False),
            refresh_method_changed=("FAST", "COMPLETE"),
            refresh_mode_changed=("ON DEMAND", "ON COMMIT"),
            fast_refreshable_changed=(True, False),
        )
        out = d.to_dict()
        for k in (
            "materialized_changed",
            "unlogged_changed",
            "algorithm_changed",
            "sql_security_changed",
            "definer_changed",
            "force_changed",
            "is_populated_changed",
            "refresh_method_changed",
            "refresh_mode_changed",
            "fast_refreshable_changed",
        ):
            assert out[k] is not None
            assert "expected" in out[k] and "actual" in out[k]
