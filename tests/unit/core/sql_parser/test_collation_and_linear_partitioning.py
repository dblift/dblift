"""SQL-file models preserve explicit collations and qualified partition methods."""

import pytest

from dblift.core.sql_parser import SqlParserFactory

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "dialect,definition,collation,data_type",
    [
        (
            "sqlserver",
            "nvarchar(10) COLLATE Latin1_General_CS_AS",
            "Latin1_General_CS_AS",
            "NVARCHAR(10)",
        ),
        ("oracle", "VARCHAR2(10) COLLATE BINARY_CI", "BINARY_CI", "VARCHAR2(10)"),
        ("oracle", "VARCHAR2(10) COLLATE binary_ci", "BINARY_CI", "VARCHAR2(10)"),
        ("oracle", 'VARCHAR2(10) COLLATE "BINARY_CI"', "BINARY_CI", "VARCHAR2(10)"),
    ],
)
def test_column_keeps_explicit_collation(dialect, definition, collation, data_type):
    parser = SqlParserFactory(dialect).get_parser()
    result = parser.parse_sql(f"CREATE TABLE t (c {definition}, d VARCHAR(10))")
    assert result.success
    column, plain_column = result.tables[0].columns
    assert column.name.lower() == "c"
    assert column.collation == collation
    assert column.data_type == data_type
    assert plain_column.name.lower() == "d"
    assert plain_column.collation is None


@pytest.mark.parametrize("collation", ["BINARY_CI", "binary_ci", '"BINARY_CI"'])
def test_oracle_regex_column_keeps_collation_separate_from_type(collation):
    parser = SqlParserFactory("oracle").get_parser()
    parser.sqlglot_parser = None
    result = parser.parse_sql(f"CREATE TABLE t (c VARCHAR2(10) COLLATE {collation} NOT NULL)")
    assert result.success
    column = result.tables[0].columns[0]
    assert column.collation == "BINARY_CI"
    assert column.data_type == "VARCHAR2(10)"
    assert column.nullable is False


def test_oracle_default_text_does_not_declare_a_collation():
    parser = SqlParserFactory("oracle").get_parser()
    parser.sqlglot_parser = None
    result = parser.parse_sql("CREATE TABLE t (c VARCHAR2(30) DEFAULT 'COLLATE BINARY_CI')")
    assert result.success
    assert result.tables[0].columns[0].collation is None


@pytest.mark.parametrize("dialect", ["oracle"])
@pytest.mark.parametrize("count", ["0", "-1", "x"])
def test_invalid_partition_count_is_unknown(dialect, count):
    result = (
        SqlParserFactory(dialect)
        .get_parser()
        .parse_sql(f"CREATE TABLE t (id INT) PARTITION BY HASH (id) PARTITIONS {count}")
    )
    assert result.success
    table = result.tables[0]
    assert table.partition_method == "HASH"
    assert table.partition_columns == ["ID"]
    assert table.partition_count is None


@pytest.mark.parametrize("dialect", ["oracle"])
def test_range_partition_list_is_unchanged(dialect):
    result = (
        SqlParserFactory(dialect)
        .get_parser()
        .parse_sql(
            "CREATE TABLE t (id INT) PARTITION BY RANGE (id) "
            "(PARTITION p0 VALUES LESS THAN (10), PARTITION p1 VALUES LESS THAN (MAXVALUE))"
        )
    )
    assert result.success
    table = result.tables[0]
    assert table.partition_method == "RANGE"
    assert table.partition_columns == ["ID"]
    assert table.partition_count is None
    assert [(p.name, p.partition_description) for p in table.export_partitions] == [
        ("p0", "VALUES LESS THAN (10)"),
        ("p1", "VALUES LESS THAN (MAXVALUE)"),
    ]


@pytest.mark.parametrize("dialect", ["oracle"])
def test_unpartitioned_table_is_unchanged(dialect):
    result = SqlParserFactory(dialect).get_parser().parse_sql("CREATE TABLE t (id INT)")
    assert result.success
    table = result.tables[0]
    assert table.partition_method is None
    assert table.partition_columns is None
    assert table.partition_count is None
    assert table.export_partitions == []
