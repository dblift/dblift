"""Subject-owner round trips through a legacy Trigger extension constructor."""

import json

import pytest

from dblift.core.sql_model.trigger import Trigger
from tests.unit.core.sql_model.test_trigger_subclass_codec import _legacy_subclass


@pytest.mark.parametrize("owner,qualified", [("data", "data.orders"), (None, "orders")])
def test_legacy_constructor_keeps_explicit_subject_owner_round_trip(owner, qualified):
    extension = _legacy_subclass(Trigger)
    trigger = extension.from_dict(
        {
            "name": "orders_changed",
            "table_name": "orders",
            "schema": "audit",
            "table_schema": owner,
        }
    )
    restored = extension.from_dict(json.loads(json.dumps(trigger.to_dict())))

    assert type(restored) is extension
    assert restored.schema == "audit"
    assert restored.table_schema == owner
    assert restored.qualified_table_name == qualified
