"""SQL-file models preserve explicit collations and qualified partition methods."""

import pytest

from dblift.core.sql_parser import SqlParserFactory

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "dialect,definition,collation,data_type",
    [
        ("postgresql", 'text COLLATE "C"', "C", "TEXT"),
        ("postgresql", 'varchar(10) COLLATE "en_US"', "en_US", "VARCHAR(10)"),
        ("mysql", "varchar(10) COLLATE utf8mb4_bin", "utf8mb4_bin", "VARCHAR(10)"),
        (
            "mysql",
            "varchar(10) CHARACTER SET latin1 COLLATE latin1_swedish_ci",
            "latin1_swedish_ci",
            "VARCHAR(10)",
        ),
        ("mariadb", "varchar(10) COLLATE utf8mb4_bin", "utf8mb4_bin", "VARCHAR(10)"),
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


@pytest.mark.parametrize("dialect", ["mysql", "mariadb"])
def test_character_set_does_not_invent_a_collation(dialect):
    result = (
        SqlParserFactory(dialect)
        .get_parser()
        .parse_sql("CREATE TABLE t (c VARCHAR(10) CHARACTER SET latin1)")
    )
    assert result.success
    assert result.tables[0].columns[0].collation is None
    assert result.tables[0].columns[0].data_type == "VARCHAR(10)"


def test_oracle_default_text_does_not_declare_a_collation():
    parser = SqlParserFactory("oracle").get_parser()
    parser.sqlglot_parser = None
    result = parser.parse_sql("CREATE TABLE t (c VARCHAR2(30) DEFAULT 'COLLATE BINARY_CI')")
    assert result.success
    assert result.tables[0].columns[0].collation is None


@pytest.mark.parametrize("dialect", ["mysql", "mariadb"])
@pytest.mark.parametrize(
    "clause,method,count",
    [
        ("HASH (id) PARTITIONS 4", "HASH", 4),
        ("KEY (id) PARTITIONS 4", "KEY", 4),
        ("LINEAR HASH (id) PARTITIONS 4", "LINEAR HASH", 4),
        ("LINEAR KEY (id) PARTITIONS 8", "LINEAR KEY", 8),
        ("KEY ALGORITHM=2 (id) PARTITIONS 8", "KEY", 8),
        ("KEY ALGORITHM = 1 (id) PARTITIONS 8", "KEY", 8),
        ("linear\nkey algorithm = 2 (id) partitions 8", "LINEAR KEY", 8),
    ],
)
def test_partition_method_columns_and_count(dialect, clause, method, count):
    result = (
        SqlParserFactory(dialect)
        .get_parser()
        .parse_sql(f"CREATE TABLE t (id INT) PARTITION BY {clause}")
    )
    assert result.success
    table = result.tables[0]
    assert table.partition_method == method
    assert table.partition_columns == ["ID"]
    assert table.partition_count == count


@pytest.mark.parametrize("dialect", ["mysql", "mariadb", "oracle"])
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


@pytest.mark.parametrize("dialect", ["mysql", "mariadb", "oracle"])
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


@pytest.mark.parametrize("dialect", ["mysql", "mariadb", "oracle"])
def test_unpartitioned_table_is_unchanged(dialect):
    result = SqlParserFactory(dialect).get_parser().parse_sql("CREATE TABLE t (id INT)")
    assert result.success
    table = result.tables[0]
    assert table.partition_method is None
    assert table.partition_columns is None
    assert table.partition_count is None
    assert table.export_partitions == []
