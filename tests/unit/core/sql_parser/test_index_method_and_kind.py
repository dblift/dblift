"""SQL-file index methods and kinds survive model extraction."""

import pytest

from dblift.core.sql_parser import SqlParserFactory

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "dialect, sql, index_type, columns, unique",
    [
        ("postgresql", "CREATE INDEX ix ON t USING gin (doc)", "GIN", ["doc"], False),
        ("postgresql", "CREATE INDEX ix ON t USING hash (a)", "HASH", ["a"], False),
        ("postgresql", "CREATE INDEX ix ON t USING gist (a)", "GIST", ["a"], False),
        ("postgresql", "CREATE INDEX ix ON t USING spgist (a)", "SPGIST", ["a"], False),
        ("postgresql", "CREATE INDEX ix ON t USING brin (a)", "BRIN", ["a"], False),
        ("sqlserver", "CREATE CLUSTERED INDEX ix ON t (a)", "CLUSTERED", ["a"], False),
        ("sqlserver", "CREATE NONCLUSTERED INDEX ix ON t (a)", "NONCLUSTERED", ["a"], False),
        ("oracle", "CREATE BITMAP INDEX ix ON t (a)", "BITMAP", ["a"], False),
        ("sqlserver", "CREATE UNIQUE CLUSTERED INDEX ix ON t (a)", "CLUSTERED", ["a"], True),
    ],
)
def test_index_keeps_method_kind_columns_and_uniqueness(dialect, sql, index_type, columns, unique):
    result = SqlParserFactory(dialect).get_parser().parse_sql(sql)
    assert result.success
    assert len(result.indexes) == 1
    index = result.indexes[0]
    assert index.type.upper() == index_type
    assert index.name.lower() == "ix"
    assert index.table_name.lower() == "t"
    assert index.columns == columns
    assert index.unique is unique


@pytest.mark.parametrize("dialect", ["postgresql", "sqlserver", "oracle"])
def test_plain_index_still_uses_btree_default(dialect):
    result = SqlParserFactory(dialect).get_parser().parse_sql("CREATE INDEX ix ON t (a)")
    assert len(result.indexes) == 1
    assert result.indexes[0].type == "BTREE"


@pytest.mark.parametrize("dialect", ["postgresql"])
def test_explicit_btree_keeps_default_type(dialect):
    result = (
        SqlParserFactory(dialect).get_parser().parse_sql("CREATE INDEX ix ON t USING btree (a)")
    )
    assert result.indexes[0].type == "BTREE"


@pytest.mark.parametrize(
    "dialect, sql, index_type, columns, flags, directions",
    [
        (
            "postgresql",
            "CREATE INDEX ix ON t USING btree ((lower(a)), id DESC)",
            "BTREE",
            ["(LOWER(a))", "id"],
            [True, False],
            ["", "DESC"],
        ),
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
    result = SqlParserFactory(dialect).get_parser().parse_sql(sql)
    assert len(result.indexes) == 1
    index = result.indexes[0]
    assert index.type == index_type
    assert index.columns == columns
    assert index.expression_flags == flags
    assert index.sort_directions == directions
