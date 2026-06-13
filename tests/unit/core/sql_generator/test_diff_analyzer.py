"""Tests for core/sql_generator/diff_analyzer.py."""

import logging
from unittest.mock import MagicMock

import pytest

from core.comparison.diff_models import ColumnDiff, DiffSeverity, SchemaDiff, TableDiff
from core.sql_generator.diff_analyzer import (
    BreakingChange,
    DependencyGraph,
    DependencyNode,
    DiffAnalysis,
    DiffAnalyzer,
    SafetyCheck,
)
from core.sql_generator.diff_analyzer import ValidationResult as AnalyzerValidationResult

# ---------------------------------------------------------------------------
# Dataclass construction tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDataclassDefaults:
    """Test dataclass construction and field defaults."""

    def test_breaking_change_defaults(self):
        bc = BreakingChange("col_drop", "t.col", "removed", DiffSeverity.ERROR)
        assert bc.change_type == "col_drop"
        assert bc.affected_objects == []

    def test_breaking_change_with_affected(self):
        bc = BreakingChange("col_drop", "t.col", "removed", DiffSeverity.ERROR, ["app1"])
        assert bc.affected_objects == ["app1"]

    def test_dependency_node_defaults(self):
        node = DependencyNode("users", "table")
        assert node.object_name == "users"
        assert node.object_type == "table"
        assert node.depends_on == []
        assert node.depended_by == []

    def test_validation_result_defaults(self):
        vr = AnalyzerValidationResult(is_valid=True)
        assert vr.errors == []
        assert vr.warnings == []
        assert vr.info == []

    def test_safety_check_defaults(self):
        sc = SafetyCheck(safe=True)
        assert sc.error_message is None
        assert sc.warning_message is None
        assert sc.suggestion is None

    def test_diff_analysis_defaults(self):
        vr = AnalyzerValidationResult(is_valid=True)
        da = DiffAnalysis(is_valid=True, validation_result=vr)
        assert da.safety_checks == []
        assert da.breaking_changes == []
        assert da.dependency_graph is None
        assert da.execution_order == []


# ---------------------------------------------------------------------------
# DependencyGraph tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDependencyGraph:
    """Test DependencyGraph add_node, add_dependency, get_execution_order."""

    def test_add_node(self):
        g = DependencyGraph()
        g.add_node("users", "table")
        assert "users" in g.nodes
        assert g.nodes["users"].object_type == "table"

    def test_add_node_idempotent(self):
        g = DependencyGraph()
        g.add_node("users", "table")
        g.add_node("users", "view")  # should not overwrite
        assert g.nodes["users"].object_type == "table"

    def test_add_dependency(self):
        g = DependencyGraph()
        g.add_node("orders", "table")
        g.add_node("users", "table")
        g.add_dependency("orders", "users")
        assert "users" in g.nodes["orders"].depends_on
        assert "orders" in g.nodes["users"].depended_by

    def test_add_dependency_idempotent(self):
        g = DependencyGraph()
        g.add_node("a", "table")
        g.add_node("b", "table")
        g.add_dependency("a", "b")
        g.add_dependency("a", "b")
        assert g.nodes["a"].depends_on.count("b") == 1
        assert g.nodes["b"].depended_by.count("a") == 1

    def test_add_dependency_missing_from_node(self):
        g = DependencyGraph()
        g.add_node("b", "table")
        with pytest.raises(ValueError, match="not found"):
            g.add_dependency("a", "b")

    def test_add_dependency_missing_to_node(self):
        g = DependencyGraph()
        g.add_node("a", "table")
        with pytest.raises(ValueError, match="not found"):
            g.add_dependency("a", "b")

    def test_execution_order_simple_chain(self):
        """A -> B -> C should produce [C, B, A]."""
        g = DependencyGraph()
        g.add_node("a", "table")
        g.add_node("b", "table")
        g.add_node("c", "table")
        g.add_dependency("a", "b")
        g.add_dependency("b", "c")
        order = g.get_execution_order()
        assert order.index("c") < order.index("b") < order.index("a")

    def test_execution_order_diamond(self):
        """Diamond: A->B, A->C, B->D, C->D."""
        g = DependencyGraph()
        for n in ["a", "b", "c", "d"]:
            g.add_node(n, "table")
        g.add_dependency("a", "b")
        g.add_dependency("a", "c")
        g.add_dependency("b", "d")
        g.add_dependency("c", "d")
        order = g.get_execution_order()
        assert order.index("d") < order.index("b")
        assert order.index("d") < order.index("c")
        assert order.index("b") < order.index("a")
        assert order.index("c") < order.index("a")

    def test_execution_order_no_deps(self):
        g = DependencyGraph()
        g.add_node("x", "table")
        g.add_node("y", "table")
        order = g.get_execution_order()
        assert set(order) == {"x", "y"}

    def test_cycle_detection_logs_warning(self, caplog):
        """Cycle A->B->A should log a warning and not raise."""
        g = DependencyGraph()
        g.add_node("a", "table")
        g.add_node("b", "table")
        g.add_dependency("a", "b")
        g.add_dependency("b", "a")
        with caplog.at_level(logging.WARNING):
            order = g.get_execution_order()
        assert any("Circular dependency" in r.message for r in caplog.records)
        # All nodes still appear in output (graceful degradation)
        assert len(order) >= 1


