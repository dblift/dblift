"""Identity generation survives model serialization and comparison."""

import pytest

from dblift.core.sql_model.base import SqlColumn


@pytest.mark.parametrize("generation", [None, "ALWAYS", "BY DEFAULT", "BY DEFAULT ON NULL"])
def test_identity_generation_round_trip_and_equality(generation):
    column = SqlColumn("id", "NUMBER", is_identity=True, identity_generation=generation)
    restored = SqlColumn.from_dict(column.to_dict())
    assert restored.identity_generation == generation
    assert restored == column
    assert hash(restored) == hash(column)
    different = SqlColumn(
        "id",
        "NUMBER",
        is_identity=True,
        identity_generation="ALWAYS" if generation != "ALWAYS" else "BY DEFAULT",
    )
    assert restored != different
