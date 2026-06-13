"""Tests for diff_utils module.

This module tests utility functions for generating GitHub-style unified diffs
from diff models.
"""

import pytest

from core.comparison.diff_models import (
    FunctionDiff,
    IndexDiff,
    PackageDiff,
    ProcedureDiff,
    SequenceDiff,
    TableDiff,
    TriggerDiff,
    ViewDiff,
)
from core.logger.formatters.diff_utils import (
    generate_function_diff_sql,
    generate_generic_diff_sql,
    generate_index_diff_sql,
    generate_package_diff_sql,
    generate_procedure_diff_sql,
    generate_sequence_diff_sql,
    generate_table_diff_sql,
    generate_trigger_diff_sql,
    generate_unified_diff,
    generate_view_diff_sql,
)
from core.sql_model.base import SqlColumn
from core.sql_model.table import Table


def _make_table(name: str = "users", columns=None, dialect: str = "postgresql") -> Table:
    cols = columns or [SqlColumn(name="id", data_type="int4", is_nullable=False)]
    return Table(name=name, schema="public", columns=cols, constraints=[], dialect=dialect)


@pytest.mark.unit
class TestGenerateUnifiedDiff:
    """Test generate_unified_diff function."""

    def test_generate_diff_identical(self):
        """Test generating diff for identical SQL."""
        before = "CREATE TABLE users (id INTEGER);"
        after = "CREATE TABLE users (id INTEGER);"

        result = generate_unified_diff(before, after)

        assert "lines" in result
        assert len(result["lines"]) > 0
        assert all(line["type"] == "equal" for line in result["lines"])

    def test_generate_diff_added_lines(self):
        """Test generating diff for added lines."""
        before = "CREATE TABLE users (id INTEGER);"
        after = "CREATE TABLE users (id INTEGER, name VARCHAR(100));"

        result = generate_unified_diff(before, after)

        assert "lines" in result
        # Should have added lines
        assert any(line["type"] == "added" for line in result["lines"])

    def test_generate_diff_removed_lines(self):
        """Test generating diff for removed lines."""
        before = "CREATE TABLE users (id INTEGER, name VARCHAR(100));"
        after = "CREATE TABLE users (id INTEGER);"

        result = generate_unified_diff(before, after)

        assert "lines" in result
        # Should have removed lines
        assert any(line["type"] == "removed" for line in result["lines"])

    def test_generate_diff_custom_labels(self):
        """Test generating diff with custom labels."""
        before = "CREATE TABLE users (id INTEGER);"
        after = "CREATE TABLE users (id INTEGER);"

        result = generate_unified_diff(before, after, before_label="Expected", after_label="Actual")

        assert "lines" in result
        assert "before_lines" in result
        assert "after_lines" in result


@pytest.mark.unit
class TestGenerateViewDiffSql:
    """Test generate_view_diff_sql function."""

    def test_generate_view_diff_with_definitions(self):
        """Test generating view diff SQL with definitions."""
        view_diff = ViewDiff(object_name="test_view", view_name="test_view")
        view_diff.expected_definition = "SELECT * FROM users"
        view_diff.actual_definition = "SELECT id, name FROM users"

        before, after = generate_view_diff_sql(view_diff)

        assert before == "SELECT * FROM users"
        assert after == "SELECT id, name FROM users"

    def test_generate_view_diff_without_definitions(self):
        """Test generating view diff SQL without definitions."""
        view_diff = ViewDiff(object_name="test_view", view_name="test_view")

        before, after = generate_view_diff_sql(view_diff)

        assert "-- View test_view (expected)" in before
        assert "-- View test_view (actual)" in after


@pytest.mark.unit
class TestGenerateProcedureDiffSql:
    """Test generate_procedure_diff_sql function."""

    def test_generate_procedure_diff_with_parameters(self):
        """Test generating procedure diff SQL with parameters."""
        procedure_diff = ProcedureDiff(object_name="test_proc", procedure_name="test_proc")
        procedure_diff.expected_parameters = ["id INTEGER", "name VARCHAR(100)"]
        procedure_diff.actual_parameters = ["id INTEGER"]

        before, after = generate_procedure_diff_sql(procedure_diff)

        assert "CREATE PROCEDURE test_proc" in before
        assert "id INTEGER" in before
        assert "name VARCHAR(100)" in before
        assert "CREATE PROCEDURE test_proc" in after
        assert "id INTEGER" in after

    def test_generate_procedure_diff_no_parameters(self):
        """Test generating procedure diff SQL without parameters."""
        procedure_diff = ProcedureDiff(object_name="test_proc", procedure_name="test_proc")

        before, after = generate_procedure_diff_sql(procedure_diff)

        assert "CREATE PROCEDURE test_proc" in before
        assert "CREATE PROCEDURE test_proc" in after


