"""Index plugin options survive model serialization like Table and View options."""

import pytest

from dblift.core.sql_model.index import Index


@pytest.mark.unit
def test_index_dialect_options_round_trip_without_changing_empty_payload():
    ordinary = Index("items_ix", "items", ["code"], dialect="postgresql")
    assert "dialect_options" not in ordinary.to_dict()

    source = Index("items_ix", "items", ["code"], dialect="sqlite")
    source.set_dialect_option("sqlite", "source_shape", {"columns": ["code"]})
    source.set_dialect_option("other", "flag", True)

    restored = Index.from_dict(source.to_dict())
    assert restored.get_dialect_option("sqlite", "source_shape") == {"columns": ["code"]}
    assert restored.get_dialect_option("other", "flag") is True
    assert restored.to_dict() == source.to_dict()