# ---------------------------------------------------------------------------
# DiffAnalyzer helpers
# ---------------------------------------------------------------------------


def _make_column_diff(name="col1", data_type_diff=None, nullable_diff=None):
    """Build a ColumnDiff mock with needed attributes."""
    cd = MagicMock(spec=ColumnDiff)
    cd.column_name = name
    cd.data_type_diff = data_type_diff
    cd.nullable_diff = nullable_diff
    # Make isinstance checks work
    cd.__class__ = ColumnDiff
    return cd


def _make_table_diff(
    table_name="users", missing_columns=None, extra_columns=None, modified_columns=None
):
    """Build a TableDiff mock."""
    td = MagicMock(spec=TableDiff)
    td.table_name = table_name
    td.missing_columns = missing_columns or []
    td.extra_columns = extra_columns or []
    td.modified_columns = modified_columns or []
    td.__class__ = TableDiff
    return td


def _make_schema_diff(modified_tables=None, missing_tables=None, extra_tables=None):
    """Build a SchemaDiff mock."""
    sd = MagicMock(spec=SchemaDiff)
    sd.modified_tables = modified_tables or []
    sd.missing_tables = missing_tables or []
    sd.extra_tables = extra_tables or []
    return sd


# ---------------------------------------------------------------------------
# validate_change tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateChange:

    def setup_method(self):
        self.analyzer = DiffAnalyzer()

    def test_column_incompatible_type_error(self):
        cd = _make_column_diff(data_type_diff=("INTEGER", "VARCHAR(50)"))
        result = self.analyzer.validate_change(cd)
        assert not result.is_valid
        assert any("may not be compatible" in e for e in result.errors)

    def test_column_nullable_to_not_null_warning(self):
        cd = _make_column_diff(nullable_diff=(False, True))
        result = self.analyzer.validate_change(cd)
        assert result.is_valid  # warning, not error
        assert any("NOT NULL" in w for w in result.warnings)

    def test_column_compatible_type_no_error(self):
        cd = _make_column_diff(data_type_diff=("VARCHAR(200)", "VARCHAR(100)"))
        result = self.analyzer.validate_change(cd)
        assert result.is_valid

    def test_table_missing_columns_error(self):
        td = _make_table_diff(missing_columns=["email", "phone"])
        result = self.analyzer.validate_change(td)
        assert not result.is_valid
        assert any("missing 2 columns" in e for e in result.errors)

    def test_table_no_missing_columns_valid(self):
        td = _make_table_diff()
        result = self.analyzer.validate_change(td)
        assert result.is_valid