@pytest.mark.unit
class TestGenerateFunctionDiffSql:
    """Test generate_function_diff_sql function."""

    def test_generate_function_diff_with_return_type(self):
        """Test generating function diff SQL with return type change."""
        function_diff = FunctionDiff(object_name="test_func", function_name="test_func")
        function_diff.expected_parameters = ["id INTEGER"]
        function_diff.actual_parameters = ["id INTEGER"]
        function_diff.return_type_changed = ("INTEGER", "VARCHAR(100)")

        before, after = generate_function_diff_sql(function_diff)

        assert "CREATE FUNCTION test_func" in before
        assert "INTEGER" in before
        assert "CREATE FUNCTION test_func" in after
        assert "VARCHAR(100)" in after

    def test_generate_function_diff_no_return_type(self):
        """Test generating function diff SQL without return type."""
        function_diff = FunctionDiff(object_name="test_func", function_name="test_func")

        before, after = generate_function_diff_sql(function_diff)

        assert "CREATE FUNCTION test_func" in before
        assert "RETURNS VOID" in before
        assert "CREATE FUNCTION test_func" in after
        assert "RETURNS VOID" in after


@pytest.mark.unit
class TestGenerateIndexDiffSql:
    """Test generate_index_diff_sql function."""

    def test_generate_index_diff_with_columns(self):
        """Test generating index diff SQL with columns."""
        index_diff = IndexDiff(object_name="idx_users", index_name="idx_users", table_name="users")
        index_diff.expected_columns = ["id", "name"]
        index_diff.actual_columns = ["id"]

        before, after = generate_index_diff_sql(index_diff)

        assert "CREATE INDEX idx_users" in before
        assert "id" in before
        assert "name" in before
        assert "CREATE INDEX idx_users" in after
        assert "id" in after

    def test_generate_index_diff_with_uniqueness(self):
        """Test generating index diff SQL with uniqueness change."""
        index_diff = IndexDiff(object_name="idx_users", index_name="idx_users", table_name="users")
        index_diff.expected_columns = ["id"]
        index_diff.actual_columns = ["id"]
        index_diff.uniqueness_changed = (False, True)

        before, after = generate_index_diff_sql(index_diff)

        assert "CREATE INDEX" in before
        assert "CREATE UNIQUE INDEX" in after


@pytest.mark.unit
class TestGenerateSequenceDiffSql:
    """Test generate_sequence_diff_sql function."""

    def test_generate_sequence_diff_with_changes(self):
        """Test generating sequence diff SQL with changes."""
        sequence_diff = SequenceDiff(object_name="seq_users", sequence_name="seq_users")
        sequence_diff.start_value_changed = (1, 100)
        sequence_diff.increment_changed = (1, 5)

        before, after = generate_sequence_diff_sql(sequence_diff)

        assert "CREATE SEQUENCE seq_users" in before
        assert "START WITH 1" in before
        assert "INCREMENT BY 1" in before
        assert "CREATE SEQUENCE seq_users" in after
        assert "START WITH 100" in after
        assert "INCREMENT BY 5" in after

    def test_generate_sequence_diff_no_changes(self):
        """Test generating sequence diff SQL without changes."""
        sequence_diff = SequenceDiff(object_name="seq_users", sequence_name="seq_users")

        before, after = generate_sequence_diff_sql(sequence_diff)

        assert "CREATE SEQUENCE seq_users" in before
        assert "-- No changes detected" in before
        assert "CREATE SEQUENCE seq_users" in after
        assert "-- No changes detected" in after


