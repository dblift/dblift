"""The public core no longer owns private rendering and DML helpers."""

from dblift.core.dialect_boundary import ModelQuirks
from dblift.core.sql_model.trigger import Trigger
from dblift.db.base_quirks import BaseQuirks
from dblift.db.plugins.oracle.quirks import OracleQuirks


def test_private_trigger_body_helpers_are_absent():
    assert not hasattr(Trigger, "_format_body")
    assert not hasattr(ModelQuirks, "wrap_trigger_body")
    assert not hasattr(BaseQuirks, "wrap_trigger_body")
    assert not hasattr(OracleQuirks, "wrap_trigger_body")


def test_private_dml_helpers_are_absent_but_shared_analysis_remains():
    quirks = BaseQuirks(dialect_name="sqlite")
    assert not hasattr(quirks, "statement_updates_restore_key")
    assert not hasattr(quirks, "is_full_table_dml")
    assert quirks.analyze_dml("UPDATE t SET value = 1 WHERE id = 2").events == {"UPDATE"}


def test_trigger_model_fields_and_serialization_remain():
    trigger = Trigger(
        "audit_update",
        "items",
        schema="main",
        timing="AFTER",
        events=["UPDATE"],
        definition="INSERT INTO audit VALUES (NEW.id);",
        dialect="sqlite",
    )
    data = trigger.to_dict()
    assert data["name"] == "audit_update"
    assert data["table_name"] == "items"
    assert data["definition"] == "INSERT INTO audit VALUES (NEW.id);"
    assert data["events"] == ["UPDATE"]