# ---------------------------------------------------------------------------
# check_data_safety tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckDataSafety:

    def setup_method(self):
        self.analyzer = DiffAnalyzer()

    def test_not_null_on_nullable_unsafe(self):
        cd = _make_column_diff(nullable_diff=(False, True))
        check = self.analyzer.check_data_safety(cd)
        assert not check.safe
        assert "NULL" in check.error_message
        assert check.suggestion is not None

    def test_incompatible_type_unsafe(self):
        cd = _make_column_diff(data_type_diff=("INTEGER", "TEXT"))
        check = self.analyzer.check_data_safety(cd)
        assert not check.safe
        assert "data loss" in check.error_message

    def test_safe_change(self):
        cd = _make_column_diff(data_type_diff=("VARCHAR(200)", "VARCHAR(100)"))
        check = self.analyzer.check_data_safety(cd)
        assert check.safe

    def test_no_diffs_safe(self):
        cd = _make_column_diff()
        check = self.analyzer.check_data_safety(cd)
        assert check.safe

    def test_not_null_takes_precedence_over_type(self):
        """When both nullable and type diffs exist, nullable is checked first."""
        cd = _make_column_diff(
            data_type_diff=("INTEGER", "TEXT"),
            nullable_diff=(False, True),
        )
        check = self.analyzer.check_data_safety(cd)
        assert not check.safe
        assert "NULL" in check.error_message  # nullable check comes first


# ---------------------------------------------------------------------------
# _is_type_compatible tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIsTypeCompatible:

    def setup_method(self):
        self.analyzer = DiffAnalyzer()

    def test_same_type(self):
        assert self.analyzer._is_type_compatible("INTEGER", "INTEGER") is True

    def test_same_type_case_insensitive(self):
        assert self.analyzer._is_type_compatible("Varchar(50)", "varchar(50)") is True

    def test_varchar_size_increase_safe(self):
        assert self.analyzer._is_type_compatible("VARCHAR(200)", "VARCHAR(100)") is True

    def test_varchar_size_decrease_unsafe(self):
        assert self.analyzer._is_type_compatible("VARCHAR(50)", "VARCHAR(100)") is False

    def test_different_types_incompatible(self):
        assert self.analyzer._is_type_compatible("INTEGER", "TEXT") is False

    def test_varchar_no_size_vs_sized(self):
        # VARCHAR (no size) vs VARCHAR(100) — extract_size returns None for first
        assert self.analyzer._is_type_compatible("VARCHAR", "VARCHAR(100)") is False


# ---------------------------------------------------------------------------
# _extract_size tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractSize:

    def setup_method(self):
        self.analyzer = DiffAnalyzer()

    def test_varchar_100(self):
        assert self.analyzer._extract_size("varchar(100)") == 100

    def test_no_parens(self):
        assert self.analyzer._extract_size("integer") is None

    def test_char_1(self):
        assert self.analyzer._extract_size("CHAR(1)") == 1

    def test_nvarchar_max(self):
        assert self.analyzer._extract_size("NVARCHAR(4000)") == 4000


# ---------------------------------------------------------------------------
# _validate_diff tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateDiff:

    def setup_method(self):
        self.analyzer = DiffAnalyzer()

    def test_name_collision_missing_and_extra(self):
        sd = _make_schema_diff(
            missing_tables=["users", "orders"],
            extra_tables=["orders", "logs"],
        )
        result = self.analyzer._validate_diff(sd)
        assert not result.is_valid
        assert any("collision" in e.lower() for e in result.errors)

    def test_no_collision(self):
        sd = _make_schema_diff(missing_tables=["users"], extra_tables=["logs"])
        result = self.analyzer._validate_diff(sd)
        assert result.is_valid

    def test_modified_table_with_missing_columns_propagates(self):
        td = _make_table_diff(missing_columns=["email"])
        sd = _make_schema_diff(modified_tables=[td])
        result = self.analyzer._validate_diff(sd)
        assert not result.is_valid