@pytest.mark.unit
class TestGenerateTriggerDiffSql:
    """Test generate_trigger_diff_sql function."""

    def test_generate_trigger_diff_with_changes(self):
        """Test generating trigger diff SQL with changes."""
        trigger_diff = TriggerDiff(
            object_name="trg_users", trigger_name="trg_users", table_name="users"
        )
        trigger_diff.timing_changed = ("BEFORE", "AFTER")
        trigger_diff.event_changed = ("INSERT", "UPDATE")

        before, after = generate_trigger_diff_sql(trigger_diff)

        assert "CREATE TRIGGER trg_users" in before
        assert "BEFORE INSERT" in before
        assert "CREATE TRIGGER trg_users" in after
        assert "AFTER UPDATE" in after

    def test_generate_trigger_diff_no_changes(self):
        """Test generating trigger diff SQL without changes."""
        trigger_diff = TriggerDiff(
            object_name="trg_users", trigger_name="trg_users", table_name="users"
        )

        before, after = generate_trigger_diff_sql(trigger_diff)

        assert "CREATE TRIGGER trg_users" in before
        assert "BEFORE INSERT" in before
        assert "CREATE TRIGGER trg_users" in after
        assert "BEFORE INSERT" in after


@pytest.mark.unit
class TestGeneratePackageDiffSql:
    """Test generate_package_diff_sql function."""

    def test_generate_package_diff_with_spec_and_body(self):
        """Test generating package diff SQL with spec and body."""
        package_diff = PackageDiff(object_name="test_pkg", package_name="test_pkg")
        package_diff.expected_spec = "CREATE PACKAGE test_pkg AS\n  PROCEDURE proc1;\nEND;"
        package_diff.expected_body = "CREATE PACKAGE BODY test_pkg AS\n  PROCEDURE proc1 IS\n  BEGIN\n    NULL;\n  END;\nEND;"
        package_diff.actual_spec = "CREATE PACKAGE test_pkg AS\n  PROCEDURE proc2;\nEND;"
        package_diff.actual_body = "CREATE PACKAGE BODY test_pkg AS\n  PROCEDURE proc2 IS\n  BEGIN\n    NULL;\n  END;\nEND;"

        before, after = generate_package_diff_sql(package_diff)

        assert "Package Specification" in before
        assert "Package Body" in before
        assert "proc1" in before
        assert "Package Specification" in after
        assert "Package Body" in after
        assert "proc2" in after

    def test_generate_package_diff_without_spec_and_body(self):
        """Test generating package diff SQL without spec and body."""
        package_diff = PackageDiff(object_name="test_pkg", package_name="test_pkg")

        before, after = generate_package_diff_sql(package_diff)

        assert "CREATE PACKAGE test_pkg" in before
        assert "CREATE PACKAGE BODY test_pkg" in before
        assert "CREATE PACKAGE test_pkg" in after
        assert "CREATE PACKAGE BODY test_pkg" in after


@pytest.mark.unit
class TestGenerateTableDiffSql:
    """Test generate_table_diff_sql renders both sides via render_table_ddl."""

    def test_generate_table_diff_with_table_refs(self):
        expected = _make_table(columns=[SqlColumn(name="id", data_type="int4", is_nullable=False)])
        actual = _make_table(
            columns=[
                SqlColumn(name="id", data_type="int4", is_nullable=False),
                SqlColumn(name="name", data_type="varchar(100)", is_nullable=True),
            ]
        )
        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            expected_table=expected,
            actual_table=actual,
        )
        result = generate_table_diff_sql(table_diff)
        assert result is not None
        before, after = result
        assert "CREATE TABLE" in before
        assert "CREATE TABLE" in after
        assert "name" in after
        assert "name" not in before

    def test_generate_table_diff_returns_none_when_both_refs_missing(self):
        table_diff = TableDiff(object_name="users", table_name="users")
        assert generate_table_diff_sql(table_diff) is None

    def test_generate_table_diff_one_sided_expected_only(self):
        """Missing table case: present on expected side only."""
        table = _make_table()
        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            expected_table=table,
            actual_table=None,
        )
        result = generate_table_diff_sql(table_diff)
        assert result is not None
        before, after = result
        assert "CREATE TABLE" in before
        assert "not present on actual side" in after

    def test_generate_table_diff_one_sided_actual_only(self):
        """Extra table case: present on actual side only."""
        table = _make_table()
        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            expected_table=None,
            actual_table=table,
        )
        result = generate_table_diff_sql(table_diff)
        assert result is not None
        before, after = result
        assert "not present on expected side" in before
        assert "CREATE TABLE" in after

    def test_generate_table_diff_native_pg_types_preserved(self):
        """Native serial/int4/numeric/timestamptz preserved — no sqlglot rewrite."""
        cols = [
            SqlColumn(name="id", data_type="serial", is_nullable=False, is_identity=True),
            SqlColumn(name="amount", data_type="numeric(10, 2)", is_nullable=False),
        ]
        table = Table(
            name="orders", schema="public", columns=cols, constraints=[], dialect="postgresql"
        )
        table_diff = TableDiff(
            object_name="orders",
            table_name="orders",
            expected_table=table,
            actual_table=table,
        )
        before, after = generate_table_diff_sql(table_diff)
        assert before == after
        assert "serial" in before.lower()
        assert "numeric(10, 2)" in before.lower()
        assert "GENERATED BY DEFAULT AS IDENTITY" not in before.upper()
        assert "DECIMAL" not in before.upper()


