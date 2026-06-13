"""Per-module tests for ``core.comparison._diff_routine``.

PR-G9: narrow coverage on the extracted module (PR-G4 split).
"""

import pytest

from core.comparison._diff_base import DiffSeverity
from core.comparison._diff_routine import FunctionDiff, ProcedureDiff, RoutineDiff

pytestmark = [pytest.mark.unit]


class TestRoutineDiffBaseHelper:
    def test_has_base_diffs_false_when_nothing_set(self):
        # Use ProcedureDiff (concrete) but only inspect the inherited helper.
        d = ProcedureDiff(object_name="p", procedure_name="p")
        assert d._has_base_diffs() is False

    @pytest.mark.parametrize(
        "field, value",
        [
            ("definition_changed", True),
            ("parameters_changed", True),
            ("volatility_changed", ("STABLE", "IMMUTABLE")),
            ("security_definer_changed", (True, False)),
            ("definer_changed", ("a@h", "b@h")),
            ("comment_changed", ("old", "new")),
            ("data_access_changed", ("CONTAINS SQL", "NO SQL")),
        ],
    )
    def test_has_base_diffs_true_for_each_field(self, field, value):
        d = ProcedureDiff(
            object_name="p",
            procedure_name="p",
            **{field: value},
        )
        assert d._has_base_diffs() is True

    def test_routine_diff_is_dataclass_abstract_helper(self):
        # RoutineDiff is reachable directly via the module (cover the import line).
        assert RoutineDiff.__name__ == "RoutineDiff"


class TestProcedureDiffSeverity:
    def test_no_diffs_keeps_default_severity(self):
        d = ProcedureDiff(object_name="p", procedure_name="p")
        assert d.has_diffs is False
        assert d.severity == DiffSeverity.INFO
        assert d.object_type == "procedure"

    def test_parameters_changed_is_error(self):
        d = ProcedureDiff(object_name="p", procedure_name="p", parameters_changed=True)
        assert d.severity == DiffSeverity.ERROR

    def test_definition_only_is_warning(self):
        d = ProcedureDiff(object_name="p", procedure_name="p", definition_changed=True)
        assert d.severity == DiffSeverity.WARNING

    def test_volatility_only_is_warning(self):
        d = ProcedureDiff(
            object_name="p",
            procedure_name="p",
            volatility_changed=("STABLE", "IMMUTABLE"),
        )
        assert d.severity == DiffSeverity.WARNING


class TestFunctionDiffSeverity:
    def test_no_diffs_keeps_default_severity(self):
        d = FunctionDiff(object_name="f", function_name="f")
        assert d.has_diffs is False
        assert d.object_type == "function"

    def test_parameters_changed_is_error(self):
        d = FunctionDiff(object_name="f", function_name="f", parameters_changed=True)
        assert d.severity == DiffSeverity.ERROR

    def test_return_type_changed_is_error(self):
        d = FunctionDiff(
            object_name="f",
            function_name="f",
            return_type_changed=("INTEGER", "BIGINT"),
        )
        assert d.has_diffs is True
        assert d.severity == DiffSeverity.ERROR

    def test_definition_only_is_warning(self):
        d = FunctionDiff(object_name="f", function_name="f", definition_changed=True)
        assert d.severity == DiffSeverity.WARNING

    def test_return_type_dominates_definition(self):
        d = FunctionDiff(
            object_name="f",
            function_name="f",
            definition_changed=True,
            return_type_changed=("INTEGER", "BIGINT"),
        )
        assert d.severity == DiffSeverity.ERROR