# ---------------------------------------------------------------------------
# _detect_breaking_changes tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDetectBreakingChanges:

    def setup_method(self):
        self.analyzer = DiffAnalyzer()

    def test_column_removal(self):
        td = _make_table_diff(extra_columns=["old_col"])
        sd = _make_schema_diff(modified_tables=[td])
        changes = self.analyzer._detect_breaking_changes(sd)
        assert len(changes) == 1
        assert changes[0].change_type == "column_removal"
        assert "old_col" in changes[0].object_name

    def test_type_change(self):
        cd = _make_column_diff(name="age", data_type_diff=("BIGINT", "INT"))
        td = _make_table_diff(modified_columns=[cd])
        sd = _make_schema_diff(modified_tables=[td])
        changes = self.analyzer._detect_breaking_changes(sd)
        assert len(changes) == 1
        assert changes[0].change_type == "type_change"

    def test_table_removal(self):
        sd = _make_schema_diff(extra_tables=["deprecated_table"])
        changes = self.analyzer._detect_breaking_changes(sd)
        assert len(changes) == 1
        assert changes[0].change_type == "table_removal"
        assert changes[0].object_name == "deprecated_table"

    def test_multiple_breaking_changes(self):
        cd = _make_column_diff(data_type_diff=("TEXT", "INT"))
        td = _make_table_diff(extra_columns=["gone"], modified_columns=[cd])
        sd = _make_schema_diff(modified_tables=[td], extra_tables=["dead_table"])
        changes = self.analyzer._detect_breaking_changes(sd)
        types = {c.change_type for c in changes}
        assert types == {"column_removal", "type_change", "table_removal"}

    def test_no_breaking_changes(self):
        sd = _make_schema_diff()
        changes = self.analyzer._detect_breaking_changes(sd)
        assert changes == []


# ---------------------------------------------------------------------------
# _calculate_dependencies tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCalculateDependencies:

    def setup_method(self):
        self.analyzer = DiffAnalyzer()

    def test_missing_tables_added(self):
        sd = _make_schema_diff(missing_tables=["t1", "t2"])
        graph = self.analyzer._calculate_dependencies(sd)
        assert "t1" in graph.nodes
        assert "t2" in graph.nodes

    def test_modified_tables_added(self):
        td = _make_table_diff(table_name="orders")
        sd = _make_schema_diff(modified_tables=[td])
        graph = self.analyzer._calculate_dependencies(sd)
        assert "orders" in graph.nodes


# ---------------------------------------------------------------------------
# analyze_diff (full pipeline) tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAnalyzeDiff:

    def setup_method(self):
        self.analyzer = DiffAnalyzer()

    def test_valid_diff_no_issues(self):
        sd = _make_schema_diff(missing_tables=["new_table"])
        result = self.analyzer.analyze_diff(sd)
        assert result.is_valid
        assert result.validation_result.is_valid
        assert result.safety_checks == []
        assert result.breaking_changes == []
        assert "new_table" in result.execution_order

    def test_unsafe_diff_marks_invalid(self):
        cd = _make_column_diff(nullable_diff=(False, True))
        td = _make_table_diff(modified_columns=[cd])
        sd = _make_schema_diff(modified_tables=[td])
        result = self.analyzer.analyze_diff(sd)
        assert not result.is_valid
        assert any(not c.safe for c in result.safety_checks)

    def test_breaking_changes_populated(self):
        sd = _make_schema_diff(extra_tables=["removed_table"])
        result = self.analyzer.analyze_diff(sd)
        assert len(result.breaking_changes) == 1
        assert result.breaking_changes[0].change_type == "table_removal"

    def test_dependency_graph_present(self):
        td = _make_table_diff(table_name="orders")
        sd = _make_schema_diff(modified_tables=[td], missing_tables=["users"])
        result = self.analyzer.analyze_diff(sd)
        assert result.dependency_graph is not None
        assert "orders" in result.dependency_graph.nodes
        assert "users" in result.dependency_graph.nodes

    def test_empty_diff(self):
        sd = _make_schema_diff()
        result = self.analyzer.analyze_diff(sd)
        assert result.is_valid
        assert result.execution_order == []
