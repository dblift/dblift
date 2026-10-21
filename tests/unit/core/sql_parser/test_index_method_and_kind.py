"""SQL-file index methods and kinds survive model extraction."""

import pytest

from tests.support.legacy_oracle_hybrid import hybrid_for

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "dialect, sql, index_type, columns, unique",
    [
        ("sqlserver", "CREATE CLUSTERED INDEX ix ON t (a)", "CLUSTERED", ["a"], False),
        ("sqlserver", "CREATE NONCLUSTERED INDEX ix ON t (a)", "NONCLUSTERED", ["a"], False),
        ("oracle", "CREATE BITMAP INDEX ix ON t (a)", "BITMAP", ["a"], False),
        ("sqlserver", "CREATE UNIQUE CLUSTERED INDEX ix ON t (a)", "CLUSTERED", ["a"], True),
    ],
)
def test_index_keeps_method_kind_columns_and_uniqueness(dialect, sql, index_type, columns, unique):
    result = hybrid_for(dialect).parse_sql(sql)
    assert result.success
    assert len(result.indexes) == 1
    index = result.indexes[0]
    assert index.type.upper() == index_type
    assert index.name.lower() == "ix"
    assert index.table_name.lower() == "t"
    assert index.columns == columns
    assert index.unique is unique


@pytest.mark.parametrize("dialect", ["sqlserver", "oracle"])
def test_plain_index_still_uses_btree_default(dialect):
    result = hybrid_for(dialect).parse_sql("CREATE INDEX ix ON t (a)")
    assert len(result.indexes) == 1
    assert result.indexes[0].type == "BTREE"


@pytest.mark.parametrize(
    "dialect, sql, index_type, columns, flags, directions",
    [
        (
            "sqlserver",
            "CREATE UNIQUE NONCLUSTERED INDEX [ix] ON [s].[t] ([a] DESC, [id])",
            "NONCLUSTERED",
            ["a", "id"],
            [False, False],
            ["DESC", ""],
        ),
    ],
)
def test_index_method_preserves_expressions_and_directions(
    dialect, sql, index_type, columns, flags, directions
):
    result = hybrid_for(dialect).parse_sql(sql)
    assert len(result.indexes) == 1
    index = result.indexes[0]
    assert index.type == index_type
    assert index.columns == columns
    assert index.expression_flags == flags
    assert index.sort_directions == directions
