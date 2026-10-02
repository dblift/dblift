"""SQL-file partition details and compatibility with develop 13de32cf."""

import copy
import json
from pathlib import Path

import pytest

from dblift.core.sql_model.table import Table
from dblift.core.sql_parser._partition_handler import apply_partition_metadata
from dblift.core.sql_parser.hybrid_parser import HybridParser

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "dialect,clause,count",
    [
        ("mysql", "HASH (id) PARTITIONS 4", 4),
        ("mysql", "KEY (id) PARTITIONS 8", 8),
        ("mariadb", "HASH (id) PARTITIONS 4", 4),
        ("oracle", "HASH (id) PARTITIONS 4 STORE IN (ts1, ts2)", 4),
        ("mysql", "HASH (YEAR(id)) PARTITIONS 4", 4),
    ],
)
def test_sql_partition_count(dialect, clause, count):
    result = HybridParser(dialect).parse_sql(f"CREATE TABLE t (id INT) PARTITION BY {clause}")
    assert result.success
    table = result.tables[0]
    assert table.partition_count == count
    assert table.export_partitions == []
    assert Table.from_dict(table.to_dict()).partition_count == count


@pytest.mark.parametrize(
    "dialect,clause,method,expression,expected",
    [
        (
            "mysql",
            "RANGE (y) (PARTITION p0 VALUES LESS THAN (2020), "
            "PARTITION p1 VALUES LESS THAN MAXVALUE)",
            "RANGE",
            "y",
            [("p0", "VALUES LESS THAN (2020)"), ("p1", "VALUES LESS THAN MAXVALUE")],
        ),
        (
            "oracle",
            "HASH (id) (PARTITION p1, PARTITION p2)",
            "HASH",
            "id",
            [("p1", None), ("p2", None)],
        ),
        (
            "mysql",
            "LIST (y) (PARTITION p0 VALUES IN (1, 2), PARTITION p1 VALUES IN (3))",
            "LIST",
            "y",
            [("p0", "VALUES IN (1, 2)"), ("p1", "VALUES IN (3)")],
        ),
        (
            "oracle",
            "LIST (y) (PARTITION p0 VALUES ('a,b', 'c)'))",
            "LIST",
            "y",
            [("p0", "VALUES ('a,b', 'c)')")],
        ),
        (
            "oracle",
            "RANGE (y) (PARTITION p0 VALUES LESS THAN (TO_DATE('2020-01-01', 'YYYY-MM-DD')))",
            "RANGE",
            "y",
            [("p0", "VALUES LESS THAN (TO_DATE('2020-01-01', 'YYYY-MM-DD'))")],
        ),
    ],
)
def test_sql_partition_list(dialect, clause, method, expression, expected):
    result = HybridParser(dialect).parse_sql(
        f"CREATE TABLE t (id INT, y INT) PARTITION BY {clause}", default_schema="s"
    )
    assert result.success
    table = result.tables[0]
    assert [(p.name, p.partition_description) for p in table.export_partitions] == expected
    for partition in table.export_partitions:
        assert partition.table == table.name
        assert partition.schema == table.schema
        assert partition.dialect == dialect
        assert partition.partition_method == method
        assert partition.partition_expression == expression
        assert partition.subpartitions == []
    assert table.partitions == []
    assert Table.from_dict(table.to_dict()).export_partitions == table.export_partitions


def test_partition_bound_is_verbatim_and_subpartitions_are_not_interpreted():
    table = Table("t", dialect="mysql")
    apply_partition_metadata(
        table,
        "CREATE TABLE t (y INT) PARTITION BY RANGE (y) SUBPARTITION BY HASH (y) "
        "SUBPARTITIONS 2 (PARTITION `p.0` values  less than (2020) "
        "(SUBPARTITION sp0, SUBPARTITION sp1), PARTITION p1 VALUES LESS THAN MAXVALUE)",
    )
    assert [(p.name, p.partition_description) for p in table.export_partitions] == [
        ("p.0", "values  less than (2020)"),
        ("p1", "VALUES LESS THAN MAXVALUE"),
    ]
    assert all(p.subpartitions == [] for p in table.export_partitions)


@pytest.mark.parametrize("factory", [Table, Table.from_options])
def test_partition_count_creation_copy_and_serialization(factory):
    table = factory("t", partition_count=4)
    assert table.to_dict()["partition_count"] == 4
    assert Table.from_dict(table.to_dict()).partition_count == 4
    assert copy.copy(table).partition_count == 4
    assert copy.deepcopy(table).partition_count == 4


def test_count_deserialization():
    table = Table.from_dict({"name": "t", "partition_count": 8})
    assert table.partition_count == 8


def test_legacy_table_serialization_is_byte_identical():
    # Captured with Table('t', dialect='mysql').to_dict() on develop 13de32cf.
    baseline = (Path(__file__).parent / "fixtures/table_without_partition_count.json").read_bytes()
    for table in (Table("t", dialect="mysql"), Table.from_dict(json.loads(baseline))):
        assert (json.dumps(table.to_dict(), indent=2) + "\n").encode() == baseline


@pytest.mark.parametrize(
    "dialect,clause,method,columns",
    [
        ("mysql", "", None, None),
        ("postgresql", "PARTITION BY RANGE (y)", "RANGE", ["Y"]),
        ("mysql", "PARTITION BY HASH (id) PARTITIONS x", "HASH", ["ID"]),
    ],
)
def test_unchanged_partition_guards(dialect, clause, method, columns):
    result = HybridParser(dialect).parse_sql(f"CREATE TABLE t (id INT, y INT) {clause}")
    assert result.success
    table = result.tables[0]
    assert table.partition_method == method
    assert table.partition_columns == columns
    assert table.partition_count is None
    assert table.export_partitions == []
    assert "partition_count" not in table.to_dict()


@pytest.mark.parametrize(
    "tail",
    ["PARTITIONS 4x", "PARTITIONS 4.5", "(PARTITION)", "(PARTITION p0", "(PARTITION p0, nonsense)"],
)
def test_unreadable_details_do_not_raise(tail):
    table = Table("t", dialect="mysql")
    apply_partition_metadata(table, f"CREATE TABLE t (id INT) PARTITION BY HASH (id) {tail}")
    assert table.partition_method == "HASH"
    assert table.partition_columns == ["ID"]
    assert table.partition_count is None
    assert table.export_partitions == []


@pytest.mark.parametrize("tail", ["(PARTITION p0 VALUES IN ('broken)))", '(PARTITION "broken)))'])
def test_unterminated_partition_quotes_leave_only_scheme(tail):
    table = Table("t", dialect="mysql")
    apply_partition_metadata(table, f"CREATE TABLE t (y INT) PARTITION BY LIST (y) {tail}")
    assert table.partition_method == "LIST"
    assert table.partition_columns == ["Y"]
    assert table.export_partitions == []
