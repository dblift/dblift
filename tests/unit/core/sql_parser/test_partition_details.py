"""SQL-file partition details and compatibility with develop 13de32cf."""

import copy
import json
from pathlib import Path

import pytest

from dblift.core.sql_model.table import Table

pytestmark = pytest.mark.unit


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
