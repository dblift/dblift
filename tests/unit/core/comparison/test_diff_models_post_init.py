"""Tests for consolidated __post_init__ in DiffResult (Story 15-12, DEDUP-02).

Verifies that the base class DiffResult.__post_init__ correctly handles
_name_field sync, _object_type_label assignment, and _calculate_diffs dispatch
for all 20 subclasses.
"""

import pytest

from core.comparison.diff_models import (
    ColumnDiff,
    ConstraintDiff,
    DatabaseLinkDiff,
    DiffResult,
    DiffSeverity,
    EventDiff,
    ExtensionDiff,
    ForeignDataWrapperDiff,
    ForeignServerDiff,
    FunctionDiff,
    IndexDiff,
    LinkedServerDiff,
    ModuleDiff,
    PackageDiff,
    ProcedureDiff,
    RoutineDiff,
    SchemaDiff,
    SequenceDiff,
    SynonymDiff,
    TableDiff,
    TriggerDiff,
    UserDefinedTypeDiff,
    ViewDiff,
)

pytestmark = [pytest.mark.unit]

ALL_SUBCLASSES = [
    ColumnDiff,
    ConstraintDiff,
    TableDiff,
    ViewDiff,
    IndexDiff,
    SequenceDiff,
    TriggerDiff,
    ProcedureDiff,
    FunctionDiff,
    SynonymDiff,
    PackageDiff,
    DatabaseLinkDiff,
    LinkedServerDiff,
    ModuleDiff,
    ForeignDataWrapperDiff,
    ForeignServerDiff,
    ExtensionDiff,
    EventDiff,
    UserDefinedTypeDiff,
    SchemaDiff,
]

# Expected ClassVar values per AC#2
CLASSVAR_EXPECTATIONS = [
    (ColumnDiff, "column_name", "column"),
    (ConstraintDiff, "constraint_name", "constraint"),
    (TableDiff, "table_name", "table"),
    (ViewDiff, "view_name", "view"),
    (IndexDiff, "index_name", "index"),
    (SequenceDiff, "sequence_name", "sequence"),
    (TriggerDiff, "trigger_name", "trigger"),
    (ProcedureDiff, "procedure_name", "procedure"),
    (FunctionDiff, "function_name", "function"),
    (SynonymDiff, "synonym_name", "synonym"),
    (PackageDiff, "package_name", "package"),
    (DatabaseLinkDiff, "link_name", "database_link"),
    (LinkedServerDiff, "server_name", "linked_server"),
    (ModuleDiff, "module_name", "module"),
    (ForeignDataWrapperDiff, "fdw_name", "foreign_data_wrapper"),
    (ForeignServerDiff, "server_name", "foreign_server"),
    (ExtensionDiff, "extension_name", "extension"),
    (EventDiff, "event_name", "event"),
    (UserDefinedTypeDiff, "type_name", "user_defined_type"),
    (SchemaDiff, "schema_name", "schema"),
]


class TestPostInitNameFieldSync:
    """AC#5.1, AC#5.2 — _name_field sync when empty, not overridden when set."""

    def test_name_field_sync_when_empty(self):
        diff = ColumnDiff(object_name="col1")
        assert diff.column_name == "col1"

    def test_name_field_not_overridden_when_set(self):
        """AC#5.2 — _name_field not overridden when already set."""
        diff = ColumnDiff(object_name="x", column_name="y")
        assert diff.column_name == "y"


class TestPostInitObjectTypeLabel:
    """AC#5.3 — object_type set from _object_type_label."""

    def test_object_type_set_from_label(self):
        diff = ColumnDiff(object_name="x")
        assert diff.object_type == "column"


class TestDiffResultBaseUnchanged:
    """AC#5.4 — DiffResult instantiated directly still works."""

    def test_diff_result_base_unchanged(self):
        result = DiffResult(object_name="x", object_type="table")
        assert result.object_type == "table"
        assert result.has_diffs is False


# TableDiff overrides __post_init__ for _BOOL_FIELDS validation (Story 18-6) — exclude from check
_SUBCLASSES_WITHOUT_POST_INIT = [c for c in ALL_SUBCLASSES if c is not TableDiff]


class TestNoPostInitInSubclassDict:
    """AC#5.5 — No subclass (except TableDiff) has __post_init__ in its own __dict__."""

    @pytest.mark.parametrize("cls", _SUBCLASSES_WITHOUT_POST_INIT, ids=lambda c: c.__name__)
    def test_no_post_init_in_subclass_dict(self, cls):
        assert (
            "__post_init__" not in cls.__dict__
        ), f"{cls.__name__} still has __post_init__ in its own __dict__"


class TestDiffResultHasPostInitInOwnDict:
    """AC#5.6 — DiffResult HAS __post_init__ in its own __dict__."""

    def test_diff_result_has_post_init_in_own_dict(self):
        assert "__post_init__" in DiffResult.__dict__


class TestCalculateDiffsDispatch:
    """M1 — __post_init__ dispatches _calculate_diffs() — has_diffs computed at construction."""

    def test_calculate_diffs_sets_has_diffs_true(self):
        """_calculate_diffs() is called during __post_init__ and computes has_diffs=True."""
        diff = ColumnDiff(object_name="col1", data_type_diff=("int", "varchar"))
        assert diff.has_diffs is True

    def test_calculate_diffs_sets_severity(self):
        """_calculate_diffs() also elevates severity correctly."""
        diff = ColumnDiff(object_name="col1", data_type_diff=("int", "varchar"))
        assert diff.severity == DiffSeverity.ERROR

    def test_calculate_diffs_no_diff_fields_leaves_has_diffs_false(self):
        """No diff fields → has_diffs stays False (dispatch happened, no-op result)."""
        diff = ColumnDiff(object_name="col1")
        assert diff.has_diffs is False


class TestClassVarValues:
    """M2 — Each subclass declares the correct _name_field and _object_type_label per AC#2."""

    @pytest.mark.parametrize(
        "cls,name_field,type_label",
        CLASSVAR_EXPECTATIONS,
        ids=lambda x: x.__name__ if isinstance(x, type) else x,
    )
    def test_classvar_values_match_ac2_table(self, cls, name_field, type_label):
        assert (
            cls._name_field == name_field
        ), f"{cls.__name__}._name_field={cls._name_field!r}, expected {name_field!r}"
        assert (
            cls._object_type_label == type_label
        ), f"{cls.__name__}._object_type_label={cls._object_type_label!r}, expected {type_label!r}"


class TestRoutineDiffIntermediateClass:
    """L2 — RoutineDiff is an intermediate class (excluded from ALL_SUBCLASSES).

    RoutineDiff inherits _name_field="" and _object_type_label="" from DiffResult.
    It was never modified by this story and never had __post_init__ in its own __dict__.
    """

    def test_routine_diff_inherits_post_init_without_crash(self):
        """RoutineDiff works correctly with inherited __post_init__."""
        diff = RoutineDiff(object_name="x", object_type="routine")
        assert diff.object_type == "routine"
        assert diff.has_diffs is False

    def test_routine_diff_has_no_post_init_in_own_dict(self):
        """RoutineDiff never had __post_init__ and still doesn't."""
        assert "__post_init__" not in RoutineDiff.__dict__
