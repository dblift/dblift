"""Characterize ``Table.compare_with_defaults`` table, filegroup-option and column differences."""

from typing import Optional

import pytest

from dblift.core.sql_model import table_options
from dblift.core.sql_model.base import SqlColumn, SqlObject, SqlObjectType
from dblift.core.sql_model.table import Table

pytestmark = pytest.mark.unit

# The plugin namespace of the dialect whose tables use filegroup syntax.
FILEGROUP_DIALECT = "sqlserver"


def _table(dialect: Optional[str] = FILEGROUP_DIALECT, *columns: SqlColumn, **options) -> Table:
    table = Table("orders", columns=list(columns), schema="app", dialect=dialect)
    for key, value in options.items():
        table.set_dialect_option(FILEGROUP_DIALECT, key, value)
    return table


def _explicit(table: Table, *properties: str) -> Table:
    for name in properties:
        table.mark_property_explicit(name)
    return table


def _column(name: str, data_type: str = "INT", *explicit: str, **kwargs) -> SqlColumn:
    column = SqlColumn(name, data_type, **kwargs)
    for prop in explicit:
        column.mark_property_explicit(prop)
    return column


class _TableShapedObject(SqlObject):
    """A same-type SQL object that is not a ``Table``."""


def test_a_table_typed_object_that_is_not_a_table_is_an_error():
    other = _TableShapedObject("orders", schema="app", object_type=SqlObjectType.TABLE)

    differences = _table().compare_with_defaults(other)

    assert differences == {"error": "Cannot compare Table with non-Table object"}


def test_an_explicit_but_equal_tablespace_is_not_a_difference():
    left = _explicit(_table(None), "tablespace")
    left.tablespace = right_tablespace = "ts_data"
    right = _table(None)
    right.tablespace = right_tablespace

    assert left.compare_with_defaults(right) == {}


def test_filegroup_options_are_ignored_for_an_unknown_dialect():
    left = _explicit(_table("no-such-dialect", filegroup="FG1"), "filegroup")

    assert left.compare_with_defaults(_table("no-such-dialect", filegroup="FG2")) == {}


def test_filegroup_options_are_not_differences_when_no_plugin_owns_the_syntax(monkeypatch):
    monkeypatch.setattr(table_options, "builtin_namespace_for", lambda capability: None)
    left = _explicit(
        _table(filegroup="FG1", memory_optimized=True), "filegroup", "memory_optimized"
    )

    assert left.compare_with_defaults(_table(filegroup="FG2")) == {}


def test_an_explicit_but_equal_filegroup_is_not_a_difference():
    left = _explicit(_table(filegroup="FG1"), "filegroup")

    assert left.compare_with_defaults(_table(filegroup="FG1")) == {}


def test_an_explicit_but_equal_memory_optimized_flag_is_not_a_difference():
    left = _explicit(_table(memory_optimized=True), "memory_optimized")

    assert left.compare_with_defaults(_table(memory_optimized=True)) == {}


def test_a_system_versioning_mismatch_skips_the_history_details():
    left = _explicit(
        _table(system_versioned=True, history_table="orders_history"), "system_versioned"
    )

    differences = left.compare_with_defaults(_table(history_table="other_history"))

    assert differences == {"system_versioned": {"self": True, "other": False}}


def test_history_details_differ_only_where_both_tables_are_system_versioned():
    shared = dict(system_versioned=True, history_table="orders_history")
    left = _explicit(
        _table(**shared, history_schema="hist", period_start_column="valid_from"),
        "system_versioned",
    )
    right = _table(**shared, history_schema="audit", period_end_column="valid_to")

    differences = left.compare_with_defaults(right)

    assert list(differences.items()) == [
        ("history_schema", {"self": "hist", "other": "audit"}),
        ("period_start_column", {"self": "valid_from", "other": None}),
        ("period_end_column", {"self": None, "other": "valid_to"}),
    ]


def test_every_column_only_on_one_side_is_listed_in_column_order():
    left = _table(None, _column("id"), _column("a"), _column("b"))
    right = _table(None, _column("id"), _column("c"), _column("d"))

    differences = left.compare_with_defaults(right)

    assert differences == {
        "columns_only_in_self": ["a", "b"],
        "columns_only_in_other": ["c", "d"],
    }


def test_an_explicit_but_equal_nullable_is_not_a_difference():
    left = _table(None, _column("id", "INT", "nullable", is_nullable=False))
    right = _table(None, _column("id", "INT", is_nullable=False))

    assert left.compare_with_defaults(right) == {}


def test_a_column_keeps_its_data_type_difference_beside_nullable_and_default():
    left = _table(
        None,
        _column("id", "INT", "nullable", "default_value", is_nullable=False, default_value="0"),
    )
    right = _table(None, _column("ID", "BIGINT", is_nullable=True, default_value="1"))

    differences = left.compare_with_defaults(right)

    assert differences == {
        "column_differences": {
            "id": {
                "data_type": {"self": "INT", "other": "BIGINT"},
                "nullable": {"self": False, "other": True},
                "default_value": {"self": "0", "other": "1"},
            }
        }
    }
    assert list(differences["column_differences"]["id"]) == [
        "data_type",
        "nullable",
        "default_value",
    ]


def test_a_default_value_differs_only_when_explicit_on_either_column():
    implicit = _table(None, _column("id", default_value="0"))
    explicit = _table(None, _column("id", "INT", "default_value", default_value="0"))
    other = _table(None, _column("id", default_value="1"))

    assert implicit.compare_with_defaults(other) == {}
    assert explicit.compare_with_defaults(other) == {
        "column_differences": {"id": {"default_value": {"self": "0", "other": "1"}}}
    }
