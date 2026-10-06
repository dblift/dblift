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


@pytest.mark.parametrize("ordered", [True, False])
def test_identity_ordering_round_trip_without_changing_old_payloads(ordered):
    old = SqlColumn("id", "NUMBER", is_identity=True)
    assert "identity_ordered" not in old.to_dict()

    column = SqlColumn("id", "NUMBER", is_identity=True, identity_ordered=ordered)
    assert column.to_dict()["identity_ordered"] is ordered
    assert SqlColumn.from_dict(column.to_dict()).identity_ordered is ordered