@pytest.mark.unit
class TestGenerateGenericDiffSql:
    """Test generate_generic_diff_sql function."""

    def test_generate_generic_diff_table(self):
        """Test generating generic diff SQL for table."""
        table = _make_table()
        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            expected_table=table,
            actual_table=table,
        )

        result = generate_generic_diff_sql(table_diff)

        assert result is not None
        assert len(result) == 2

    def test_generate_generic_diff_view(self):
        """Test generating generic diff SQL for view."""
        view_diff = ViewDiff(object_name="test_view", view_name="test_view")
        view_diff.expected_definition = "SELECT * FROM users"
        view_diff.actual_definition = "SELECT * FROM users"

        result = generate_generic_diff_sql(view_diff)

        assert result is not None
        assert len(result) == 2

    def test_generate_generic_diff_index(self):
        """Test generating generic diff SQL for index."""
        index_diff = IndexDiff(object_name="idx_users", index_name="idx_users", table_name="users")

        result = generate_generic_diff_sql(index_diff)

        assert result is not None
        assert len(result) == 2

    def test_generate_generic_diff_sequence(self):
        """Test generating generic diff SQL for sequence."""
        sequence_diff = SequenceDiff(object_name="seq_users", sequence_name="seq_users")

        result = generate_generic_diff_sql(sequence_diff)

        assert result is not None
        assert len(result) == 2

    def test_generate_generic_diff_trigger(self):
        """Test generating generic diff SQL for trigger."""
        trigger_diff = TriggerDiff(
            object_name="trg_users", trigger_name="trg_users", table_name="users"
        )

        result = generate_generic_diff_sql(trigger_diff)

        assert result is not None
        assert len(result) == 2

    def test_generate_generic_diff_procedure(self):
        """Test generating generic diff SQL for procedure."""
        procedure_diff = ProcedureDiff(object_name="test_proc", procedure_name="test_proc")

        result = generate_generic_diff_sql(procedure_diff)

        assert result is not None
        assert len(result) == 2

    def test_generate_generic_diff_function(self):
        """Test generating generic diff SQL for function."""
        function_diff = FunctionDiff(object_name="test_func", function_name="test_func")

        result = generate_generic_diff_sql(function_diff)

        assert result is not None
        assert len(result) == 2

    def test_generate_generic_diff_package(self):
        """Test generating generic diff SQL for package."""
        package_diff = PackageDiff(object_name="test_pkg", package_name="test_pkg")

        result = generate_generic_diff_sql(package_diff)

        assert result is not None
        assert len(result) == 2

    def test_generate_generic_diff_with_definitions(self):
        """Test generating generic diff SQL with expected/actual definitions."""

        class CustomDiff:
            object_type = "custom"
            expected_definition = "CREATE CUSTOM obj;"
            actual_definition = "CREATE CUSTOM obj_modified;"

        diff_obj = CustomDiff()
        result = generate_generic_diff_sql(diff_obj)

        assert result is not None
        assert len(result) == 2
        assert "CREATE CUSTOM obj" in result[0]
        assert "CREATE CUSTOM obj_modified" in result[1]

    def test_generate_generic_diff_unsupported(self):
        """Test generating generic diff SQL for unsupported type."""

        class UnsupportedDiff:
            object_type = "unsupported"

        diff_obj = UnsupportedDiff()
        result = generate_generic_diff_sql(diff_obj)

        assert result is None
